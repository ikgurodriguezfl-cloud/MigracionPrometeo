"""Prueba opcional de lectura del respaldo real y sus ejemplares."""
import os
import unittest

from access_reader import AccessReader
from marc_converter import MarcConverter
from validacion_marc import inspeccionar_copias


class ConversionAccessTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('PROMETEO_ACCESS_PRUEBA'), 'Requiere una copia local de Access')
    def test_fichas_y_ejemplares_del_respaldo(self):
        reader = AccessReader(os.environ['PROMETEO_ACCESS_PRUEBA'])
        self.addCleanup(reader.close)
        fichas = reader.leer_fichas(limite=5)
        self.assertTrue(fichas)
        converter = MarcConverter()
        for ficha in fichas:
            numero = ficha['Ficha_No']
            ejemplares = reader.leer_ejemplares_por_ficha([numero]).get(numero, [])
            record = converter.ficha_a_record(ficha, ejemplares)
            copia, incidencias = inspeccionar_copias(converter.record_a_marcxml(record), record.as_marc())
            self.assertFalse(any(i.campo in ('ISO2709', 'MARCXML', 'MARCXML/ISO2709') for i in incidencias))
            self.assertEqual(copia['001'].data, str(numero))
            self.assertEqual(len(copia.get_fields('952')), len(ejemplares))


if __name__ == '__main__':
    unittest.main()
