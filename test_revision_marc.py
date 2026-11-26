"""Regresiones del recorrido de corrección y exportación por ficha."""
import csv
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock, patch
from zipfile import ZipFile

from pymarc import Field, MARCReader, Subfield, parse_xml_to_array

from exportacion_marc import exportar_lote
from gui_app import MigracionApp
from lotes import HistorialLotes, Lote
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter
from panel_lotes import parsear_subcampos, record_para_edicion, serializar_registro, texto_incidencias_lote, texto_subcampos
from validacion_marc import ERROR, cargar_framework, es_repetible, estado_ficha, inspeccionar_copias, validar_ficha


def ficha(numero=1):
    return MarcConverter().ficha_a_record({
        'Ficha_No': numero, 'Titulo': 'Bibliotecas de Nayarit', 'Autor': 'Pérez, Elena',
        'ISBN': '9780306406157', 'DatosFijos': '261118s2020    mx ' + ' ' * 11 + '000 0 spa d',
        'EtiquetasMARC': '¦260Tepic :Editorial,2020.¦30052 páginas¦650Bibliotecas',
    }, [])


def copias(record, numero):
    return dict(id_ficha_acceso=numero, marca_marcxml=MarcConverter().record_a_marcxml(record),
                marca_iso2709=record.as_marc())


