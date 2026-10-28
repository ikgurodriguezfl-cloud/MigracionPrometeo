"""Pruebas del seguimiento del sprint 2; no conectan Access, MySQL ni Koha."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lotes import HistorialLotes, acciones_lote, lotes_de_ejemplo


class LotesTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / 'historial.json'
        self.historial = HistorialLotes(self.ruta)

    def test_historial_nuevo_vacio_no_inventa_lotes(self):
        self.assertEqual(self.historial.listar(), [])
        self.assertFalse(self.ruta.exists())

    def test_recibir_reutiliza_espera_y_persiste_acentos(self):
        primero = self.historial.recibir('Poesía y niñez.mdb', 100)
        segundo = self.historial.recibir('Poesía y niñez.mdb', 120)
        self.assertEqual(primero.id, segundo.id)
        recargado = HistorialLotes(self.ruta).obtener(primero.id)
        self.assertEqual(recargado.total_recibidos, 120)
        self.assertIn('Poesía', recargado.fuente)

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
            self.assertEqual(acciones['iniciar'], lote.estado == 'en_espera')
            self.assertEqual(acciones['exportar'], lote.estado == 'concluido')
            self.assertEqual(acciones['resumen'], lote.estado in ('concluido', 'con_incidencias'))
            for bloqueos in ({'ocupado': True}, {'demostracion': True}):
                acciones = acciones_lote(lote, fuente_validada=True, destino_coincide=True, **bloqueos)
                self.assertFalse(acciones['iniciar']); self.assertFalse(acciones['exportar'])
        self.assertEqual(self.historial.listar(), [])

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
