"""
Lectura de base de datos Access (.mdb) de Prometeo.
Extrae registros de FICHAS y EJEMPLARES y los devuelve como diccionarios.
"""
import os
import re
import pyodbc
from typing import List, Dict, Optional, Iterator
from datetime import datetime


class AccessReader:
    # Columnas consultadas posteriormente para convertir fichas y ejemplares.
    CAMPOS_REQUERIDOS = {
        "FICHAS": (
            "Ficha_No", "Fecha", "FechaMod", "DatosFijos", "EtiquetasMARC",
            "TipoMaterial", "ISBN", "Titulo", "Autor", "Clasificacion",
        ),
        "EJEMPLARES": (
            "Ficha_No", "NumAdqui", "FechaIngreso", "Biblioteca",
            "Volumen", "Ejemplar", "Tomo", "Accesible",
        ),
    }

    def __init__(self, mdb_path: str, driver: str = "{Microsoft Access Driver (*.mdb, *.accdb)}"):
        self.mdb_path = mdb_path
        self.driver = driver
        self.conn_str = (
            f"DRIVER={driver};"
            f"DBQ={mdb_path};ReadOnly=1;"
        )
        self._conn = None

    def connect(self):
        self._conn = pyodbc.connect(self.conn_str)
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self.connect()
        return self._conn

    def test_connection(self) -> bool:
        try:
            self.connect()
            self.close()
            return True
        except Exception:
            return False

    def validar_archivo(self) -> List[str]:
        """Valida extension, existencia, contenido y tablas/campos de la copia."""
        errores = []
        extension = os.path.splitext(self.mdb_path)[1].lower()
        if extension not in {".mdb", ".accdb"}:
            errores.append("El archivo debe tener extension .mdb o .accdb.")
        if not os.path.isfile(self.mdb_path):
            errores.append("El archivo seleccionado no existe o no es un archivo.")
        elif os.path.getsize(self.mdb_path) == 0:
            errores.append("El archivo seleccionado esta vacio.")

        if errores:
            return errores

        cursor = self.conn.cursor()
        for tabla, campos in self.CAMPOS_REQUERIDOS.items():
            seleccion = ", ".join(f"[{campo}]" for campo in campos)
            try:
                cursor.execute(f"SELECT {seleccion} FROM [{tabla}] WHERE 1=0")
            except pyodbc.Error as error:
                errores.append(
                    f"La tabla {tabla} no contiene la estructura requerida: {error}"
                )
        return errores

    def leer_fichas(self, limite: Optional[int] = None) -> List[Dict]:
        """
        Lee la tabla FICHAS. Devuelve lista de diccionarios con las columnas:
        Ficha_No, Fecha, FechaMod, DatosFijos, EtiquetasMARC, TipoMaterial,
        ISBN, Titulo, Autor, Clasificacion
        """
        return [ficha for bloque in self.iterar_bloques(limite) for ficha in bloque]

    def iterar_bloques(self, limite=None, tamano=250):
        """Lee un bloque a la vez en un orden estable, incluso al repetir un lote."""
        cursor = self.conn.cursor()
        try:
            tope = f'TOP {int(limite)} ' if limite and limite > 0 else ''
            cursor.execute(
                f'SELECT {tope}Ficha_No, Fecha, FechaMod, DatosFijos, EtiquetasMARC, '
                'TipoMaterial, ISBN, Titulo, Autor, Clasificacion FROM FICHAS ORDER BY Ficha_No'
            )
            columnas = [desc[0] for desc in cursor.description]
            while filas := cursor.fetchmany(tamano):
                yield [dict(zip(columnas, fila)) for fila in filas]
        finally:
            cursor.close()

    def codigos_adquisicion_repetidos(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'SELECT Trim(NumAdqui) FROM EJEMPLARES '
                'WHERE NumAdqui IS NOT NULL GROUP BY Trim(NumAdqui) HAVING COUNT(*) > 1'
            )
            return {str(fila[0]).strip().casefold() for fila in cursor if fila[0]}
        finally:
            cursor.close()

    def leer_ejemplares_por_ficha(self, ficha_nos: List[int]) -> Dict[int, List[Dict]]:
        """
        Lee los ejemplares de EJEMPLARES para una lista de Ficha_No.
        Devuelve un diccionario: {Ficha_No: [ejemplar_dict, ...]}
        """
        if not ficha_nos:
            return {}

        cursor = self.conn.cursor()
        placeholders = ",".join(["?"] * len(ficha_nos))
        sql = f"""
            SELECT Ficha_No, NumAdqui, FechaIngreso, Biblioteca,
                   Volumen, Ejemplar, Tomo, Accesible
            FROM EJEMPLARES
            WHERE Ficha_No IN ({placeholders})
        """
        cursor.execute(sql, ficha_nos)
        columnas = [desc[0] for desc in cursor.description]
        filas = cursor.fetchall()

        resultado: Dict[int, List[Dict]] = {}
        for fila in filas:
            d = dict(zip(columnas, fila))
            resultado.setdefault(d["Ficha_No"], []).append(d)
        return resultado

    def leer_todos_ejemplares(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT Ficha_No, NumAdqui, FechaIngreso, Biblioteca,
                   Volumen, Ejemplar, Tomo, Accesible
            FROM EJEMPLARES
        """)
        columnas = [desc[0] for desc in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]

    def contar_fichas(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM FICHAS")
        return cursor.fetchone()[0]

    def contar_ejemplares(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM EJEMPLARES")
        return cursor.fetchone()[0]

    def obtener_bibliotecas(self) -> List[Dict]:
        """
        Intenta leer la tabla Bibliotecas para mapear códigos.
        Si no existe o falla, devuelve lista vacía.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM Bibliotecas")
            columnas = [desc[0] for desc in cursor.description]
            return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        except Exception:
            return []


def parsear_etiquetas_marc(texto: Optional[str]) -> List[Dict]:
    """
    Parsea el campo EtiquetasMARC de Access.
    Formato compacto de Prometeo: ¦020ISBN¦041SPA¦082Clasificación.
    Devuelve lista de diccionarios: {"tag": "020", "content": "..."}
    """
    if not texto:
        return []

    texto = texto.strip()
    if not texto.startswith("¦"):
        return []

    # Ì es el terminador del bloque, no parte del último campo bibliográfico.
    texto = texto.removesuffix('Ì')
    campos = []
    for parte in re.split(r'¦(?=\d{3})', texto[1:]):
        coincidencia = re.fullmatch(r'(\d{3})(.*)', parte, re.DOTALL)
        if coincidencia:
            tag, contenido = coincidencia.groups()
            campos.append({'tag': tag, 'content': contenido.replace('¦', ' ').strip()})
    return campos


def formatear_fecha_marc(dt: Optional[datetime]) -> str:
    """Convierte datetime de Access a formato MARC 005: YYYYMMDDHHMMSS.0"""
    if dt is None:
        return datetime.now().strftime("%Y%m%d%H%M%S.0")
    return dt.strftime("%Y%m%d%H%M%S.0")
