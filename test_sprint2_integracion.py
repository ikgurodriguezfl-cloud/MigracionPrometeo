"""Prueba el enlace del proceso real al panel con conexiones sustituidas."""
from pathlib import Path
from queue import Queue
from threading import Event
import tempfile
import unittest
from unittest.mock import Mock, patch
import tkinter as tk

from gui_app import MigracionApp
from lotes import HistorialLotes
import main as entrada


class IntegracionSprint2Tests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.historial = HistorialLotes(Path(self.temporal.name) / 'lotes.json')
        self.lote = self.historial.recibir('copia.mdb', 3)
        self.historial.actualizar(self.lote.id, estado='en_proceso', etapa='conexion',
            destino={'host': 'localhost', 'port': 3306, 'database': 'prueba'})
        self.app = MigracionApp.__new__(MigracionApp)
        self.app.historial_lotes = self.historial
        self.app._eventos_ui = Queue()
        self.app._detencion_solicitada = Event()
        self.app.marc_converter = Mock()
        self.app.marc_converter.record_a_marcxml.return_value = '<record></record>'
        self.app.marc_converter.record_a_iso2709.return_value = b'marc'
        self.app.log = Mock()
        self.lector = Mock()
        self.lector.contar_fichas.return_value = 3
        self.lector.leer_fichas.return_value = [{'Ficha_No': 1}, {'Ficha_No': 2}, {'Ficha_No': 3}]
        self.lector.leer_ejemplares_por_ficha.return_value = {}
        self.escritor = Mock()
        self.escritor.registrar_existe.return_value = False

    def ejecutar(self):
        with patch('gui_app.AccessReader', return_value=self.lector), patch('gui_app.MySQLWriter', return_value=self.escritor):
            self.app._ejecutar_migracion('copia.mdb', {'password': 'CLAVE_PRIVADA'}, 0, True, {}, {}, self.lote.id)
        return self.historial.obtener(self.lote.id)

    def test_correctos_y_omitidos_se_actualizan_desde_la_migracion(self):
        self.escritor.registrar_existe.side_effect = [False, True, False]
        lote = self.ejecutar()
        self.assertEqual(lote.estado, 'concluido')
        self.assertEqual((lote.correctos, lote.omitidos, lote.errores, lote.progreso), (2, 1, 0, 100))
        self.assertEqual(lote.fichas_correctas, [1, 3])
        self.assertGreater(self.app._eventos_ui.qsize(), 0)
        self.lector.close.assert_called_once(); self.escritor.close.assert_called_once()

    def test_error_por_registro_no_se_anuncia_como_concluido(self):
        self.escritor.insertar_registro_marc.side_effect = [1, ValueError('dato inválido'), 3]
        lote = self.ejecutar()
        self.assertEqual(lote.estado, 'con_incidencias')
        self.assertEqual((lote.correctos, lote.errores, lote.progreso), (2, 1, 100))
        self.assertEqual(lote.incidencias[0]['referencia'], 'Ficha 2')

    def test_sucursal_sin_correspondencia_no_se_copia_como_destino(self):
        self.lector.leer_ejemplares_por_ficha.return_value = {
            1: [{'Biblioteca': 165}],
        }

        lote = self.ejecutar()

        self.assertEqual(lote.estado, 'con_incidencias')
        self.assertTrue(any('No contemplado' in item['mensaje']
                            for item in lote.incidencias))
        llamada = self.escritor.insertar_ejemplar.call_args
        self.assertIsNone(llamada.args[3])

    def test_fallo_de_conexion_conserva_pendientes_y_oculta_password(self):
        self.escritor.connect.side_effect = RuntimeError('Conexión fallida CLAVE_PRIVADA')
        lote = self.ejecutar()
        self.assertEqual(lote.estado, 'con_incidencias')
        self.assertEqual(lote.pendientes, 3)
        self.assertEqual(lote.progreso, 0)
        self.assertNotIn('CLAVE_PRIVADA', self.historial.ruta.read_text())

    def test_respaldo_cambiado_no_inicia_conversion(self):
        self.lector.contar_fichas.return_value = 4
        lote = self.ejecutar()
        self.assertEqual(lote.estado, 'con_incidencias')
        self.app.marc_converter.ficha_a_record.assert_not_called()

    def test_error_de_identificador_se_registra_y_sigue_con_las_demas_fichas(self):
        self.lector.leer_fichas.return_value = [{'Ficha_No': 'inválido'}, {'Ficha_No': 2}, {'Ficha_No': 3}]
        lote = self.ejecutar()
        self.assertEqual((lote.correctos, lote.errores), (2, 1))
        self.assertEqual(lote.incidencias[0]['referencia'], 'Fila 1')

    def test_todos_omitidos_termina_con_avance_completo(self):
        self.escritor.registrar_existe.return_value = True
        lote = self.ejecutar()
        self.assertEqual((lote.correctos, lote.omitidos, lote.progreso), (0, 3, 100))
        self.assertEqual(lote.estado, 'concluido')
        self.escritor.insertar_registro_marc.assert_not_called()

    def test_detencion_antes_de_iniciar_no_abre_conexiones(self):
        self.app._detencion_solicitada.set()
        lote = self.ejecutar()
        self.assertEqual((lote.estado, lote.procesados, lote.pendientes), ('detenido', 0, 3))
        self.escritor.connect.assert_not_called()
        self.app.marc_converter.ficha_a_record.assert_not_called()

    def test_detencion_termina_la_ficha_actual_con_todos_sus_ejemplares(self):
        self.lector.leer_ejemplares_por_ficha.return_value = {1: [{'Biblioteca': 165}, {'Biblioteca': 166}]}
        self.escritor.insertar_ejemplar.side_effect = lambda *args, **kwargs: self.app._detencion_solicitada.set()
        lote = self.ejecutar()
        self.assertEqual((lote.estado, lote.correctos, lote.ejemplares, lote.pendientes), ('detenido', 1, 2, 2))
        self.assertEqual(lote.fichas_correctas, [1])
        self.assertEqual(self.escritor.insertar_ejemplar.call_count, 2)
        self.escritor.insertar_registro_marc.assert_called_once()
        self.lector.close.assert_called_once(); self.escritor.close.assert_called_once()

    def test_detencion_durante_conexion_no_lee_ni_convierte_fichas(self):
        self.escritor.connect.side_effect = self.app._detencion_solicitada.set
        lote = self.ejecutar()
        self.assertEqual((lote.estado, lote.etapa, lote.procesados), ('detenido', 'conexion', 0))
        self.escritor.crear_tablas.assert_not_called()
        self.lector.leer_fichas.assert_not_called()
        self.escritor.close.assert_called_once()

    def test_detencion_durante_lectura_no_inicia_conversion(self):
        def leer(**kwargs):
            self.app._detencion_solicitada.set()
            return [{'Ficha_No': 1}, {'Ficha_No': 2}, {'Ficha_No': 3}]
        self.lector.leer_fichas.side_effect = leer
        lote = self.ejecutar()
        self.assertEqual((lote.estado, lote.etapa, lote.procesados), ('detenido', 'lectura', 0))
        self.app.marc_converter.ficha_a_record.assert_not_called()

    def test_detencion_despues_de_omitir_registro_conserva_su_conteo(self):
        def existe(identificador):
            self.app._detencion_solicitada.set()
            return True
        self.escritor.registrar_existe.side_effect = existe
        lote = self.ejecutar()
        self.assertEqual((lote.estado, lote.omitidos, lote.pendientes), ('detenido', 1, 2))
        self.assertEqual(lote.errores, 0)

    def test_peticion_en_la_ultima_ficha_no_inventa_pendientes(self):
        def insertar(identificador, *args):
            if identificador == 3:
                self.app._detencion_solicitada.set()
            return identificador
        self.escritor.insertar_registro_marc.side_effect = insertar
        lote = self.ejecutar()
        self.assertEqual((lote.estado, lote.correctos, lote.pendientes), ('concluido', 3, 0))

    def test_exportacion_consulta_solo_las_fichas_correctas_del_lote(self):
        from xml.etree import ElementTree
        self.historial.actualizar(self.lote.id, estado='concluido', etapa='finalizado',
            correctos=2, omitidos=1, fichas_correctas=[1, 3])
        self.app._politica_lote = Mock(return_value={'exportar': True})
        self.app._destino_actual = Mock(return_value={'host': 'localhost', 'port': 3306, 'database': 'prueba'})
        self.app.entry_user = Mock(); self.app.entry_user.get.return_value = 'prueba'
        self.app.entry_pass = Mock(); self.app.entry_pass.get.return_value = ''
        self.app._actualizar_panel = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = [{'marca_marcxml': '<collection><record></record></collection>'}] * 2
        self.escritor.conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        self.escritor.conn.cursor.return_value.__exit__ = Mock(return_value=False)
        ruta = str(Path(self.temporal.name) / 'lote.xml')
        with patch('gui_app.MySQLWriter', return_value=self.escritor), patch('gui_app.filedialog.asksaveasfilename', return_value=ruta), patch('gui_app.messagebox.showinfo'), patch('gui_app.messagebox.showerror') as error:
            self.app._exportar_marcxml(self.lote.id)
        error.assert_not_called()
        consulta, parametros = cursor.execute.call_args.args
        self.assertIn('WHERE id_ficha_acceso IN (%s,%s)', consulta)
        self.assertEqual(parametros, (1, 3))
        self.assertEqual(len(ElementTree.parse(ruta).getroot()), 2)


