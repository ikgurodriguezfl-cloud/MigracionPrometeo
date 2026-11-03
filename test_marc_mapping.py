"""Pruebas del motor MARC21 y su mapeo autorizado."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from marc_converter import MarcConverter


class MarcMappingTests(unittest.TestCase):
    def setUp(self):
        self.converter = MarcConverter()

    def test_carga_versión_1_y_conserva_las_correspondencias_marc(self):
        ficha = {
            'Ficha_No': 21,
            'Fecha': datetime(2020, 5, 6),
            'FechaMod': datetime(2021, 7, 8, 9, 10, 11),
            'ISBN': ' 9780000000001 ',
            'Titulo': 'Título de prueba',
            'Autor': 'Autora de prueba',
            'Clasificacion': '123.4',
        }
        ejemplares = [{
            'NumAdqui': 'BAR-21',
            'Accesible': 2,
            'Volumen': 3,
            'Tomo': 1,
        }]

        record = self.converter.ficha_a_record(ficha, ejemplares)

        self.assertEqual(self.converter.mapping_version, '1.0')
        self.assertEqual(record.leader, '00000cam a2200000 a 4500')
        self.assertEqual(record['001'].data, '21')
        self.assertEqual(record['005'].data, '20210708091011.0')
        self.assertEqual(record['008'].data[7:11], '2020')
        self.assertEqual(record['008'].data[18:20], 'mx')
        self.assertEqual(record['008'].data[21:24], 'spa')
        self.assertEqual(record['020']['a'], '9780000000001')
        self.assertEqual(record['040']['a'], 'MX-Prometeo')
        self.assertEqual(record['041']['a'], 'spa')
        self.assertEqual(record['082']['a'], '123.4')
        self.assertEqual(record['100']['a'], 'Autora de prueba')
        self.assertEqual(record['245']['a'], 'Título de prueba')
        self.assertEqual(record['245']['c'], 'Autora de prueba')
        self.assertEqual(record['942']['c'], 'LIBR0')
        item = record.get_fields('952')[0]
        self.assertEqual(item['a'], 'ITT')
        self.assertEqual(item['b'], 'ITT')
        self.assertEqual(item['y'], 'LIBR0')
        self.assertEqual(item['p'], 'BAR-21')
        self.assertEqual(item['o'], '123.4')
        self.assertEqual(item['z'], 'checkedout')
        self.assertEqual(item['c'], 'V3 T1')

    def test_faltante_ambiguo_y_no_contemplado_se_informan_sin_inferir(self):
        ficha = {
            'Ficha_No': 22,
            'Titulo': '',
            'Fecha': [datetime(2020, 1, 1), datetime(2021, 1, 1)],
        }
        ejemplares = [{'Accesible': 99}]
        incidencias = []

        record = self.converter.ficha_a_record(
            ficha, ejemplares, incidencias=incidencias)

        self.assertEqual(record.get_fields('245'), [])
        self.assertEqual(record['008'].data[7:11], '    ')
        item = record.get_fields('952')[0]
        self.assertEqual(item.get_subfields('z'), [])
        mensajes = '\n'.join(item['mensaje'] for item in incidencias)
        self.assertIn('Faltante', mensajes)
        self.assertIn('Ambiguo', mensajes)
        self.assertIn('No contemplado', mensajes)
        self.assertNotIn('99', item.get_subfields('z'))

    def test_faltantes_con_regla_explicita_y_fecha_operativa_se_reportan(self):
        incidencias = []
        record = self.converter.ficha_a_record(
            {'Ficha_No': 23, 'Fecha': ''}, [], incidencias=incidencias)

        self.assertEqual(record['008'].data[7:11], '0000')
        self.assertTrue(record.get_fields('005'))
        self.assertTrue(any('fecha de ejecución autorizada' in item['mensaje']
                            for item in incidencias))
        self.assertTrue(any("valor autorizado '0000'" in item['mensaje']
                            for item in incidencias))

    def test_huella_identifica_las_reglas_y_mapeos_de_la_ejecucion(self):
        original = self.converter.mapping_fingerprint({}, {'2': 'checkedout'})
        otra_sucursal = self.converter.mapping_fingerprint(
            {'165': 'CENTRAL'}, {'2': 'checkedout'})
        otro_estado = self.converter.mapping_fingerprint({}, {'2': 'available'})

        self.assertEqual(len(original), 64)
        self.assertNotEqual(original, otra_sucursal)
        self.assertNotEqual(original, otro_estado)

    def test_mapeo_invalido_no_se_sustituye_silenciosamente(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'mapeo_marc21.json'
            ruta.write_text('{no-json', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'No se pudo cargar el mapeo'):
                MarcConverter(mapping_path=str(ruta))


if __name__ == '__main__':
    unittest.main()
