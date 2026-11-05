"""Prueba el enlace del proceso real al panel con conexiones sustituidas."""
from pathlib import Path
from queue import Queue
from threading import Event
import tempfile
import unittest
from unittest.mock import Mock, patch
import tkinter as tk

from auth import AuthenticationService
from gui_app import MigracionApp
from lotes import HistorialLotes
from marc_converter import MarcConverter
from io import StringIO
from pymarc import parse_xml_to_array
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

    def test_reprocesamiento_no_reemplaza_registros_y_completa_ejemplares_faltantes(self):
        origen = self.historial.actualizar(
            self.lote.id, estado='concluido', etapa='finalizado',
            total_objetivo=3, correctos=3, fichas_correctas=[1, 2, 3],
        )
        intento = self.historial.recibir_reprocesamiento(origen.id, 3)
        self.historial.actualizar(
            intento.id, estado='en_proceso', etapa='conexion',
            destino=origen.destino,
        )
        self.escritor.registrar_existe.return_value = True
        self.escritor.insertar_ejemplares_faltantes.return_value = (1, [])

        with patch(
                'gui_app.AccessReader', return_value=self.lector), patch(
                'gui_app.MySQLWriter', return_value=self.escritor):
            self.app._ejecutar_migracion(
                'copia.mdb', {'password': 'CLAVE_PRIVADA'}, 0, True,
                {}, {}, intento.id,
            )

        reprocesado = self.historial.obtener(intento.id)
        self.assertEqual(reprocesado.lote_origen, origen.id)
        self.assertEqual(
            (reprocesado.correctos, reprocesado.omitidos, reprocesado.errores),
            (0, 3, 0),
        )
        self.assertEqual(reprocesado.ejemplares, 3)
        self.assertEqual(
            self.escritor.insertar_ejemplares_faltantes.call_count, 3,
        )
        self.escritor.insertar_registro_marc.assert_not_called()

    def test_error_por_registro_no_se_anuncia_como_concluido(self):
        self.escritor.insertar_registro_marc.side_effect = [1, ValueError('dato inválido'), 3]
        lote = self.ejecutar()
        self.assertEqual(lote.estado, 'con_incidencias')
        self.assertEqual((lote.correctos, lote.errores, lote.progreso), (2, 1, 100))
        self.assertEqual(lote.incidencias[0]['referencia'], 'Ficha 2')

    def test_el_motor_guarda_los_campos_recuperados_de_access(self):
        self.app.marc_converter = MarcConverter()
        self.lector.leer_fichas.return_value = [
            dict(Ficha_No=i, Titulo='Título corto', DatosFijos='051028s1971^^^^mx^^^^^gr^^^^^000^f^spa^d',
                 EtiquetasMARC='¦245Título completo /Responsable.¦260MEXICO :ERA,1971.¦300203 P.¦650Materia¦922Ì')
            for i in (1, 2, 3)]
        lote = self.ejecutar()
        self.assertEqual(lote.correctos, 3)
        for llamada in self.escritor.insertar_registro_marc.call_args_list:
            registro = parse_xml_to_array(StringIO(llamada.args[2]))[0]
            self.assertEqual(registro['260']['b'], 'ERA,')
            self.assertEqual(registro['300']['a'], '203 P.')
            self.assertEqual(registro['650']['a'], 'Materia')
            self.assertEqual(registro['008'].data[7:11], '1971')

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
        self.app.perfil_usuario = 'Aprobacion'
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

    def test_revision_consulta_solo_fichas_correctas_y_exige_permiso(self):
        lote = self.historial.actualizar(
            self.lote.id, estado='concluido', etapa='finalizado',
            total_objetivo=3, correctos=2, omitidos=1,
            fichas_correctas=[1, 3],
        )
        self.app.perfil_usuario = 'Revision'
        self.app.migracion_en_curso = False
        self.app._lote_actual_id = lote.id
        self.app.entry_host = Mock()
        self.app.entry_user = Mock()
        self.app.entry_user.get.return_value = 'revisor'
        self.app.entry_pass = Mock()
        self.app.entry_pass.get.return_value = 'CLAVE_PRIVADA'
        self.app._destino_actual = Mock(return_value=lote.destino)
        registros = [{'id_ficha_acceso': 3, 'marca_marcxml': '<record />'}]
        self.escritor.obtener_registros_revision.return_value = registros

        with patch('gui_app.MySQLWriter', return_value=self.escritor) as crear_writer:
            resultado = self.app._obtener_registros_revision(lote.id, 1, 1)

        self.assertEqual(resultado, registros)
        self.escritor.obtener_registros_revision.assert_called_once_with([3])
        crear_writer.assert_called_once()
        self.assertEqual(
            crear_writer.call_args.args[0]['password'], 'CLAVE_PRIVADA',
        )
        self.escritor.close.assert_called_once()

        self.app.perfil_usuario = 'Ejecucion'
        with patch('gui_app.MySQLWriter') as crear_writer:
            with self.assertRaises(PermissionError):
                self.app._obtener_registros_revision(lote.id, 0, 1)
        crear_writer.assert_not_called()

    def test_revision_no_expone_contrasena_si_falla_mysql(self):
        lote = self.historial.actualizar(
            self.lote.id, estado='concluido', etapa='finalizado',
            total_objetivo=3, correctos=2, omitidos=1,
            fichas_correctas=[1, 3],
        )
        self.app.perfil_usuario = 'Revision'
        self.app.migracion_en_curso = False
        self.app._lote_actual_id = lote.id
        self.app.entry_host = Mock()
        self.app.entry_user = Mock()
        self.app.entry_user.get.return_value = 'revisor'
        self.app.entry_pass = Mock()
        self.app.entry_pass.get.return_value = 'CLAVE_PRIVADA'
        self.app._destino_actual = Mock(return_value=lote.destino)
        self.escritor.obtener_registros_revision.side_effect = RuntimeError(
            'Error CLAVE_PRIVADA',
        )

        with patch('gui_app.MySQLWriter', return_value=self.escritor):
            with self.assertRaisesRegex(RuntimeError, r'Error \*{3}') as error:
                self.app._obtener_registros_revision(lote.id, 0, 1)

        self.assertNotIn('CLAVE_PRIVADA', str(error.exception))
        self.escritor.close.assert_called_once()

    def test_accion_de_revision_respeta_perfiles_autorizados(self):
        lote = self.historial.actualizar(
            self.lote.id, estado='concluido', etapa='finalizado',
            total_objetivo=3, correctos=2, omitidos=1,
            fichas_correctas=[1, 3],
        )
        self.app.migracion_en_curso = False
        self.app._lote_actual_id = lote.id
        self.app.entry_host = Mock()
        self.app._destino_actual = Mock(return_value=lote.destino)

        self.app.perfil_usuario = 'Ejecucion'
        self.assertFalse(self.app._politica_lote(lote)['revision'])
        self.assertTrue(self.app._politica_lote(lote)['exportar_historial'])
        self.assertTrue(self.app._politica_lote(lote)['reprocesar'])
        self.app.perfil_usuario = 'Revision'
        self.assertTrue(self.app._politica_lote(lote)['revision'])
        self.assertFalse(self.app._politica_lote(lote)['reprocesar'])
        self.assertTrue(self.app._politica_lote(lote)['exportar_historial'])
        self.app.perfil_usuario = 'Aprobacion'
        self.assertTrue(self.app._politica_lote(lote)['revision'])
        self.assertTrue(self.app._politica_lote(lote)['reprocesar'])
        self.assertTrue(self.app._politica_lote(lote)['exportar_historial'])
        self.app.perfil_usuario = 'Administracion'
        self.assertTrue(self.app._politica_lote(lote)['revision'])
        self.assertTrue(self.app._politica_lote(lote)['reprocesar'])
        self.assertTrue(self.app._politica_lote(lote)['exportar_historial'])

    def test_revision_puede_registrar_observacion_asociada_a_ficha(self):
        lote = self.historial.actualizar(
            self.lote.id, estado='concluido', etapa='finalizado',
            total_objetivo=3, correctos=3, fichas_correctas=[1, 2, 3],
        )
        self.app.perfil_usuario = 'Revision'
        self.app.auth_service = None
        self.app.entry_host = Mock()
        self.app.entry_port = Mock()
        self.app.entry_db = Mock()
        self.app.entry_user = Mock()
        self.app.entry_user.get.return_value = 'revisora'
        self.app.entry_pass = Mock()
        self.app.entry_pass.get.return_value = ''
        self.app._destino_actual = Mock(return_value=lote.destino)
        self.app._usuario_actual = Mock(return_value='revisora')

        writer = Mock()
        writer.registrar_observacion_revision.return_value = 23
        with patch('gui_app.MySQLWriter', return_value=writer):
            observacion_id = self.app._registrar_observacion_revision(
                lote.id, 2, 'Revisar el 245$a.',
            )

        self.assertEqual(observacion_id, 23)
        writer.registrar_observacion_revision.assert_called_once_with(
            lote.id, 2, 'revisora', 'Revisar el 245$a.',
        )
        self.assertIn(
            'Observación #23',
            self.historial.obtener(lote.id).actividad[-1]['mensaje'],
        )

        self.app.perfil_usuario = 'Ejecucion'
        with patch('gui_app.MySQLWriter') as crear_writer:
            with self.assertRaises(PermissionError):
                self.app._registrar_observacion_revision(
                    lote.id, 2, 'No autorizado.',
                )
        crear_writer.assert_not_called()

    def test_perfiles_sin_permiso_no_llegan_al_motor_ni_al_exportador(self):
        for perfil, operacion in (
            ('Revision', self.app._probar_access),
            ('Revision', self.app._iniciar_migracion),
            ('Ejecucion', self.app._exportar_marcxml),
        ):
            with self.subTest(perfil=perfil, operacion=operacion.__name__), \
                    patch('gui_app.messagebox.showerror') as aviso, \
                    patch('gui_app.AccessReader') as origen, \
                    patch('gui_app.MySQLWriter') as destino:
                self.app.perfil_usuario = perfil
                operacion()
                self.assertEqual(aviso.call_args.args[0], 'Acceso Restringido')
                origen.assert_not_called()
                destino.assert_not_called()


