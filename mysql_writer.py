"""Escritura de registros MARC21 y ejemplares a MySQL."""
import pymysql
from typing import Dict, Optional


class MySQLWriter:
    def __init__(self, config: Dict):
        self.config = config
        self._conn = None

    def connect(self):
        self._conn = pymysql.connect(
            host=self.config.get('host', 'localhost'),
            port=int(self.config.get('port', 3306)),
            user=self.config.get('user', 'root'),
            password=self.config.get('password', ''),
            database=self.config.get('database', 'prometeo_marc'),
            charset=self.config.get('charset', 'utf8mb4'),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
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

    def ensure_database(self):
        """Crea la base de datos si no existe."""
        db_name = self.config.get('database', 'prometeo_marc')
        tmp = pymysql.connect(
            host=self.config.get('host', 'localhost'),
            port=int(self.config.get('port', 3306)),
            user=self.config.get('user', 'root'),
            password=self.config.get('password', ''),
            charset=self.config.get('charset', 'utf8mb4'),
            autocommit=True,
        )
        with tmp.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        tmp.close()

    def test_connection(self) -> bool:
        try:
            self.connect()
            self.close()
            return True
        except Exception:
            return False

    def crear_tablas(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS registros_marc (
                    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    id_ficha_acceso INT UNSIGNED NOT NULL COMMENT 'PK original en Access FICHAS',
                    id_control VARCHAR(50) COMMENT 'MARC 001',
                    marca_marcxml LONGTEXT NOT NULL COMMENT 'Registro MARC21 en MARCXML',
                    marca_iso2709 LONGBLOB COMMENT 'Registro MARC21 en ISO2709',
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    estado ENUM('NUEVO','VALIDADO','ERROR','DUPLICADO') DEFAULT 'NUEVO',
                    UNIQUE KEY uk_id_ficha (id_ficha_acceso),
                    INDEX idx_id_control (id_control)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ejemplares_marc (
                    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    id_registro_marc INT UNSIGNED NOT NULL,
                    id_ficha_acceso INT UNSIGNED NOT NULL COMMENT 'FK a FICHAS en Access',
                    num_adqui VARCHAR(100) COMMENT 'Numero de adquisicion / codigo de barras',
                    biblioteca VARCHAR(50) COMMENT 'Codigo de biblioteca en Access',
                    branch_koha VARCHAR(50) COMMENT 'Codigo de sucursal en Koha',
                    volumen INT UNSIGNED,
                    ejemplar INT UNSIGNED,
                    tomo INT UNSIGNED,
                    accesible INT UNSIGNED,
                    fecha_ingreso DATE,
                    signatura VARCHAR(200) COMMENT 'Clasificacion / signatura',
                    FOREIGN KEY (id_registro_marc) REFERENCES registros_marc(id) ON DELETE CASCADE,
                    UNIQUE KEY uk_num_adqui (num_adqui),
                    INDEX idx_id_ficha (id_ficha_acceso)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS log_migracion (
                    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    nivel ENUM('INFO','WARN','ERROR') DEFAULT 'INFO',
                    mensaje TEXT,
                    id_ficha INT UNSIGNED,
                    id_ejemplar VARCHAR(100)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        self.conn.commit()

    def insertar_log(self, nivel: str, mensaje: str,
                     id_ficha: Optional[int] = None,
                     id_ejemplar: Optional[str] = None):
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO log_migracion (nivel, mensaje, id_ficha, id_ejemplar) VALUES (%s,%s,%s,%s)',
                (nivel, mensaje, id_ficha, id_ejemplar),
            )
        self.conn.commit()

    def registrar_existe(self, id_ficha: int) -> bool:
        with self.conn.cursor() as cur:
            cur.execute('SELECT id FROM registros_marc WHERE id_ficha_acceso = %s', (id_ficha,))
            return cur.fetchone() is not None

    def insertar_registro_marc(self, id_ficha: int, id_control: str,
                               marcxml: str, iso2709: bytes) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO registros_marc '
                '(id_ficha_acceso, id_control, marca_marcxml, marca_iso2709, estado) '
                'VALUES (%s, %s, %s, %s, %s)',
                (id_ficha, id_control, marcxml, iso2709, 'NUEVO'),
            )
            self.conn.commit()
            return cur.lastrowid

    def insertar_ejemplar(self, id_registro_marc: int, id_ficha: int,
                          ejemplar: Dict, branch_koha: str,
                          signatura: Optional[str] = None):
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO ejemplares_marc '
                '(id_registro_marc, id_ficha_acceso, num_adqui, biblioteca, '
                'branch_koha, volumen, ejemplar, tomo, accesible, fecha_ingreso, signatura) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (
                    id_registro_marc,
                    id_ficha,
                    ejemplar.get('NumAdqui'),
                    str(ejemplar.get('Biblioteca', '')) if ejemplar.get('Biblioteca') is not None else '',
                    branch_koha,
                    int(ejemplar['Volumen']) if ejemplar.get('Volumen') is not None else None,
                    int(ejemplar['Ejemplar']) if ejemplar.get('Ejemplar') is not None else None,
                    int(ejemplar['Tomo']) if ejemplar.get('Tomo') is not None else None,
                    int(ejemplar['Accesible']) if ejemplar.get('Accesible') is not None else None,
                    ejemplar.get('FechaIngreso').date() if ejemplar.get('FechaIngreso') else None,
                    signatura,
                ),
            )
        self.conn.commit()

    def obtener_estadisticas(self) -> Dict:
        with self.conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS total FROM registros_marc')
            total_registros = cur.fetchone()['total']
            cur.execute('SELECT COUNT(*) AS total FROM ejemplares_marc')
            total_ejemplares = cur.fetchone()['total']
            cur.execute('SELECT estado, COUNT(*) AS cnt FROM registros_marc GROUP BY estado')
            por_estado = {row['estado']: row['cnt'] for row in cur.fetchall()}
        return {
            'total_registros': total_registros,
            'total_ejemplares': total_ejemplares,
            'por_estado': por_estado,
        }
