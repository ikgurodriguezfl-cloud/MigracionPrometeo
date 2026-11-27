"""Permisos sobre propuestas propias y salida de la migración, sin servicios reales."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import MagicMock, Mock

from avisos import AvisoUsuario, mensaje_error
from gui_app import MigracionApp
from lotes import HistorialLotes
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter
from permissions import AccesoDenegado


class AprobacionPropiaTests(unittest.TestCase):
    def escritor(self, autor='ana', original_cambio=False, propuesta_invalida=False):
        conversor = MarcConverter()
        record = conversor.ficha_a_record({
            'Ficha_No': 123, 'Titulo': 'Bibliotecas', 'Autor': 'Pérez, Elena',
            'ISBN': '9780306406157',
            'DatosFijos': '261118s2020    mx ' + ' ' * 11 + '000 0 spa d',
            'EtiquetasMARC': '¦260Tepic :Editorial,2020.¦30052 páginas¦650Bibliotecas',
        }, [])
        propuesta = {
            'id': 7, 'id_ficha_acceso': 123, 'propuesto_por': autor,
            'marca_marcxml_propuesta': conversor.record_a_marcxml(record),
            'marca_iso2709_propuesta': b'invalido' if propuesta_invalida else record.as_marc(),
            'huella_original': MySQLWriter.huella_registro('<record/>', b'original'),
        }
        writer = MySQLWriter({})
        writer._conn = MagicMock()
        cursor = writer.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [propuesta, {
            'marca_marcxml': '<cambio/>' if original_cambio else '<record/>',
            'marca_iso2709': b'original',
        }]
        return writer, cursor

    def test_solo_administracion_aprueba_su_propuesta_y_conserva_auditoria(self):
        for perfil in ('Administracion', 'Aprobacion', 'Revision', 'Ejecucion', None, 'desconocido'):
            with self.subTest(perfil=perfil):
                writer, cursor = self.escritor()
                if perfil == 'Administracion':
                    self.assertEqual(writer.resolver_correccion(
                        7, 'LOTE-1', 'ana', True, perfil_actual=perfil,
                    ), 'APROBADA')
                    writer.conn.commit.assert_called_once()
                    escrituras = [c.args for c in cursor.execute.call_args_list]
                    self.assertTrue(any('UPDATE registros_marc' in sql for sql, _ in escrituras))
                    self.assertTrue(any(args == ('APROBADA', 'ana', 7) for _, args in escrituras))
                    self.assertTrue(any('aprobada por ana' in str(args) for sql, args in escrituras
                                        if 'INSERT INTO log_migracion' in sql))
                else:
                    with self.assertRaises((AccesoDenegado, AvisoUsuario)):
                        writer.resolver_correccion(7, 'LOTE-1', 'ana', True, perfil_actual=perfil)
                    writer.conn.commit.assert_not_called()
                    self.assertFalse(any('UPDATE ' in c.args[0] for c in cursor.execute.call_args_list))

    def test_administrador_no_evade_validacion_ni_cambios_concurrentes(self):
        for opciones in ({'original_cambio': True}, {'propuesta_invalida': True}):
            with self.subTest(opciones=opciones):
                writer, cursor = self.escritor(**opciones)
                with self.assertRaises(ValueError):
                    writer.resolver_correccion(7, 'LOTE-1', 'ana', True, perfil_actual='Administracion')
                writer.conn.rollback.assert_called_once()
                writer.conn.commit.assert_not_called()
                self.assertFalse(any('UPDATE ' in c.args[0] for c in cursor.execute.call_args_list))

    def test_aprobacion_resuelve_propuestas_ajenas(self):
        for aprobar in (True, False):
            writer, _ = self.escritor(autor='otra persona')
            self.assertEqual(writer.resolver_correccion(
                7, 'LOTE-1', 'ana', aprobar, perfil_actual='Aprobacion',
            ), 'APROBADA' if aprobar else 'RECHAZADA')
            writer.conn.commit.assert_called_once()

    def test_rechazo_propio_conserva_la_restriccion_existente(self):
        for perfil in ('Administracion', 'Aprobacion'):
            writer, _ = self.escritor()
            with self.assertRaisesRegex(AvisoUsuario, 'otra persona'):
                writer.resolver_correccion(7, 'LOTE-1', 'ana', False, perfil_actual=perfil)
            writer.conn.rollback.assert_called_once()

    def test_aplicacion_pasa_perfil_y_publica_permisos_por_propuesta(self):
        app = MigracionApp.__new__(MigracionApp)
        app._validar_lote_revision = Mock(return_value=SimpleNamespace(id='LOTE-1'))
        app._usuario_actual = Mock(return_value='ana')
        app.historial_lotes = Mock()
        writer = Mock(config={})
        writer.resolver_correccion.return_value = 'APROBADA'
        app._writer_revision = Mock(return_value=writer)
        for perfil, puede in (('Administracion', True), ('Aprobacion', False)):
            app.perfil_usuario = perfil
            writer.listar_correcciones_pendientes.return_value = [
                {'id': 7, 'propuesto_por': 'ana'}, {'id': 8, 'propuesto_por': 'otra persona'},
            ]
            propia, ajena = app._listar_correcciones_pendientes('LOTE-1')
            self.assertEqual(propia['puede_aprobar'], puede)
            self.assertTrue(ajena['puede_aprobar'])
            self.assertFalse(propia['puede_rechazar'])
            app._resolver_correccion('LOTE-1', 7, True)
            writer.resolver_correccion.assert_called_with(7, 'LOTE-1', 'ana', True, perfil_actual=perfil)

    def test_avisos_conservan_la_orientacion_sin_volcar_errores_tecnicos(self):
        aviso = AvisoUsuario('La ficha cambió. Actualiza la revisión.')
        envuelto = RuntimeError('SQL con datos internos')
        envuelto.__cause__ = aviso
        self.assertEqual(mensaje_error(envuelto, 'Inténtalo de nuevo.'), str(aviso))
        self.assertEqual(mensaje_error(RuntimeError('SELECT password FROM tabla'),
                                      'Revisa la conexión.'), 'Revisa la conexión.')


class ResultadoMigracionTests(unittest.TestCase):
    def setUp(self):
        self.temporal = TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.historial = HistorialLotes(Path(self.temporal.name) / 'lotes.json')
        self.app = MigracionApp(self.root, self.historial)
        self.addCleanup(self.app.cerrar)

    def test_botones_abren_el_lote_terminado_y_el_inicio(self):
        app = self.app
        self.assertEqual(app.acciones_fin_migracion.winfo_manager(), '')
        for estado, etapa, correctos in (('concluido', 'finalizado', 2),
                                        ('con_incidencias', 'revision', 1),
                                        ('detenido', 'conversion', 1)):
            with self.subTest(estado=estado):
                lote = self.historial.recibir('copia.mdb', 2)
                self.historial.actualizar(lote.id, estado=estado, etapa=etapa, correctos=correctos,
                                          fichas_correctas=list(range(1, correctos + 1)),
                                          errores=1 if estado == 'con_incidencias' else 0)
                app._lote_actual_id = lote.id
                app._finalizar_migracion()
                self.assertEqual(app.acciones_fin_migracion.winfo_manager(), 'grid')
                # Cambiar la selección en Inicio no debe cambiar el destino del botón.
                otro = self.historial.recibir('otra.mdb', 2)
                app.panel_lotes.seleccionar_real(otro.id)
                app.btn_verificar_lote.invoke()
                self.assertIs(app.pagina_actual, app.panel_lotes)
                self.assertEqual(app.panel_lotes.seleccionado, lote.id)
                self.assertEqual(app.panel_lotes._historial_pagina_actual, 'detalle')
                app.btn_volver_inicio.invoke()
                self.assertEqual(app.panel_lotes._vista_actual, 'resumen')
        app._lote_actual_id = None
        app._finalizar_migracion()
        self.assertEqual(app.acciones_fin_migracion.winfo_manager(), '')

    def test_propuestas_propias_habilitan_aprobar_solo_para_administracion(self):
        app = self.app
        lote = self.historial.recibir('copia.mdb', 1)
        lote = self.historial.actualizar(lote.id, estado='concluido', etapa='finalizado', correctos=1,
                                         fichas_correctas=[123])
        app.panel_lotes.lote_actual = Mock(return_value=lote)
        app.panel_lotes.politica = Mock(return_value={'revision': True, 'aprobar_correccion': True})
        writer, cursor = AprobacionPropiaTests().escritor()
        propuesta = cursor.fetchone()
        propuesta.update(fecha_creacion='2026-11-27',
                         marca_marcxml_actual=propuesta['marca_marcxml_propuesta'],
                         marca_iso2709_actual=propuesta['marca_iso2709_propuesta'])
        app.panel_lotes.revisar = Mock(return_value=[dict(
            id_ficha_acceso=123, marca_marcxml=propuesta['marca_marcxml_propuesta'],
            marca_iso2709=propuesta['marca_iso2709_propuesta'], ejemplares=[],
        )])
        app._validar_lote_revision = Mock(return_value=lote)
        app._usuario_actual = Mock(return_value='ana')
        app._writer_revision = Mock(return_value=Mock(
            listar_correcciones_pendientes=Mock(return_value=[propuesta]),
        ))
        def descendientes(padre):
            for hijo in padre.winfo_children():
                yield hijo
                yield from descendientes(hijo)
        def boton(padre, texto):
            return next(w for w in descendientes(padre)
                        if isinstance(w, ttk.Button) and w.cget('text') == texto)
        app.panel_lotes._revisar()
        for perfil, habilitado in (('Aprobacion', False), ('Administracion', True)):
            app.perfil_usuario = perfil
            boton(app.panel_lotes._historial_paginas['revision'], 'Revisar propuestas').invoke()
            pagina = app.panel_lotes._historial_paginas['propuestas']
            self.assertEqual('disabled' not in boton(pagina, 'Aprobar y aplicar').state(), habilitado)
            self.assertIn('disabled', boton(pagina, 'Rechazar').state())
            boton(pagina, 'Volver a revisión').invoke()


if __name__ == '__main__':
    unittest.main()