class InterfazSprint2Tests(unittest.TestCase):
    def test_panel_integrado_y_botones_de_ejemplo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = tk.Tk()
            raiz.withdraw()
            app = None
            try:
                app = MigracionApp(raiz, HistorialLotes(Path(carpeta) / 'lotes.json'))
                self.assertFalse(hasattr(app, 'notebook'))
                self.assertIs(app.pagina_actual, app.panel_lotes)
                self.assertEqual(app.panel_lotes.winfo_manager(), 'grid')
                panel = app.panel_lotes
                self.assertEqual(
                    [panel.vistas.tab(tab, 'text') for tab in panel.vistas.tabs()],
                    ['Resumen', 'Historial', 'Análisis'],
                )
                panel.demo.set(True); panel._cambiar_modo()
                self.assertEqual(len(panel.tabla.get_children()), 4)
                for tipo in (
                    'Estado de los lotes', 'Resultado de fichas',
                    'Fichas correctas por lote', 'Ejemplares por lote',
                ):
                    panel.tipo_grafico.set(tipo)
                    panel._pintar_grafico()
                    self.assertGreater(len(panel.grafico.find_all()), 0)
                for lote in panel.lotes:
                    panel.seleccionado = lote.id; panel._pintar_detalle()
                    self.assertIn('disabled', panel.btn_iniciar.state())
                    self.assertIn('disabled', panel.btn_exportar.state())
                    self.assertIn('disabled', panel.btn_revisar.state())
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

    def test_navegacion_lateral_secuencial_habilita_pasos_al_validar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = tk.Tk()
            raiz.withdraw()
            app = None
            try:
                app = MigracionApp(raiz, HistorialLotes(Path(carpeta) / 'lotes.json'))
                self.assertFalse(hasattr(app, 'notebook'))
                self.assertEqual(app.pagina_actual, app.panel_lotes)
                for pagina in app.paginas:
                    self.assertEqual(pagina.winfo_manager(), 'grid')
                self.assertEqual(app._nav_items[app.frame_conexion].cget('state'), 'normal')
                self.assertEqual(app._nav_items[app.frame_config].cget('state'), 'disabled')
                self.assertEqual(app._nav_items[app.frame_migracion].cget('state'), 'disabled')
                self.assertEqual(app._nav_items[app.panel_lotes].cget('state'), 'normal')
                self.assertEqual(app._nav_items[app.frame_migracion].cget('state'), 'disabled')

                origen = Path(carpeta) / 'origen.accdb'
                origen.write_bytes(b'prueba')
                app.var_access_path.set(str(origen))
                app._validacion_access = app._firma_access(str(origen))
                app._mysql_validado = True
                app._actualizar_navegacion_secuencial()
                self.assertEqual(app._nav_items[app.frame_config].cget('state'), 'normal')

                app._navegar(app.frame_config)
                app._continuar_a_migracion()
                self.assertIs(app.pagina_actual, app.frame_migracion)
                self.assertEqual(app._nav_items[app.frame_migracion].cget('state'), 'normal')

                app._configuracion_modificada()
                self.assertEqual(app._nav_items[app.frame_migracion].cget('state'), 'disabled')
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
                lote = app.historial_lotes.obtener(app._lote_actual_id)
                self.assertEqual(lote.version_mapeo, app.marc_converter.mapping_version)
                self.assertRegex(lote.huella_mapeo, r'^[0-9a-f]{64}$')
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
            servicio = AuthenticationService(Path(carpeta) / 'auth.db')
            servicio.create_user('operador', 'clave-prueba', 'Ejecucion')
            def login_simulado(raiz, auth_service, on_login_success):
                raiz.withdraw()
                raiz.bind('<Return>', lambda evento: None)
                on_login_success(auth_service.authenticate('operador', 'clave-prueba'))
            def crear_app(raiz, **opciones):
                app = MigracionApp(raiz, HistorialLotes(Path(carpeta) / 'lotes.json'), **opciones)
                aplicaciones.append(app)
                self.assertEqual(app.perfil_usuario, 'Ejecucion')
                self.assertTrue(servicio.is_authenticated(app.session_token))
                self.assertEqual(raiz.bind('<Return>'), '')
                self.assertTrue(all(raiz.resizable()))
                raiz.after(50, app.cerrar)
                return app
            with patch.object(entrada, 'AuthenticationService', return_value=servicio), \
                    patch.object(entrada, 'LoginScreen', side_effect=login_simulado), \
                    patch.object(entrada, 'MigracionApp', side_effect=crear_app):
                entrada.main()
            self.assertEqual(len(aplicaciones), 1)


if __name__ == '__main__':
    unittest.main()
