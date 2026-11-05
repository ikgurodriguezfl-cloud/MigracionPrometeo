"""Pruebas del motor MARC21 y su mapeo autorizado."""
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
import tempfile
import unittest

from pymarc import MARCReader, parse_xml_to_array
from marc_converter import MarcConverter
from access_reader import parsear_etiquetas_marc
import json


class MarcMappingTests(unittest.TestCase):
    def setUp(self):
        self.converter = MarcConverter()

    def test_carga_version_actual_y_conserva_las_correspondencias_marc(self):
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

        self.assertEqual(self.converter.mapping_version, '2.0')
        self.assertEqual(record.leader, '00000cam a2200000 a 4500')
        self.assertEqual(record['001'].data, '21')
        self.assertEqual(record['005'].data, '20210708091011.0')
        self.assertEqual(record['008'].data[:6], '200506')
        self.assertEqual(record['008'].data[7:11], 'uuuu')
        self.assertEqual(record['008'].data[15:18], 'xx ')
        self.assertEqual(record['008'].data[35:38], 'und')
        self.assertEqual(record['020']['a'], '9780000000001')
        self.assertEqual(record['040']['a'], 'MX-Prometeo')
        self.assertIsNone(record.get('041'))
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
        self.assertEqual(item['x'], 'checkedout')
        self.assertEqual(item['h'], 'V3 T1')
        self.assertEqual(item.get_subfields('c', 'z'), [])

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
        self.assertEqual(record['008'].data[7:11], 'uuuu')
        item = record.get_fields('952')[0]
        self.assertEqual(item.get_subfields('x'), [])
        mensajes = '\n'.join(item['mensaje'] for item in incidencias)
        self.assertIn('Faltante', mensajes)
        self.assertIn('No contemplado', mensajes)
        self.assertNotIn('99', item.get_subfields('x'))

    def test_faltantes_con_regla_explicita_y_fecha_operativa_se_reportan(self):
        incidencias = []
        record = self.converter.ficha_a_record(
            {'Ficha_No': 23, 'Fecha': ''}, [], incidencias=incidencias)

        self.assertEqual(record['008'].data[7:11], 'uuuu')
        self.assertTrue(record.get_fields('005'))
        self.assertTrue(any('fecha de ejecución autorizada' in item['mensaje']
                            for item in incidencias))
        self.assertTrue(any('fecha de publicación queda desconocida' in item['mensaje']
                            for item in incidencias))

    def test_recupera_las_etiquetas_compactas_sin_saltar_campos(self):
        texto = '¦020¦035000000001¦041¦082895.63¦245Título /Autora.¦260MEXICO :ERA,1971.¦300203 P.¦922Ì'
        campos = parsear_etiquetas_marc(texto)
        self.assertEqual([c['tag'] for c in campos], ['020','035','041','082','245','260','300','922'])
        self.assertEqual(campos[1]['content'], '000000001')
        self.assertEqual(campos[-1]['content'], '')
        alternado = parsear_etiquetas_marc('¦020¦contenido¦041¦idioma¦082895.63¦1')
        self.assertEqual([c['content'] for c in alternado], ['contenido', 'idioma', '895.63 1'])

    def test_recupera_publicacion_y_titulo_completo_sin_usar_fecha_de_captura(self):
        ficha = dict(Ficha_No=1, Fecha=datetime(2009, 11, 24), Titulo='Título truncado',
                     Autor='Autora', DatosFijos='051028s1971^^^^mx^^^^^gr^^^^^000^f^spa^d',
                     TipoMaterial=0, EtiquetasMARC='¦020¦035000000001¦100Autora¦245Título completo /Autora ; traducción de Ana.¦260MEXICO :ERA,1971.¦300203 P.¦440Colección¦500Nota¦650Materia¦650Otra materia¦700Ana, traductora.¦922Ì')
        record = self.converter.ficha_a_record(ficha, [])
        self.assertEqual(record['008'].data[7:11], '1971')
        self.assertEqual(record['008'].data[35:38], 'spa')
        self.assertEqual(len(record['008'].data), 40)
        self.assertIn('Título completo', record['245']['a'])
        self.assertIn('traducción de Ana', record['245']['c'])
        self.assertEqual(record['260']['b'], 'ERA,')
        self.assertEqual(record['260']['c'], '1971.')
        self.assertEqual(record['300']['a'], '203 P.')
        self.assertEqual([f['a'] for f in record.get_fields('650')], ['Materia', 'Otra materia'])
        self.assertEqual(json.loads(record['887']['a'])['EtiquetasMARC'], ficha['EtiquetasMARC'])
        self.assertEqual(record['035']['a'], '000000001')
        self.assertIsNone(record.get('922'))

    def test_preserva_origen_ambiguo_y_reporta_etiquetas_sin_correspondencia(self):
        original = '¦245Prueba¦260Lugar desconocido¦777Información pendiente'
        incidencias = []
        record = self.converter.ficha_a_record(dict(Ficha_No=9, EtiquetasMARC=original), [], incidencias=incidencias)
        self.assertEqual(json.loads(record['887']['a'])['EtiquetasMARC'], original)
        self.assertEqual(record['260']['a'], 'Lugar desconocido')
        self.assertTrue(any(i['referencia'] == '777' for i in incidencias))

    def test_datos_fijos_cortos_e_idioma_explicito(self):
        ficha = dict(Ficha_No=1, DatosFijos='051028s1975^^^^mx^^^^^r^^^^^^^^^0^',
                     EtiquetasMARC='¦041ENG¦245Prueba', Fecha=datetime(2009, 1, 1))
        record = self.converter.ficha_a_record(ficha, [])
        self.assertEqual(record['008'].data[7:11], '1975')
        self.assertEqual(record['008'].data[35:38], 'eng')
        self.assertEqual(record['041']['a'], 'eng')
        self.assertEqual(record['245'].indicator1, '0')

    def test_ejemplares_conservan_sucursal_fechas_y_numeracion(self):
        record = self.converter.ficha_a_record(dict(Ficha_No=1, Titulo='Prueba'), [
            dict(NumAdqui='A1', Biblioteca=165, FechaIngreso=datetime(2020, 2, 3),
                 Ejemplar=2, Volumen=3, Tomo=1, Accesible=3)], branch_mapping={'165':'CENTRAL'})
        item = record['952']
        self.assertEqual((item['a'], item['b']), ('CENTRAL', 'CENTRAL'))
        self.assertEqual(item['d'], '2020-02-03')
        self.assertEqual(item['t'], '2')
        self.assertEqual(item['h'], 'V3 T1')
        incidencias = []
        sin_mapeo = self.converter.ficha_a_record(dict(Ficha_No=1), [dict(Biblioteca=0)],
                                                branch_mapping={}, incidencias=incidencias)
        self.assertEqual(sin_mapeo['952'].get_subfields('a', 'b'), [])
        self.assertTrue(any(i['referencia'] == '952$a' for i in incidencias))

    def test_idiomas_concatenados_y_saltos_de_linea_se_conservan_en_xml_e_iso(self):
        original = '¦100Autora;\r\nOtra autora¦041SPA.ENG.¦245Título /Autoras.¦922Ì'
        record = self.converter.ficha_a_record(dict(Ficha_No=1, EtiquetasMARC=original), [])
        self.assertEqual(record['041'].get_subfields('a'), ['spa', 'eng'])
        xml = self.converter.record_a_marcxml(record)
        iso = self.converter.record_a_iso2709(record)
        desde_xml = parse_xml_to_array(StringIO(xml))[0]
        desde_iso = next(iter(MARCReader(iso)))
        self.assertEqual(desde_xml.as_dict(), desde_iso.as_dict())
        self.assertEqual(json.loads(desde_xml['887']['a'])['EtiquetasMARC'], original)

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

    def test_marcxml_generado_es_completo_y_coincide_con_iso2709(self):
        record = self.converter.ficha_a_record(
            {'Ficha_No': 21, 'Titulo': 'Título de prueba'}, [],
        )

        marcxml = self.converter.record_a_marcxml(record)
        registro_xml = parse_xml_to_array(StringIO(marcxml), strict=True)
        registro_iso = next(iter(MARCReader(
            BytesIO(self.converter.record_a_iso2709(record)),
            to_unicode=True,
        )))

        self.assertTrue(marcxml.endswith('</collection>'))
        self.assertEqual(len(registro_xml), 1)
        self.assertEqual(registro_xml[0].as_dict(), registro_iso.as_dict())
        self.assertEqual(registro_xml[0]['245']['a'], 'Título de prueba')


if __name__ == '__main__':
    unittest.main()