class InterfazSprint2Tests(unittest.TestCase):
    def test_panel_integrado_y_botones_de_ejemplo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = tk.Tk()
            raiz.withdraw()
            app = None
            try:
                app = MigracionApp(raiz, HistorialLotes(Path(carpeta) / 'lotes.json'))
                self.assertEqual(app.notebook.select(), str(app.panel_lotes))
                panel = app.panel_lotes
                panel.demo.set(True); panel._cambiar_modo()
                self.assertEqual(len(panel.tabla.get_children()), 4)
                for lote in panel.lotes:
                    panel.seleccionado = lote.id; panel._pintar_detalle()
                    self.assertIn('disabled', panel.btn_iniciar.state())
                    self.assertIn('disabled', panel.btn_exportar.state())
                    self.assertIn('disabled', panel.btn_detener.state())
                    self.assertEqual('disabled' not in panel.btn_resumen.state(), lote.estado in ('concluido', 'con_incidencias'))
                panel.filtro.set('En espera'); panel._pintar_tabla()
                self.assertEqual(len(panel.tabla.get_children()), 1)
                self.assertEqual(app.historial_lotes.listar(), [])
            finally:
                if app:
                    app.cerrar()
                else:
                    raiz.destroy()

    def test_botones_detienen_el_lote_activo_y_se_reinician_para_otro_lote(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = tk.Tk(); raiz.withdraw()
            app = None
            try:
                app = MigracionApp(raiz, HistorialLotes(Path(carpeta) / 'lotes.json'))
                fuente = Path(carpeta) / 'copia.mdb'; fuente.write_bytes(b'copia de prueba')
                app.var_access_path.set(str(fuente))
                app._validar_archivo_access = Mock(return_value=[])
                lector = Mock(); lector.contar_fichas.return_value = 3
                app._detencion_solicitada.set()
                with patch('gui_app.AccessReader', return_value=lector), patch('gui_app.threading.Thread'):
                    app._iniciar_migracion()
                self.assertFalse(app._detencion_solicitada.is_set())
                self.assertNotIn('disabled', app.btn_detener.state())
                self.assertNotIn('disabled', app.panel_lotes.btn_detener.state())
                app.panel_lotes.btn_detener.invoke()
                self.assertTrue(app._detencion_solicitada.is_set())
                self.assertIn('disabled', app.btn_detener.state())
                self.assertIn('disabled', app.panel_lotes.btn_detener.state())
                self.assertEqual(app.btn_detener.cget('text'), 'Deteniendo…')
                self.assertIn('Detención solicitada', app.panel_lotes.siguiente.cget('text'))
                app.historial_lotes.actualizar(app._lote_actual_id, estado='detenido', evento='Detenido en prueba.')
                app._finalizar_migracion()
                self.assertIn('disabled', app.btn_detener.state())
                self.assertIn('disabled', app.panel_lotes.btn_exportar.state())
                self.assertNotIn('disabled', app.panel_lotes.btn_resumen.state())
                with patch('gui_app.AccessReader', return_value=lector), patch('gui_app.threading.Thread'):
                    app._iniciar_migracion()
                self.assertFalse(app._detencion_solicitada.is_set())
                self.assertNotIn('disabled', app.btn_detener.state())
                app.btn_detener.invoke()
                self.assertTrue(app._detencion_solicitada.is_set())
            finally:
                if app:
                    app.migracion_en_curso = False
                    app.cerrar()
                else:
                    raiz.destroy()

    def test_main_abre_el_sistema_y_retira_el_atajo_del_login(self):
        with tempfile.TemporaryDirectory() as carpeta:
            aplicaciones = []
            def login_simulado(raiz, on_login_success):
                raiz.withdraw()
                raiz.bind('<Return>', lambda evento: None)
                on_login_success()
            def crear_app(raiz):
                app = MigracionApp(raiz, HistorialLotes(Path(carpeta) / 'lotes.json'))
                aplicaciones.append(app)
                self.assertEqual(raiz.bind('<Return>'), '')
                self.assertTrue(all(raiz.resizable()))
                raiz.after(50, app.cerrar)
                return app
            with patch.object(entrada, 'LoginScreen', side_effect=login_simulado), patch.object(entrada, 'MigracionApp', side_effect=crear_app):
                entrada.main()
            self.assertEqual(len(aplicaciones), 1)


if __name__ == '__main__':
    unittest.main()
