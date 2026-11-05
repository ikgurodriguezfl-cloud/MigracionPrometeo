"""Pruebas del seguimiento del sprint 2; no conectan Access, MySQL ni Koha."""
import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lotes import HistorialLotes, acciones_lote, lotes_de_ejemplo
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter
from pymarc import Field, Record, Subfield
from panel_lotes import (
    campos_desde_marcxml, campos_desde_iso2709, campos_para_revision,
    datos_grafico, ejemplares_desde_registro_marc, filtrar_lotes,
    record_para_edicion, resumir_lotes,
)


class LotesTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / 'historial.json'
        self.historial = HistorialLotes(self.ruta)

    def test_historial_nuevo_vacio_no_inventa_lotes(self):
        self.assertEqual(self.historial.listar(), [])
        self.assertFalse(self.ruta.exists())

    def test_historial_de_interfaz_institucional_conserva_detalle_y_usuario(self):
        lote = self.historial.recibir('copia.mdb', 2)
        self.historial.actualizar(lote.id, estado='concluido', etapa='finalizado',
            correctos=1, omitidos=1, fichas_correctas=[7])
        documento = json.loads(self.ruta.read_text(encoding='utf-8'))
        resultados = [
            dict(id=7, referencia='Ficha 7', titulo='Poesía', estado='Convertida', motivos=[]),
            dict(id=8, referencia='Ficha 8', titulo='Otra ficha', estado='Omitida', motivos=[]),
        ]
        documento['lotes'][0].update(resultados=resultados, usuario='operador', omitir_existentes=False)
        self.ruta.write_text(json.dumps(documento, ensure_ascii=False), encoding='utf-8')
        anterior = self.ruta.read_bytes()
        recargado = HistorialLotes(self.ruta)
        self.assertFalse(recargado.solo_lectura)
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(recargado.obtener(lote.id).resultados, resultados)
        recargado.actualizar(lote.id, evento='Revisión del lote.')
        persistido = HistorialLotes(self.ruta).obtener(lote.id)
        self.assertEqual(persistido.resultados, resultados)
        self.assertEqual(persistido.usuario, 'operador')
        self.assertFalse(persistido.omitir_existentes)

    def test_historial_con_detalle_inconsistente_se_conserva_para_revision(self):
        lote = self.historial.recibir('copia.mdb', 1)
        documento = json.loads(self.ruta.read_text(encoding='utf-8'))
        documento['lotes'][0]['resultados'] = [
            dict(id=1, referencia='Ficha 1', titulo='Prueba', estado='Convertida', motivos=[])]
        self.ruta.write_text(json.dumps(documento), encoding='utf-8')
        anterior = self.ruta.read_bytes()
        recargado = HistorialLotes(self.ruta)
        self.assertTrue(recargado.solo_lectura)
        self.assertEqual(self.ruta.read_bytes(), anterior)

    def test_recibir_reutiliza_espera_y_persiste_acentos(self):
        primero = self.historial.recibir('Poesía y niñez.mdb', 100)
        segundo = self.historial.recibir('Poesía y niñez.mdb', 120)
        self.assertEqual(primero.id, segundo.id)
        recargado = HistorialLotes(self.ruta).obtener(primero.id)
        self.assertEqual(recargado.total_recibidos, 120)
        self.assertIn('Poesía', recargado.fuente)

    def test_reprocesamiento_crea_un_intento_vinculado_sin_tocar_el_lote_origen(self):
        origen = self.historial.recibir('copia.mdb', 3)
        origen = self.historial.actualizar(
            origen.id, estado='concluido', etapa='finalizado',
            correctos=3, fichas_correctas=[1, 2, 3],
        )

        intento = self.historial.recibir_reprocesamiento(origen.id, 3)

        self.assertNotEqual(intento.id, origen.id)
        self.assertEqual(intento.lote_origen, origen.id)
        self.assertEqual(intento.total_objetivo, origen.total_objetivo)
        self.assertEqual(self.historial.obtener(origen.id).correctos, 3)
        self.assertTrue(acciones_lote(origen)['reprocesar'])
        self.assertFalse(acciones_lote(intento)['reprocesar'])
        recargado = HistorialLotes(self.ruta).obtener(intento.id)
        self.assertEqual(recargado.lote_origen, origen.id)

    def test_reprocesamiento_rechaza_lote_activo_o_respaldo_con_conteo_distinto(self):
        activo = self.historial.recibir('activo.mdb', 2)
        with self.assertRaisesRegex(ValueError, 'finalizados o detenidos'):
            self.historial.recibir_reprocesamiento(activo.id, 2)

        terminado = self.historial.recibir('terminado.mdb', 2)
        self.historial.actualizar(
            terminado.id, estado='concluido', etapa='finalizado',
            correctos=2, fichas_correctas=[1, 2],
        )
        with self.assertRaisesRegex(ValueError, 'número de fichas distinto'):
            self.historial.recibir_reprocesamiento(terminado.id, 3)

    def test_persiste_version_y_huella_del_mapeo_marc(self):
        lote = self.historial.recibir('mapeo.mdb', 1)
        huella = 'a' * 64
        self.historial.actualizar(
            lote.id, version_mapeo='1.0', huella_mapeo=huella)

        recargado = HistorialLotes(self.ruta).obtener(lote.id)

        self.assertEqual(recargado.version_mapeo, '1.0')
        self.assertEqual(recargado.huella_mapeo, huella)

    def test_limited_recibidos_no_se_confunde_con_alcance(self):
        lote = self.historial.recibir('copia.mdb', 100)
        lote = self.historial.actualizar(lote.id, estado='en_proceso', etapa='conversion', total_objetivo=10,
            correctos=3, omitidos=2, errores=1, fichas_correctas=[1, 2, 3])
        self.assertEqual((lote.total_recibidos, lote.total_objetivo), (100, 10))
        self.assertEqual((lote.procesados, lote.pendientes, lote.progreso), (6, 4, 60))

    def test_no_permite_concluir_con_errores_pendientes_o_sin_registros(self):
        for cambio in ({'errores': 1}, {'correctos': 9, 'fichas_correctas': list(range(9))}, {'total_objetivo': 0}):
            with self.subTest(cambio=cambio):
                lote = self.historial.recibir(f'copia-{len(str(cambio))}.mdb', 10)
                with self.assertRaises(ValueError):
                    self.historial.actualizar(lote.id, estado='concluido', etapa='finalizado', **cambio)
                self.assertEqual(self.historial.obtener(lote.id).estado, 'en_espera')

    def test_no_permite_contadores_incoherentes_ni_booleanos(self):
        lote = self.historial.recibir('copia.mdb', 10)
        for cambio in ({'omitidos': -1}, {'errores': True}, {'total_objetivo': 11}, {'correctos': 1}, {'omitidos': 11}):
            with self.subTest(cambio=cambio), self.assertRaises(ValueError):
                self.historial.actualizar(lote.id, **cambio)

    def test_reabrir_proceso_interrumpido_requiere_revision(self):
        lote = self.historial.recibir('copia.mdb', 10)
        self.historial.actualizar(lote.id, estado='en_proceso', etapa='conversion', omitidos=3)
        recuperado = HistorialLotes(self.ruta).obtener(lote.id)
        self.assertEqual(recuperado.estado, 'con_incidencias')
        self.assertEqual(recuperado.pendientes, 7)
        self.assertIn('cerró', recuperado.incidencias[0]['mensaje'])

    def test_100_por_ciento_con_error_no_es_exito(self):
        lote = self.historial.recibir('copia.mdb', 10)
        lote = self.historial.actualizar(lote.id, estado='con_incidencias', etapa='revision', errores=10)
        self.assertEqual(lote.progreso, 100)
        self.assertFalse(acciones_lote(lote, destino_coincide=True)['exportar'])

    def test_matriz_de_acciones_y_demostracion_aislada(self):
        ejemplos = lotes_de_ejemplo()
        for lote in ejemplos:
            acciones = acciones_lote(lote, fuente_validada=True, destino_coincide=True)
            self.assertEqual(
                acciones['reprocesar'],
                lote.estado in ('concluido', 'con_incidencias', 'detenido'),
            )
            self.assertEqual(acciones['iniciar'], lote.estado == 'en_espera')
            self.assertEqual(acciones['exportar'], lote.estado == 'concluido')
            self.assertEqual(acciones['revision'], bool(lote.correctos))
            self.assertEqual(acciones['resumen'], lote.estado in ('concluido', 'con_incidencias'))
            for bloqueos in ({'ocupado': True}, {'demostracion': True}):
                acciones = acciones_lote(lote, fuente_validada=True, destino_coincide=True, **bloqueos)
                self.assertFalse(acciones['iniciar']); self.assertFalse(acciones['exportar'])
                self.assertFalse(acciones['revision'])
        self.assertEqual(self.historial.listar(), [])

    def test_resumen_agrega_metricas_y_estados_sin_modificar_lotes(self):
        ejemplos = lotes_de_ejemplo()

        resumen = resumir_lotes(ejemplos)

        self.assertEqual(resumen['total_lotes'], 4)
        self.assertEqual(resumen['fichas_correctas'], 224)
        self.assertEqual(resumen['ejemplares'], 0)
        self.assertEqual(resumen['requieren_revision'], 1)
        self.assertEqual(resumen['por_estado'], {
            'en_espera': 1,
            'en_proceso': 1,
            'concluido': 1,
            'con_incidencias': 1,
            'detenido': 0,
        })
        self.assertEqual(self.historial.listar(), [])

    def test_filtros_de_fecha_estado_y_ordenamiento(self):
        ejemplos = lotes_de_ejemplo()
        fechas = (
            '2026-11-04T09:00:00-07:00',
            '2026-10-30T09:00:00-07:00',
            '2026-10-01T09:00:00-07:00',
            '2025-12-31T09:00:00-07:00',
        )
        for lote, fecha in zip(ejemplos, fechas):
            lote.creado_en = fecha

        semana = filtrar_lotes(
            ejemplos, periodo='Últimos 7 días', hoy=date(2026, 11, 4),
        )
        revision = filtrar_lotes(
            ejemplos, estado='Con incidencias', hoy=date(2026, 11, 4),
        )
        mayor_error = filtrar_lotes(ejemplos, orden='Más errores')
        mas_antiguos = filtrar_lotes(ejemplos, orden='Más antiguos')

        self.assertEqual([lote.id for lote in semana], [ejemplos[0].id, ejemplos[1].id])
        self.assertEqual([lote.id for lote in revision], [ejemplos[3].id])
        self.assertEqual(mayor_error[0].errores, 10)
        self.assertEqual(mas_antiguos[0].creado_en, fechas[3])
        with self.assertRaises(ValueError):
            filtrar_lotes(ejemplos, periodo='Fecha inválida')

    def test_graficos_muestran_resultados_comparables_y_limite_por_lote(self):
        ejemplos = lotes_de_ejemplo()
        resumen = resumir_lotes(ejemplos)

        _, etiquetas, resultados, colores = datos_grafico(
            ejemplos, resumen, 'Resultado de fichas',
        )
        self.assertEqual(etiquetas, ['Correctas', 'Omitidas', 'Con error', 'Pendientes'])
        self.assertEqual(resultados, [224, 21, 10, 145])
        self.assertEqual(len(colores), len(resultados))

        titulo, etiquetas, cantidades, colores = datos_grafico(
            ejemplos, resumen, 'Fichas correctas por lote',
        )
        self.assertEqual(titulo, 'Fichas correctas por lote')
        self.assertEqual(cantidades, [90, 80, 54, 0])
        self.assertEqual(len(etiquetas), len(colores))
        with self.assertRaises(ValueError):
            datos_grafico(ejemplos, resumen, 'Gráfico desconocido')

    def test_parser_marcxml_separa_campos_indicadores_y_subcampos(self):
        xml = (
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            '<leader>00000nam a2200000 i 4500</leader>'
            '<controlfield tag="001">123</controlfield>'
            '<datafield tag="245" ind1="1" ind2="0">'
            '<subfield code="a">Título</subfield>'
            '<subfield code="b">subtítulo</subfield>'
            '</datafield></record>'
        )

        campos = campos_desde_marcxml(xml)

        self.assertEqual(campos[0]['etiqueta'], 'LDR')
        self.assertEqual(campos[1]['contenido'], '123')
        self.assertEqual(campos[2]['etiqueta'], '245')
        self.assertEqual(campos[2]['indicadores'], '10')
        self.assertEqual(campos[2]['contenido'], '$a Título  |  $b subtítulo')
        with self.assertRaises(ValueError):
            campos_desde_marcxml('<record><broken></record>')
        with self.assertRaises(ValueError):
            campos_desde_marcxml('<collection />')

    def test_revision_recupera_campos_de_iso2709_si_el_xml_es_invalido(self):
        registro = Record(force_utf8=True)
        registro.leader = '00000nam a2200000 i 4500'
        registro.add_field(Field(tag='001', data='123'))
        registro.add_field(Field(
            tag='245', indicators=['1', '0'],
            subfields=[Subfield('a', 'Título')],
        ))
        iso2709 = registro.as_marc()

        campos = campos_desde_iso2709(iso2709)
        campos_recuperados, aviso = campos_para_revision({
            'marca_marcxml': '<record><incompleto></record>',
            'marca_iso2709': iso2709,
        })

        self.assertEqual(campos[1]['contenido'], '123')
        self.assertEqual(campos[2]['etiqueta'], '245')
        self.assertEqual(campos[2]['indicadores'], '10')
        self.assertEqual(campos[2]['contenido'], '$a Título')
        self.assertEqual(campos_recuperados, campos)
        self.assertIn('ISO2709', aviso)
        with self.assertRaisesRegex(ValueError, 'MARC ISO2709'):
            campos_desde_iso2709(b'invalid')

    def test_revision_recupera_ejemplares_desde_campos_952_si_tabla_vacia(self):
        record = Record(force_utf8=True)
        record.add_field(Field(
            tag='952', indicators=[' ', ' '],
            subfields=[
                Subfield('a', 'ITT'), Subfield('b', 'ITT'),
                Subfield('p', 'BAR-351'), Subfield('c', 'V2 T1'),
                Subfield('z', 'available'), Subfield('o', 'QA76'),
            ],
        ))

        ejemplares = ejemplares_desde_registro_marc({
            'marca_iso2709': record.as_marc(),
            'marca_marcxml': '',
        })

        self.assertEqual(len(ejemplares), 1)
        self.assertEqual(ejemplares[0]['num_adqui'], 'BAR-351')
        self.assertEqual(ejemplares[0]['branch_koha'], 'ITT / ITT')
        self.assertEqual(ejemplares[0]['volumen'], 'V2 T1')
        self.assertEqual(ejemplares[0]['accesible'], 'available')
        self.assertEqual(ejemplares[0]['signatura'], 'QA76')
        self.assertEqual(ejemplares[0]['biblioteca'], '—')

    def test_consulta_revision_devuelve_registros_y_ejemplares_por_ficha(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [
                {'id_ficha_acceso': 12, 'marca_marcxml': '<record />',
                 'marca_iso2709': b'marc12'},
                {'id_ficha_acceso': 15, 'marca_marcxml': '<record />',
                 'marca_iso2709': b'marc15'},
            ],
            [{'id_ficha_acceso': 15, 'num_adqui': 'BAR-15'}],
        ]
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor

        registros = writer.obtener_registros_revision([12, 15])

        self.assertEqual(registros[0]['ejemplares'], [])
        self.assertEqual(registros[1]['ejemplares'][0]['num_adqui'], 'BAR-15')
        self.assertEqual(cursor.execute.call_args_list[0].args[1], (12, 15))
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (12, 15))
        self.assertIn(
            'JOIN registros_marc r ON r.id = e.id_registro_marc',
            cursor.execute.call_args_list[1].args[0],
        )

    def test_consulta_revision_avisa_si_falta_un_registro_del_lote(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor

        with self.assertRaisesRegex(ValueError, 'no contiene todos los registros'):
            writer.obtener_registros_revision([12])
        with self.assertRaises(ValueError):
            writer.obtener_registros_revision([True])

    def test_marcxml_completo_y_iso2709_equivalente_se_validan(self):
        record = Record(force_utf8=True)
        record.leader = '00000nam a2200000 i 4500'
        record.add_field(Field(tag='001', data='123'))
        record.add_field(Field(tag='005', data='20261104120000.0'))
        record.add_field(Field(tag='008', data='0' * 40))
        record.add_field(Field(
            tag='040', indicators=[' ', ' '],
            subfields=[Subfield('a', 'ABC'), Subfield('c', 'ABC')],
        ))
        record.add_field(Field(
            tag='245', indicators=['1', '0'],
            subfields=[Subfield('a', 'Title')],
        ))

        marcxml = MarcConverter().record_a_marcxml(record)
        validado = MySQLWriter._validar_registro_propuesto(
            marcxml, record.as_marc(),
        )

        self.assertTrue(marcxml.endswith('</collection>'))
        self.assertEqual(validado['001'].data, '123')
        with self.assertRaisesRegex(ValueError, 'exactamente un registro'):
            MySQLWriter._validar_registro_propuesto(
                marcxml, record.as_marc() * 2,
            )

    def test_rechaza_fecha_marc_005_incompleta(self):
        record = Record(force_utf8=True)
        record.leader = '00000nam a2200000 i 4500'
        record.add_field(Field(tag='001', data='123'))
        record.add_field(Field(tag='005', data='20261104120000'))
        record.add_field(Field(tag='008', data='0' * 40))
        record.add_field(Field(
            tag='040', indicators=[' ', ' '],
            subfields=[Subfield('a', 'ABC'), Subfield('c', 'ABC')],
        ))
        record.add_field(Field(
            tag='245', indicators=['1', '0'],
            subfields=[Subfield('a', 'Title')],
        ))
        marcxml = MarcConverter().record_a_marcxml(record)

        with self.assertRaisesRegex(ValueError, '005 debe tener el formato MARC'):
            MySQLWriter._validar_registro_propuesto(marcxml, record.as_marc())

    def test_editor_recupera_marcxml_o_permite_reconstruir_ficha_corrupta(self):
        record = Record(force_utf8=True)
        record.add_field(Field(tag='001', data='123'))
        marcxml = MarcConverter().record_a_marcxml(record)

        recuperado, aviso = record_para_edicion({
            'marca_marcxml': marcxml,
            'marca_iso2709': b'invalido',
        })
        self.assertEqual(recuperado['001'].data, '123')
        self.assertIn('ISO2709', aviso)

        nuevo, aviso = record_para_edicion({
            'marca_marcxml': '<xml roto',
            'marca_iso2709': b'invalido',
        })
        self.assertEqual(str(nuevo.leader), '00000nam a2200000 i 4500')
        self.assertIn('ficha vacía', aviso)

    def test_quien_propone_no_puede_resolver_su_propuesta(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'propuesto_por': 'revisor'}
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor

        with self.assertRaisesRegex(ValueError, 'no puede aprobarla ni rechazarla'):
            writer.resolver_correccion(7, 'LOTE-1', 'revisor', True)

        writer.conn.rollback.assert_called_once()
        writer.conn.commit.assert_not_called()
        self.assertEqual(cursor.execute.call_count, 1)

    def test_reprocesamiento_inserta_solo_ejemplares_que_no_existen(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'id': 42}
        cursor.fetchall.return_value = [{
            'num_adqui': 'BAR-1', 'biblioteca': 'CENTRAL',
            'branch_koha': 'CEN', 'volumen': None, 'ejemplar': None,
            'tomo': None, 'accesible': None, 'fecha_ingreso': None,
            'signatura': 'QA76',
        }]
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor
        existentes = {
            'NumAdqui': 'BAR-1', 'Biblioteca': 'CENTRAL',
        }
        faltante = {
            'NumAdqui': 'BAR-2', 'Biblioteca': 'OTRA',
        }

        with patch.object(writer, 'insertar_ejemplar') as insertar:
            agregados, sin_mapeo = writer.insertar_ejemplares_faltantes(
                7, [existentes, faltante],
                {'CENTRAL': 'CEN', 'OTRA': 'OTR'}, signatura='QA76',
            )

        self.assertEqual(agregados, 1)
        self.assertEqual(sin_mapeo, [])
        insertar.assert_called_once_with(42, 7, faltante, 'OTR', 'QA76')

    def test_observacion_se_valida_y_se_guarda_con_evento_de_auditoria(self):
        cursor = MagicMock()
        cursor.lastrowid = 15
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor

        observacion_id = writer.registrar_observacion_revision(
            'LOTE-1', 17, 'revisora', 'Verificar campo 245.',
        )

        self.assertEqual(observacion_id, 15)
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn('INSERT INTO observaciones_revision', cursor.execute.call_args_list[0].args[0])
        self.assertEqual(
            cursor.execute.call_args_list[0].args[1],
            ('LOTE-1', 17, 'revisora', 'Verificar campo 245.'),
        )
        self.assertIn('INSERT INTO log_migracion', cursor.execute.call_args_list[1].args[0])
        writer.conn.commit.assert_called_once()

        with self.assertRaisesRegex(ValueError, '5000 caracteres'):
            writer.registrar_observacion_revision(
                'LOTE-1', 17, 'revisora', 'x' * 5001,
            )

    def test_listar_observaciones_filtra_por_lote_y_ficha(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{
            'id': 1, 'usuario': 'revisora',
            'observacion': 'Validar 245$a', 'fecha': '2026-11-04 10:00:00',
        }]
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor

        observaciones = writer.listar_observaciones_revision('LOTE-1', 17)

        self.assertEqual(observaciones[0]['observacion'], 'Validar 245$a')
        self.assertEqual(cursor.execute.call_args.args[1], ('LOTE-1', 17))

    def test_aprobar_correccion_actualiza_marc_y_audita_en_una_transaccion(self):
        record = Record(force_utf8=True)
        record.leader = '00000nam a2200000 i 4500'
        record.add_field(Field(tag='001', data='123'))
        record.add_field(Field(tag='005', data='20261104120000.0'))
        record.add_field(Field(tag='008', data='0' * 40))
        record.add_field(Field(
            tag='040', indicators=[' ', ' '],
            subfields=[Subfield('a', 'ABC'), Subfield('c', 'ABC')],
        ))
        record.add_field(Field(
            tag='245', indicators=['1', '0'],
            subfields=[Subfield('a', 'Title')],
        ))
        marcxml = MarcConverter().record_a_marcxml(record)
        iso2709 = record.as_marc()
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                'id': 7, 'id_ficha_acceso': 123,
                'marca_marcxml_propuesta': marcxml,
                'marca_iso2709_propuesta': iso2709,
                'huella_original': MySQLWriter.huella_registro(
                    '<record/>', b'original',
                ),
                'propuesto_por': 'revisor',
            },
            {
                'marca_marcxml': '<record/>',
                'marca_iso2709': b'original',
            },
        ]
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        writer.conn.cursor.return_value.__enter__.return_value = cursor

        resultado = writer.resolver_correccion(7, 'LOTE-1', 'aprobador', True)

        self.assertEqual(resultado, 'APROBADA')
        writer.conn.commit.assert_called_once()
        writer.conn.rollback.assert_not_called()
        self.assertTrue(any(
            'UPDATE registros_marc SET marca_marcxml' in llamada.args[0]
            for llamada in cursor.execute.call_args_list
        ))
        self.assertTrue(any(
            'INSERT INTO log_migracion' in llamada.args[0]
            for llamada in cursor.execute.call_args_list
        ))

    def test_no_exporta_omitidos_como_nuevos_registros(self):
        lote = self.historial.recibir('copia.mdb', 10)
        lote = self.historial.actualizar(lote.id, estado='concluido', etapa='finalizado', omitidos=10)
        self.assertFalse(acciones_lote(lote, destino_coincide=True)['exportar'])
        self.assertTrue(acciones_lote(lote)['resumen'])

    def test_lote_detenido_conserva_avance_y_no_permita_exportar(self):
        lote = self.historial.recibir('copia.mdb', 10)
        lote = self.historial.actualizar(lote.id, estado='detenido', etapa='conversion',
            correctos=2, omitidos=1, fichas_correctas=[1, 2], evento='Detenido por el usuario.')
        self.assertEqual((lote.procesados, lote.pendientes, lote.progreso), (3, 7, 30))
        politica = acciones_lote(lote, fuente_validada=True, destino_coincide=True)
        self.assertTrue(politica['resumen'])
        self.assertFalse(politica['iniciar'])
        self.assertFalse(politica['exportar'])
        recuperado = HistorialLotes(self.ruta).obtener(lote.id)
        self.assertEqual(recuperado.estado, 'detenido')
        self.assertEqual(recuperado.fichas_correctas, [1, 2])

    def test_detener_solo_el_lote_activo_y_una_sola_vez(self):
        lote = lotes_de_ejemplo()[1]
        self.assertTrue(acciones_lote(lote, ocupado=True, lote_activo_id=lote.id)['detener'])
        for cambio in ({'ocupado': False}, {'lote_activo_id': 'OTRO-LOTE'},
                       {'demostracion': True}, {'detencion_solicitada': True}):
            opciones = {'ocupado': True, 'lote_activo_id': lote.id, **cambio}
            self.assertFalse(acciones_lote(lote, **opciones)['detener'])
        politica = acciones_lote(lote, ocupado=True, lote_activo_id=lote.id, detencion_solicitada=True)
        self.assertTrue(politica['detencion_solicitada'])

    def test_no_se_marca_detenido_un_lote_que_ya_atendio_todo(self):
        lote = self.historial.recibir('copia.mdb', 10)
        with self.assertRaises(ValueError):
            self.historial.actualizar(lote.id, estado='detenido', etapa='conversion', omitidos=10)

    def test_rechaza_credenciales_en_historial(self):
        lote = self.historial.recibir('copia.mdb', 10)
        with self.assertRaises(ValueError):
            self.historial.actualizar(lote.id, destino={'password': 'NO_GUARDAR'})
        self.assertNotIn('NO_GUARDAR', self.ruta.read_text(encoding='utf-8'))

    def test_almacen_corrupto_no_se_sobrescribe(self):
        self.ruta.write_text('{invalido', encoding='utf-8')
        historial = HistorialLotes(self.ruta)
        self.assertTrue(historial.solo_lectura)
        with self.assertRaises(OSError):
            historial.recibir('copia.mdb', 10)
        self.assertEqual(self.ruta.read_text(), '{invalido')

    def test_fallo_al_guardar_conserva_memoria_y_archivo(self):
        lote = self.historial.recibir('copia.mdb', 10)
        anterior = self.ruta.read_bytes()
        with patch('lotes.os.replace', side_effect=OSError('sin permisos')):
            with self.assertRaises(OSError):
                self.historial.actualizar(lote.id, estado='en_proceso', etapa='conexion')
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(self.historial.obtener(lote.id).estado, 'en_espera')


if __name__ == '__main__':
    unittest.main()
