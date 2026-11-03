"""Pruebas del motor MARC21 y su mapeo autorizado."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from io import BytesIO
from unittest.mock import MagicMock
from pymarc import MARCReader, parse_xml_to_array

from marc_converter import MarcConverter
from exportacion_marc import exportar_lote


class MarcMappingTests(unittest.TestCase):
    def setUp(self):
        self.converter = MarcConverter()

    def test_carga_version_vigente_y_conserva_las_correspondencias_marc(self):
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

        self.assertEqual(self.converter.mapping_version, '1.1')
        self.assertEqual(record.leader, '00000cam a2200000 a 4500')
        self.assertEqual(record['001'].data, '21')
        self.assertEqual(record['005'].data, '20210708091011.0')
        self.assertEqual(record['008'].data[7:11], '2020')
        self.assertEqual(record['008'].data[15:18], 'mx ')
        self.assertEqual(record['008'].data[35:38], 'spa')
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
        self.assertEqual(record['008'].data[6:15], 'nuuuuuuuu')
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

        self.assertEqual(record['008'].data[6:15], 'nuuuuuuuu')
        self.assertTrue(record.get_fields('005'))
        self.assertTrue(any('fecha de ejecución autorizada' in item['mensaje']
                            for item in incidencias))
        self.assertTrue(any("valor autorizado 'uuuu'" in item['mensaje']
                            for item in incidencias))

    def test_huella_identifica_las_reglas_y_mapeos_de_la_ejecucion(self):
        original = self.converter.mapping_fingerprint({}, {'2': 'checkedout'})
        otra_sucursal = self.converter.mapping_fingerprint(
            {'165': 'CENTRAL'}, {'2': 'checkedout'})
        otro_estado = self.converter.mapping_fingerprint({}, {'2': 'available'})

        self.assertEqual(len(original), 64)
        self.assertNotEqual(original, otra_sucursal)
        self.assertNotEqual(original, otro_estado)

    def test_xml_e_iso_conservan_campos_tildes_y_ejemplares(self):
        ficha = {'Ficha_No': 7, 'Fecha': datetime(2022, 1, 5), 'Titulo': 'Poesía & niñez <México>'}
        items = [{'NumAdqui': 'A-1', 'Accesible': 1}, {'NumAdqui': 'A-2', 'Accesible': 1}]
        registro = self.converter.ficha_a_record(ficha, items)
        xml = self.converter.record_a_marcxml(registro)
        iso = self.converter.record_a_iso2709(registro)
        desde_xml, = parse_xml_to_array(BytesIO(xml.encode('utf-8')), strict=True)
        desde_iso, = MARCReader(iso)
        self.assertEqual(desde_xml.as_dict()['fields'], desde_iso.as_dict()['fields'])
        self.assertEqual(desde_xml['245']['a'], ficha['Titulo'])
        self.assertEqual(desde_xml['245'].indicator1, '0')
        self.assertEqual([f['p'] for f in desde_iso.get_fields('952')], ['A-1', 'A-2'])
        self.assertEqual(desde_iso['008'].data[:6], datetime.now().strftime('%y%m%d'))

    def test_exportar_lote_anterior_y_preservar_archivo_si_el_destino_es_inconsistente(self):
        registro = self.converter.ficha_a_record({'Ficha_No': 7, 'Titulo':'Ñ'}, [])
        anterior = self.converter.record_a_marcxml(registro).removesuffix('</collection>')
        conexion = MagicMock()
        cursor = conexion.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{'id_ficha_acceso': 7, 'marca_marcxml': anterior}]
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / 'lote.xml'
            exportar_lote(conexion, [7], ruta)
            origen = ruta.read_bytes()
            self.assertEqual(parse_xml_to_array(str(ruta))[0]['001'].data, '7')
            cursor.fetchall.return_value = [{'id_ficha_acceso': 8, 'marca_marcxml': anterior}]
            with self.assertRaisesRegex(ValueError, '001'):
                exportar_lote(conexion, [8], ruta)
            self.assertEqual(ruta.read_bytes(), origen)
            self.assertEqual(list(Path(directorio).iterdir()), [ruta])

    def test_mapeo_invalido_no_se_sustituye_silenciosamente(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'mapeo_marc21.json'
            ruta.write_text('{no-json', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'No se pudo cargar el mapeo'):
                MarcConverter(mapping_path=str(ruta))


if __name__ == '__main__':
    unittest.main()
