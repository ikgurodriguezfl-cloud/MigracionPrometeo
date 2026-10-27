"""
Lectura de base de datos Access (.mdb) de Prometeo.
Extrae registros de FICHAS y EJEMPLARES y los devuelve como diccionarios.
"""
import os
import pyodbc
from typing import List, Dict, Optional, Iterator
from datetime import datetime


class AccessReader:
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
            f"DBQ={mdb_path};"
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
        """Comprueba el formato, que el archivo exista y la estructura requerida."""
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
        cursor = self.conn.cursor()
        if limite and limite > 0:
            sql = """
                SELECT TOP {limite} Ficha_No, Fecha, FechaMod, DatosFijos,
                EtiquetasMARC, TipoMaterial, ISBN, Titulo, Autor, Clasificacion
                FROM FICHAS
            """.format(limite=limite)
        else:
            sql = """
                SELECT Ficha_No, Fecha, FechaMod, DatosFijos, EtiquetasMARC,
                       TipoMaterial, ISBN, Titulo, Autor, Clasificacion
                FROM FICHAS
            """

        cursor.execute(sql)
        columnas = [desc[0] for desc in cursor.description]
        filas = cursor.fetchall()
        return [dict(zip(columnas, fila)) for fila in filas]

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
    Formato aproximado: ¦020¦contenido¦041¦contenido¦082895.63¦1
    Devuelve lista de diccionarios: {"tag": "020", "content": "..."}
    """
    if not texto:
        return []

    texto = texto.strip()
    if not texto.startswith("¦"):
        return []

    campos = []
    partes = texto.split("¦")
    # Las partes alternan: ["", "020", "contenido", "041", "contenido", ...]
    i = 1
    while i < len(partes) - 1:
        tag = partes[i].strip()
        contenido = partes[i + 1].strip() if i + 1 < len(partes) else ""
        # Si el tag tiene más de 3 caracteres, puede ser que el contenido
        # se haya pegado al tag (ej: "082895.63"). Intentar separar.
        if len(tag) == 3 and tag.isdigit():
            campos.append({"tag": tag, "content": contenido})
            i += 2
        elif len(tag) > 3 and tag[:3].isdigit():
            campos.append({"tag": tag[:3], "content": tag[3:] + " " + contenido})
            i += 2
        else:
            i += 1
    return campos


def formatear_fecha_marc(dt: Optional[datetime]) -> str:
    """Convierte datetime de Access a formato MARC 005: YYYYMMDDHHMMSS.0"""
    if dt is None:
        return datetime.now().strftime("%Y%m%d%H%M%S.0")
    return dt.strftime("%Y%m%d%H%M%S.0")
