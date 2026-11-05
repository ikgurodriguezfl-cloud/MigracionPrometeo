"""Escritura de registros MARC21 y ejemplares a MySQL."""
from hashlib import sha256
from collections import Counter
from datetime import datetime
from io import BytesIO, StringIO
import pymysql
from pymarc import MARCReader, parse_xml_to_array
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS correcciones_marc (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    lote_id VARCHAR(40) NOT NULL,
                    id_ficha_acceso INT UNSIGNED NOT NULL,
                    marca_marcxml_propuesta LONGTEXT NOT NULL,
                    marca_iso2709_propuesta LONGBLOB NOT NULL,
                    huella_original CHAR(64) NOT NULL,
                    propuesto_por VARCHAR(100) NOT NULL,
                    estado ENUM('PENDIENTE','APROBADA','RECHAZADA')
                        NOT NULL DEFAULT 'PENDIENTE',
                    decidido_por VARCHAR(100),
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_decision TIMESTAMP NULL,
                    INDEX idx_lote_estado (lote_id, estado),
                    INDEX idx_ficha_estado (id_ficha_acceso, estado)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS observaciones_revision (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    lote_id VARCHAR(40) NOT NULL,
                    id_ficha_acceso INT UNSIGNED NOT NULL,
                    usuario VARCHAR(100) NOT NULL,
                    observacion TEXT NOT NULL,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_lote_ficha_fecha (lote_id, id_ficha_acceso, fecha)
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
                          ejemplar: Dict, branch_koha: Optional[str],
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

    @staticmethod
    def _valores_ejemplar(ejemplar, branch_koha, signatura):
        fecha = ejemplar.get('FechaIngreso')
        if isinstance(fecha, datetime):
            fecha = fecha.date()
        return (
            ejemplar.get('NumAdqui'),
            str(ejemplar.get('Biblioteca', ''))
            if ejemplar.get('Biblioteca') is not None else '',
            branch_koha,
            int(ejemplar['Volumen']) if ejemplar.get('Volumen') is not None else None,
            int(ejemplar['Ejemplar']) if ejemplar.get('Ejemplar') is not None else None,
            int(ejemplar['Tomo']) if ejemplar.get('Tomo') is not None else None,
            int(ejemplar['Accesible']) if ejemplar.get('Accesible') is not None else None,
            fecha,
            signatura,
        )

    @staticmethod
    def _clave_ejemplar(valores):
        if valores[0] is not None:
            return ('num_adqui', str(valores[0]))
        return ('datos', *valores[1:])

    def insertar_ejemplares_faltantes(self, id_ficha, ejemplares,
                                      branch_mapping, signatura=None):
        with self.conn.cursor() as cur:
            cur.execute(
                'SELECT id FROM registros_marc WHERE id_ficha_acceso = %s',
                (id_ficha,),
            )
            registro = cur.fetchone()
            if registro is None:
                raise ValueError('No existe el registro MARC que contiene estos ejemplares.')
            id_registro = registro['id']
            cur.execute(
                'SELECT num_adqui, biblioteca, branch_koha, volumen, ejemplar, '
                'tomo, accesible, fecha_ingreso, signatura '
                'FROM ejemplares_marc WHERE id_ficha_acceso = %s',
                (id_ficha,),
            )
            existentes = cur.fetchall()

        conteo = Counter(
            self._clave_ejemplar((
                item['num_adqui'], item['biblioteca'], item['branch_koha'],
                item['volumen'], item['ejemplar'], item['tomo'],
                item['accesible'], item['fecha_ingreso'], item['signatura'],
            ))
            for item in existentes
        )
        insertados = 0
        sucursales_sin_mapeo = []
        for ejemplar in ejemplares:
            biblioteca = ejemplar.get('Biblioteca')
            codigo = str(biblioteca).strip() if biblioteca is not None else ''
            branch_koha = branch_mapping.get(codigo) if codigo else None
            valores = self._valores_ejemplar(
                ejemplar, branch_koha, signatura,
            )
            clave = self._clave_ejemplar(valores)
            if conteo[clave]:
                conteo[clave] -= 1
                continue
            if not codigo or branch_koha is None:
                sucursales_sin_mapeo.append(codigo or '(vacío)')
            self.insertar_ejemplar(
                id_registro, id_ficha, ejemplar, branch_koha, signatura,
            )
            insertados += 1
        return insertados, sucursales_sin_mapeo

    def registrar_observacion_revision(self, lote_id, id_ficha, usuario,
                                       observacion):
        if (not isinstance(lote_id, str) or not lote_id.strip()
                or len(lote_id) > 40 or type(id_ficha) is not int
                or id_ficha < 0 or not isinstance(usuario, str)
                or not usuario.strip() or len(usuario) > 100
                or not isinstance(observacion, str)
                or not observacion.strip() or len(observacion.strip()) > 5000):
            raise ValueError('La observación requiere lote, ficha, usuario y texto de hasta 5000 caracteres.')
        texto = observacion.strip()
        self.conn.begin()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO observaciones_revision '
                    '(lote_id, id_ficha_acceso, usuario, observacion) '
                    'VALUES (%s,%s,%s,%s)',
                    (lote_id, id_ficha, usuario.strip(), texto),
                )
                observacion_id = cur.lastrowid
                cur.execute(
                    'INSERT INTO log_migracion (nivel, mensaje, id_ficha) '
                    'VALUES (%s,%s,%s)',
                    (
                        'INFO',
                        f'Observación de revisión #{observacion_id} registrada por {usuario.strip()} en lote {lote_id}.',
                        id_ficha,
                    ),
                )
            self.conn.commit()
            return observacion_id
        except Exception:
            self.conn.rollback()
            raise

    def listar_observaciones_revision(self, lote_id, id_ficha):
        if (not isinstance(lote_id, str) or not lote_id.strip()
                or len(lote_id) > 40 or type(id_ficha) is not int
                or id_ficha < 0):
            raise ValueError('El lote o la ficha de las observaciones no es válido.')
        with self.conn.cursor() as cur:
            cur.execute(
                'SELECT id, usuario, observacion, fecha '
                'FROM observaciones_revision WHERE lote_id = %s '
                'AND id_ficha_acceso = %s ORDER BY fecha, id',
                (lote_id, id_ficha),
            )
            return cur.fetchall()

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

    def obtener_registros_revision(self, fichas):
        if not fichas:
            return []
        if len(fichas) > 100:
            raise ValueError('La consulta de revisión no puede superar 100 fichas.')
        if any(type(ficha) is not int or ficha < 0 for ficha in fichas):
            raise ValueError('La lista de fichas para revisión no es válida.')

        marcadores = ','.join(['%s'] * len(fichas))
        with self.conn.cursor() as cur:
            cur.execute(
                'SELECT id_ficha_acceso, id_control, marca_marcxml, '
                'marca_iso2709, estado, '
                'fecha_creacion, fecha_actualizacion FROM registros_marc '
                f'WHERE id_ficha_acceso IN ({marcadores}) '
                'ORDER BY id_ficha_acceso',
                tuple(fichas),
            )
            registros = cur.fetchall()
            if len(registros) != len(set(fichas)):
                raise ValueError(
                    'El destino no contiene todos los registros del grupo solicitado. '
                    'Revisa la base de datos antes de continuar.'
                )
            cur.execute(
                'SELECT id_ficha_acceso, num_adqui, biblioteca, branch_koha, '
                'volumen, ejemplar, tomo, accesible, fecha_ingreso, signatura '
                'FROM ejemplares_marc '
                f'WHERE id_ficha_acceso IN ({marcadores}) '
                'ORDER BY id_ficha_acceso, id',
                tuple(fichas),
            )
            ejemplares = cur.fetchall()

        por_ficha = {ficha: [] for ficha in fichas}
        for ejemplar in ejemplares:
            por_ficha[ejemplar['id_ficha_acceso']].append(ejemplar)
        for registro in registros:
            registro['ejemplares'] = por_ficha[registro['id_ficha_acceso']]
            registro['huella_revision'] = self.huella_registro(
                registro['marca_marcxml'], registro['marca_iso2709'],
            )
        return registros

    @staticmethod
    def huella_registro(marcxml, iso2709):
        xml_bytes = marcxml if isinstance(marcxml, bytes) else str(marcxml or '').encode('utf-8')
        iso_bytes = bytes(iso2709) if iso2709 is not None else b''
        return sha256(xml_bytes + b'\0' + iso_bytes).hexdigest()

    @staticmethod
    def _validar_registro_propuesto(marcxml, iso2709):
        if not isinstance(marcxml, str) or not marcxml.strip():
            raise ValueError('El MARCXML propuesto está vacío.')
        if not isinstance(iso2709, bytes) or not iso2709:
            raise ValueError('El MARC ISO2709 propuesto está vacío.')
        try:
            desde_xml = parse_xml_to_array(StringIO(marcxml), strict=True)
            registros_iso = list(MARCReader(BytesIO(iso2709), to_unicode=True))
        except Exception as exc:
            raise ValueError(f'El registro MARC propuesto está corrupto: {exc}') from exc
        if (len(desde_xml) != 1 or len(registros_iso) != 1
                or registros_iso[0] is None):
            raise ValueError('La propuesta debe contener exactamente un registro MARC válido.')
        record_xml = desde_xml[0]
        desde_iso = registros_iso[0]
        if record_xml.as_dict() != desde_iso.as_dict():
            raise ValueError('Las versiones MARCXML e ISO2709 no representan el mismo registro.')

        errores = []
        if len(str(record_xml.leader)) != 24:
            errores.append('LDR debe tener exactamente 24 caracteres')
        campo_001 = record_xml.get_fields('001')
        if not campo_001 or not (campo_001[0].data or '').strip():
            errores.append('falta el campo 001')
        campo_005 = record_xml.get_fields('005')
        if not campo_005 or len((campo_005[0].data or '').strip()) != 16:
            errores.append('005 debe tener el formato MARC YYYYMMDDHHMMSS.0 (16 caracteres)')
        campo_008 = record_xml.get_fields('008')
        if not campo_008 or len(campo_008[0].data or '') != 40:
            errores.append('008 debe tener exactamente 40 caracteres')
        campo_040 = record_xml.get_fields('040')
        if not campo_040 or any(
            not (campo_040[0].get_subfields(codigo) or [''])[0].strip()
            for codigo in ('a', 'c')
        ):
            errores.append('040 debe incluir los subcampos $a y $c')
        campo_245 = record_xml.get_fields('245')
        if not campo_245 or not any(
            valor.strip()
            for campo in campo_245 for valor in campo.get_subfields('a')
        ):
            errores.append('falta el título principal 245$a')
        if errores:
            raise ValueError('El registro está incompleto: ' + '; '.join(errores) + '.')
        return record_xml

    def proponer_correccion(self, lote_id, id_ficha, marcxml, iso2709,
                            huella_original, usuario):
        self._validar_registro_propuesto(marcxml, iso2709)
        self.conn.begin()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    'SELECT marca_marcxml, marca_iso2709 FROM registros_marc '
                    'WHERE id_ficha_acceso = %s FOR UPDATE',
                    (id_ficha,),
                )
                actual = cur.fetchone()
                if actual is None:
                    raise ValueError('No existe el registro que se desea corregir.')
                if self.huella_registro(
                    actual['marca_marcxml'], actual['marca_iso2709'],
                ) != huella_original:
                    raise ValueError(
                        'El registro cambió desde que se abrió para revisión. '
                        'Actualiza la vista y vuelve a proponer la corrección.'
                    )
                cur.execute(
                    "SELECT id FROM correcciones_marc WHERE lote_id = %s "
                    "AND id_ficha_acceso = %s AND estado = 'PENDIENTE' "
                    'FOR UPDATE',
                    (lote_id, id_ficha),
                )
                if cur.fetchone() is not None:
                    raise ValueError(
                        'Ya hay una corrección pendiente para esta ficha. '
                        'Espera a que Aprobación la resuelva.'
                    )
                cur.execute(
                    'INSERT INTO correcciones_marc '
                    '(lote_id, id_ficha_acceso, marca_marcxml_propuesta, '
                    'marca_iso2709_propuesta, huella_original, propuesto_por) '
                    'VALUES (%s,%s,%s,%s,%s,%s)',
                    (lote_id, id_ficha, marcxml, iso2709, huella_original, usuario),
                )
                propuesta_id = cur.lastrowid
                cur.execute(
                    'INSERT INTO log_migracion (nivel, mensaje, id_ficha) '
                    'VALUES (%s,%s,%s)',
                    ('INFO', f'Corrección MARC #{propuesta_id} propuesta por {usuario}; pendiente de aprobación.', id_ficha),
                )
            self.conn.commit()
            return propuesta_id
        except Exception:
            self.conn.rollback()
            raise

    def listar_correcciones_pendientes(self, lote_id):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.lote_id, c.id_ficha_acceso, "
                "c.marca_marcxml_propuesta, c.marca_iso2709_propuesta, "
                "c.huella_original, c.propuesto_por, c.fecha_creacion, "
                "r.marca_marcxml AS marca_marcxml_actual, "
                "r.marca_iso2709 AS marca_iso2709_actual "
                "FROM correcciones_marc c JOIN registros_marc r "
                "ON r.id_ficha_acceso = c.id_ficha_acceso "
                "WHERE c.lote_id = %s AND c.estado = 'PENDIENTE' "
                "ORDER BY c.fecha_creacion, c.id",
                (lote_id,),
            )
            return cur.fetchall()

    def resolver_correccion(self, propuesta_id, lote_id, usuario,
                            aprobar):
        estado_final = 'APROBADA' if aprobar else 'RECHAZADA'
        self.conn.begin()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id, id_ficha_acceso, marca_marcxml_propuesta, "
                    "marca_iso2709_propuesta, huella_original, propuesto_por "
                    "FROM correcciones_marc WHERE id = %s AND lote_id = %s "
                    "AND estado = 'PENDIENTE' FOR UPDATE",
                    (propuesta_id, lote_id),
                )
                propuesta = cur.fetchone()
                if propuesta is None:
                    raise ValueError(
                        'La propuesta no existe, ya fue resuelta o pertenece a otro lote.'
                    )
                if propuesta['propuesto_por'] == usuario:
                    raise ValueError(
                        'La persona que propuso la corrección no puede aprobarla ni rechazarla.'
                    )
                if aprobar:
                    registro_propuesto = self._validar_registro_propuesto(
                        propuesta['marca_marcxml_propuesta'],
                        bytes(propuesta['marca_iso2709_propuesta']),
                    )
                    cur.execute(
                        'SELECT marca_marcxml, marca_iso2709 FROM registros_marc '
                        'WHERE id_ficha_acceso = %s FOR UPDATE',
                        (propuesta['id_ficha_acceso'],),
                    )
                    actual = cur.fetchone()
                    if actual is None or self.huella_registro(
                        actual['marca_marcxml'], actual['marca_iso2709'],
                    ) != propuesta['huella_original']:
                        raise ValueError(
                            'El registro cambió después de la propuesta. '
                            'No se aplicó la corrección; debe revisarse de nuevo.'
                        )
                    id_control = registro_propuesto['001'].data
                    cur.execute(
                        "UPDATE registros_marc SET marca_marcxml = %s, "
                        "marca_iso2709 = %s, id_control = %s, estado = 'VALIDADO' "
                        'WHERE id_ficha_acceso = %s',
                        (
                            propuesta['marca_marcxml_propuesta'],
                            propuesta['marca_iso2709_propuesta'],
                            id_control, propuesta['id_ficha_acceso'],
                        ),
                    )
                cur.execute(
                    'UPDATE correcciones_marc SET estado = %s, decidido_por = %s, '
                    'fecha_decision = CURRENT_TIMESTAMP WHERE id = %s',
                    (estado_final, usuario, propuesta_id),
                )
                cur.execute(
                    'INSERT INTO log_migracion (nivel, mensaje, id_ficha) '
                    'VALUES (%s,%s,%s)',
                    (
                        'INFO',
                        f'Corrección MARC #{propuesta_id} {estado_final.lower()} por {usuario}.',
                        propuesta['id_ficha_acceso'],
                    ),
                )
            self.conn.commit()
            return estado_final
        except Exception:
            self.conn.rollback()
            raise
