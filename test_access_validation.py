import tempfile
import unittest
from pathlib import Path

import pyodbc

from access_reader import AccessReader


class CursorFalso:
    def __init__(self, tablas_invalidas=()):
        self.tablas_invalidas = set(tablas_invalidas)
        self.consultas = []

    def execute(self, consulta):
        self.consultas.append(consulta)
        tabla = next(
            (nombre for nombre in ("FICHAS", "EJEMPLARES") if f"[{nombre}]" in consulta),
            None,
        )
        if tabla in self.tablas_invalidas:
            raise pyodbc.Error(f"estructura invalida en {tabla}")


class ConexionFalsa:
    def __init__(self, cursor):
        self.cursor_falso = cursor

    def cursor(self):
        return self.cursor_falso


class AccessValidationTests(unittest.TestCase):
    def _crear_archivo(self, directorio, nombre, contenido=b"Access"):
        ruta = Path(directorio) / nombre
        ruta.write_bytes(contenido)
        return ruta

    def test_rechaza_extension_no_compatible(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = self._crear_archivo(directorio, "copia.xlsx")
            lector = AccessReader(str(ruta))

            errores = lector.validar_archivo()

        self.assertTrue(any("extension .mdb o .accdb" in error for error in errores))

    def test_rechaza_archivo_vacio(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = self._crear_archivo(directorio, "copia.mdb", b"")
            lector = AccessReader(str(ruta))

            errores = lector.validar_archivo()

        self.assertTrue(any("vacio" in error for error in errores))

    def test_acepta_estructura_requerida(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = self._crear_archivo(directorio, "copia.accdb")
            cursor = CursorFalso()
            lector = AccessReader(str(ruta))
            lector._conn = ConexionFalsa(cursor)

            errores = lector.validar_archivo()

        self.assertEqual(errores, [])
        self.assertEqual(len(cursor.consultas), 2)

    def test_rechaza_tabla_con_estructura_incompleta(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = self._crear_archivo(directorio, "copia.mdb")
            cursor = CursorFalso(tablas_invalidas=("EJEMPLARES",))
            lector = AccessReader(str(ruta))
            lector._conn = ConexionFalsa(cursor)

            errores = lector.validar_archivo()

        self.assertEqual(len(errores), 1)
        self.assertIn("EJEMPLARES", errores[0])


if __name__ == "__main__":
    unittest.main()