class RevisionMarcTests(unittest.TestCase):
    def test_fuente_008_solo_cambia_la_ultima_posicion_y_conserva_original(self):
        conversor = MarcConverter()
        prefijo = ficha()['008'].data[:39]
        for origen, esperado in [('D', 'd'), ('g', '|'), ('C', 'c'), (' ', ' '), ('|', '|'), ('u', 'u')]:
            with self.subTest(origen=origen):
                original = prefijo + origen
                record = conversor.ficha_a_record(dict(Ficha_No=1, Titulo='Obra', DatosFijos=original), [])
                self.assertEqual(record['008'].data, prefijo + esperado)
                self.assertIn(original, record['887']['a'])
                xml, iso = serializar_registro(record)
                self.assertFalse(any(i.gravedad == ERROR for i in inspeccionar_copias(xml, iso)[1]))

    def test_avisos_de_material_se_deduplican_sin_perder_otros_avisos_008(self):
        app = MigracionApp.__new__(MigracionApp)
        app.marc_converter = MarcConverter()
        fijo = ficha()['008'].data
        datos = dict(Ficha_No=8, Titulo='Obra', DatosFijos=fijo[:22] + '?' + fijo[23:],
                     EtiquetasMARC='¦260Tepic :Editorial,1975.')
        _, avisos = app._convertir_y_guardar_ficha(Mock(), datos, 8, [], {}, {})
        observaciones = [mensaje for campo, mensaje, _ in avisos if campo == '008']
        self.assertTrue(any('incompatibles con libros' in m for m in observaciones))
        self.assertFalse(any('Hay posiciones de material' in m for m in observaciones))
        self.assertTrue(any('difiere de la fecha' in m for m in observaciones))

    def test_historial_22_recupera_bloqueos_fuera_de_la_muestra_y_ubica_fichas(self):
        with TemporaryDirectory() as td:
            historial = HistorialLotes(Path(td) / 'historial.json')
            lote = historial.recibir('copia.mdb', 3, incremental=True)
            filas = [dict(id=n, estado=estado, motivos=motivos, referencia=f'Ficha {n}', titulo='Libro')
                     for n, estado, motivos in [(10, 'Omitida', ['Ya existe']),
                         (11, 'Convertida', ['008: Error · 008 · 39-39', '245: Error · 245 · título']),
                         (12, 'Convertida', ['008: Advertencia · 008'])]]
            muestra = [dict(referencia=f'Ficha {f} · 020', mensaje='Sin ISBN') for f in (11, 12)]
            historial.actualizar(lote.id, estado='con_incidencias', etapa='revision', filas=filas,
                                 version_mapeo='2.2', huella_mapeo='0'*64, correctos=2, omitidos=1, incidencias=muestra)
            anterior = historial.bloqueos_anteriores(lote.id)
            self.assertEqual(anterior[0], 1)
            lote = historial.obtener(lote.id, resumen=True)
            texto = texto_incidencias_lote(lote, anterior)
            self.assertIn('Ficha 11 · Error', texto)
            self.assertNotIn('Sin ISBN', texto)
            texto = texto_incidencias_lote(lote, anterior, mostrar_advertencias=True)
            self.assertIn('2 × 020', texto)
            self.assertIsNone(historial.posicion_convertida(lote.id, 10))
            self.assertEqual(historial.posicion_convertida(lote.id, 12), 1)

    def test_ir_a_ficha_anterior_y_proponer_ajuste_008(self):
        with TemporaryDirectory() as td:
            root = tk.Tk()
            root.withdraw()
            app = MigracionApp(root, HistorialLotes(Path(td) / 'historial.json'))
            self.addCleanup(app.cerrar)
            panel = app.panel_lotes
            lote = Lote('LOTE-QA', 'copia.mdb', 51, 51, correctos=51)
            panel.lote_actual = Mock(return_value=lote)
            panel.politica = Mock(return_value={'revision': True, 'proponer_correccion': True})
            panel.posicion_convertida = Mock(return_value=50)
            record = ficha(2316)
            prefijo = record['008'].data[:39]
            record['008'].data = prefijo + 'g'
            guardada = dict(copias(record, 2316), huella_revision='huella anterior')
            panel.revisar = Mock(side_effect=lambda lote, inicio, cantidad: [guardada] if inicio else [copias(ficha(), 1)])
            panel.proponer = Mock(return_value=1)

            def descendientes(padre):
                for hijo in padre.winfo_children():
                    yield hijo
                    yield from descendientes(hijo)

            def pulsar(padre, texto):
                next(w for w in descendientes(padre) if isinstance(w, ttk.Button) and w.cget('text') == texto).invoke()

            panel._revisar()
            revision = panel._historial_paginas['revision']
            with patch('panel_lotes.simpledialog.askinteger', return_value=2316):
                pulsar(revision, 'Ir a ficha…')
            limite = time.monotonic() + 3
            while time.monotonic() < limite and panel.revisar.call_count < 2:
                root.update()
            panel.revisar.assert_called_with(lote.id, 50, 50)
            root.update()
            pulsar(revision, 'Corregir / proponer')
            root.update()
            editor = panel._historial_paginas['editor']
            with patch('panel_lotes.messagebox.showinfo'), patch('panel_lotes.messagebox.showwarning'):
                pulsar(editor, 'Ajustar 008/39')
                root.update()
                pulsar(editor, 'Enviar a aprobación')
            panel.proponer.assert_called_once()
            ident, num, xml, iso, huella = panel.proponer.call_args.args
            self.assertEqual((ident, num, huella), (lote.id, 2316, 'huella anterior'))
            nueva, issues = inspeccionar_copias(xml, iso)
            self.assertEqual(nueva['008'].data, prefijo + '|')
            self.assertFalse(any(i.gravedad == ERROR for i in issues))
            self.assertEqual(record['008'].data, prefijo + 'g')

    def test_tres_estados_y_correccion_sin_inventar_datos(self):
        rec = ficha()
        self.assertEqual(estado_ficha(validar_ficha(rec)), 'Válida')
        rec.remove_fields('020', '100', '300', '650')
        self.assertEqual(estado_ficha(validar_ficha(rec)), 'Con advertencias')
        rec.remove_fields('245')
        self.assertEqual(estado_ficha(validar_ficha(rec)), 'Con errores')
        with self.assertRaisesRegex(ValueError, '245'):
            serializar_registro(rec)
        rec.add_field(Field(tag='245', indicators=['0', '0'], subfields=[Subfield('a', 'Título verificado')]))
        xml, iso = serializar_registro(rec)
        _, issues = inspeccionar_copias(xml, iso)
        self.assertNotIn('245', [i.campo for i in issues])
        self.assertEqual(estado_ficha(issues), 'Con advertencias')

    def test_campos_indicadores_repeticion_y_subcampos(self):
        rec = ficha()
        for tag in ('100', '245', '650'):
            rec.add_field(deepcopy(rec[tag]))
        rec['245'].subfields.extend([Subfield('a', 'Segundo'), Subfield('y', 'Inválido')])
        rec['245'].indicator2 = 'x'
        errors = [i for i in validar_ficha(rec) if i.gravedad == ERROR]
        self.assertEqual({i.campo for i in errors}, {'100', '245'})
        self.assertTrue(any(i.campo == '245' and i.subcampo == 'a' and i.ocurrencia == 1 for i in errors))
        self.assertTrue(any(i.subcampo == 'y' for i in errors))
        self.assertTrue(any('Indicador 2' in i.detalle for i in errors))
        self.assertTrue(es_repetible('650'))
        self.assertFalse(es_repetible('245'))

    def test_leader_directorio_utf8_y_copias_distintas(self):
        rec = ficha()
        xml, iso = serializar_registro(rec)
        corrupto = bytearray(iso)
        corrupto[31:36] = b'00004'
        for dato in [bytes(corrupto), iso[:-1], iso + iso, iso.replace(b'Bibliotecas', b'\xffibliotecas', 1)]:
            with self.subTest(dato=dato[:32]):
                self.assertEqual(estado_ficha(inspeccionar_copias(xml, dato)[1]), 'Con errores')
        with self.assertRaisesRegex(ValueError, 'LDR'):
            modificado = deepcopy(rec)
            modificado.leader = '0' * 24
            serializar_registro(modificado)
        with self.assertRaisesRegex(ValueError, 'copias'):
            MySQLWriter._validar_registro_propuesto(xml, ficha(2).as_marc())

    def test_008_depende_del_material_y_la_longitud(self):
        rec = ficha()
        rec['008'].data = rec['008'].data[:23] + 'X' + rec['008'].data[24:]
        self.assertTrue(any(i.campo == '008' and '23-23' in i.detalle for i in validar_ficha(rec)))
        rec['008'].data = rec['008'].data[:-1]
        self.assertTrue(any('40 caracteres' in i.detalle for i in validar_ficha(rec)))
        rec = ficha()
        rec.leader = str(rec.leader)[:6] + 'm' + str(rec.leader)[7:]
        rec['008'].data = rec['008'].data[:18] + 'a' + rec['008'].data[19:]
        self.assertTrue(any('COMPUTER FILES' in i.detalle for i in validar_ficha(rec)))

    def test_framework_csv_y_repetibilidad_local(self):
        with TemporaryDirectory() as td:
            path = Path(td) / 'biblioteca.csv'
            path.write_text('tagfield,frameworkcode,mandatory,repeatable\n'
                            '942,LIB,1,0\n650,LIB,0,0\n998,LIB,1,1\n"#-#","#-#","#-#","#-#"\n\n'
                            'tagfield,tagsubfield,frameworkcode,mandatory,repeatable\n'
                            '942,c,LIB,1,0\n942,z,LIB,1,0\n998,a,LIB,1,1\n', encoding='utf-8-sig')
            perfil = cargar_framework(path)
            problemas = validar_ficha(ficha(), perfil)
            self.assertTrue(any(i.campo == '942' and i.subcampo == 'z' and i.regla == 'Koha' for i in problemas))
            self.assertTrue(any(i.campo == '998' and i.gravedad == ERROR for i in problemas))
            self.assertFalse(es_repetible('650', perfil))
            self.assertTrue(es_repetible('998', perfil))
            path.write_text('un archivo equivocado', encoding='utf8')
            with self.assertRaises(ValueError):
                cargar_framework(path)

    def test_borrador_ilegible_en_iso_conserva_los_campos_originales(self):
        rec = ficha()
        rec['245'].subfields = [Subfield('a', 'Título con \x1e separador')]
        nuevo, aviso = record_para_edicion({'borrador_marc': rec.as_json()})
        self.assertIn('Borrador', aviso)
        self.assertEqual(nuevo['245']['a'], rec['245']['a'])
        with self.assertRaisesRegex(ValueError, '245'):
            serializar_registro(nuevo)
        nuevo['245'].subfields = [Subfield('a', 'Título cotejado')]
        self.assertEqual(estado_ficha(inspeccionar_copias(*serializar_registro(nuevo))[1]), 'Válida')

    def test_editor_conserva_barras_y_subcampos_repetidos(self):
        campo = Field(tag='500', indicators=[' ', ' '], subfields=[
            Subfield('a', r'Nota A | B con ruta C:\sitio'), Subfield('5', 'MX')])
        self.assertEqual(parsear_subcampos(texto_subcampos(campo)), campo.subfields)

    def test_exportacion_atomica_y_lista_completa_de_exclusiones(self):
        valid = ficha()
        bloqueada = ficha(2)
        bloqueada.remove_fields('245')
        lote = Lote('LOTE-QA', 'qa.mdb', 2, 2, estado='con_incidencias', correctos=2, fichas_correctas=[1, 2])
        writer = Mock()
        writer.obtener_copias.return_value = [copias(valid, 1), copias(bloqueada, 2)]
        with TemporaryDirectory() as td:
            xml = Path(td) / 'entrega.xml'
            xml.write_bytes(b'entrega anterior')
            with self.assertRaisesRegex(ValueError, 'Ficha 2'):
                exportar_lote(xml, lote, writer)
            self.assertEqual(xml.read_bytes(), b'entrega anterior')
            parcial = xml.with_suffix('.zip')
            self.assertEqual(exportar_lote(parcial, lote, writer), (1, 0, 1))
            with ZipFile(parcial) as z:
                recs = parse_xml_to_array(BytesIO(z.read('registros.xml')), strict=True)
                self.assertEqual([r['001'].data for r in recs], ['1'])
                filas = list(csv.DictReader(StringIO(z.read('exclusiones.csv').decode('utf-8-sig'))))
                self.assertEqual([f['ficha_access'] for f in filas], ['2'])
                self.assertIn('245', filas[0]['motivo'])
            bloqueada.add_field(Field(tag='245', indicators=['0', '0'], subfields=[Subfield('a', 'Título cotejado')]))
            bloqueada.remove_fields('020')
            writer.obtener_copias.return_value[1] = copias(bloqueada, 2)
            for destino in (xml, xml.with_suffix('.mrc')):
                self.assertEqual(exportar_lote(destino, lote, writer), (2, 1, 0))
                recs = (parse_xml_to_array(str(destino), strict=True) if destino.suffix == '.xml'
                        else list(MARCReader(destino.read_bytes())))
                self.assertEqual(recs[1]['245']['a'], 'Título cotejado')
            self.assertEqual(len(list(Path(td).iterdir())), 3)

    def test_mapeo_conserva_origen_y_requiere_confirmar_dewey(self):
        datos = dict(Ficha_No=4, Titulo='Obra', Clasificacion='860',
                     DatosFijos='051028s1971^^^^mx^^^^^gr^^^^^000^f^spa^d', EtiquetasMARC='¦440Serie de prueba')
        base = MarcConverter().ficha_a_record(datos, [])
        self.assertTrue(any(i.campo == '082' and i.gravedad == ERROR for i in validar_ficha(base)))
        rec = MarcConverter(edicion_dewey='1').ficha_a_record(datos, [])
        self.assertEqual(rec['082'].indicator1, '1')
        self.assertEqual(rec['490']['a'], rec['830']['a'])
        self.assertIn(datos['DatosFijos'], rec['887']['a'])
        self.assertFalse(any(i.gravedad == ERROR for i in validar_ficha(rec)))

    def test_posible_duplicado_se_puede_exportar(self):
        problemas = inspeccionar_copias(*serializar_registro(ficha()), duplicado=True)[1]
        self.assertEqual(estado_ficha(problemas), 'Con advertencias')
        self.assertEqual(problemas[0].campo, '001')

    def test_directorio_desbordado_identifica_el_campo(self):
        rec = ficha()
        rec.add_field(Field(tag='500', indicators=[' ', ' '], subfields=[Subfield('a', 'á' * 5100)]))
        errores = [i for i in validar_ficha(rec) if i.gravedad == ERROR]
        self.assertTrue(any(i.campo == '500' and 'bytes' in i.detalle for i in errores))
        with self.assertRaises(ValueError):
            serializar_registro(rec)

    def test_revision_navega_a_una_incidencia_de_la_pagina_siguiente(self):
        with TemporaryDirectory() as td:
            root = tk.Tk()
            root.withdraw()
            app = MigracionApp(root, HistorialLotes(Path(td) / 'historial.json'))
            self.addCleanup(app.cerrar)
            panel = app.panel_lotes
            lote = Lote('LOTE-PRUEBA', 'qa.mdb', 51, 51, correctos=51)
            panel.lote_actual = Mock(return_value=lote)
            panel.politica = Mock(return_value={'revision': True, 'proponer_correccion': True})
            modelo = copias(ficha(), 1)
            inicial = [dict(modelo, id_ficha_acceso=i) for i in range(1, 51)]
            mala = ficha(51)
            mala.remove_fields('245')
            panel.revisar = Mock(side_effect=[inicial, [copias(mala, 51)]])
            panel._revisar()
            revision = panel._historial_paginas['revision']
            def widgets(padre):
                for hijo in padre.winfo_children():
                    yield hijo
                    yield from widgets(hijo)
            avanzar = next(w for w in widgets(revision) if isinstance(w, ttk.Button) and w.cget('text') == 'Incidencia →')
            avanzar.invoke()
            inicio = time.monotonic()
            while time.monotonic() - inicio < 1:
                root.update()
                notebook = next(w for w in widgets(revision) if isinstance(w, ttk.Notebook))
                if notebook.tab(notebook.select(), 'text').startswith('Incidencias'):
                    break
            self.assertTrue(notebook.tab(notebook.select(), 'text').startswith('Incidencias'))
            lista = next(w for w in widgets(revision) if isinstance(w, ttk.Treeview) and w.cget('columns') == ('ficha','estado'))
            self.assertEqual(lista.selection(), ('51',))
            self.assertEqual(lista.item('51', 'values'), ('51', 'Con errores'))
            self.assertEqual(panel.revisar.call_args.args, (lote.id, 50, 50))
