"""Seguimiento local de ejecuciones; no modifica el esquema de Access o MySQL."""
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import RLock
from typing import Optional
from uuid import uuid4


ESTADOS = {
    'en_espera': 'En espera', 'en_proceso': 'En proceso',
    'concluido': 'Concluido', 'con_incidencias': 'Con incidencias',
    'detenido': 'Detenido',
}
ETAPAS = {
    'recepcion': 'Respaldo validado', 'conexion': 'Conexión al destino',
    'lectura': 'Lectura de fichas', 'conversion': 'Conversión y guardado MARC21',
    'revision': 'Revisión de incidencias', 'finalizado': 'Procesamiento finalizado',
}
ESTADOS_FICHA = ('Convertida', 'Omitida', 'Rechazada')


def _validar_resultado(fila):
    if (not isinstance(fila, dict) or fila.get('estado') not in ESTADOS_FICHA
            or not isinstance(fila.get('referencia'), str)
            or not isinstance(fila.get('titulo'), str)
            or not isinstance(fila.get('motivos'), list)
            or not all(isinstance(motivo, str) for motivo in fila['motivos'])):
        raise ValueError('El detalle de una ficha no es válido.')


def ahora():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def ruta_historial():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home())
    return base / 'PrometeoMigrator' / 'lotes.json'


@dataclass
class Lote:
    id: str
    fuente: str
    total_recibidos: int
    total_objetivo: int
    destino: dict = field(default_factory=dict)
    version_mapeo: Optional[str] = None
    huella_mapeo: Optional[str] = None
    estado: str = 'en_espera'
    etapa: str = 'recepcion'
    correctos: int = 0
    omitidos: int = 0
    errores: int = 0
    ejemplares: int = 0
    creado_en: str = field(default_factory=ahora)
    actualizado_en: str = field(default_factory=ahora)
    fichas_correctas: list = field(default_factory=list)
    incidencias: list = field(default_factory=list)
    actividad: list = field(default_factory=list)
    lote_origen: Optional[str] = None
    # Los historiales de la interfaz institucional conservan detalle por ficha.
    resultados: Optional[list] = None
    usuario: Optional[str] = None
    omitir_existentes: bool = True
    iniciado_en: Optional[str] = None

    @property
    def procesados(self):
        return self.correctos + self.omitidos + self.errores

    @property
    def pendientes(self):
        return self.total_objetivo - self.procesados

    @property
    def progreso(self):
        return round(self.procesados * 100 / self.total_objetivo, 1) if self.total_objetivo else 0

    def validar(self, *, detalle=True):
        if self.estado not in ESTADOS or self.etapa not in ETAPAS:
            raise ValueError('Estado o etapa del lote no reconocido.')
        for campo in ('total_recibidos', 'total_objetivo', 'correctos', 'omitidos', 'errores', 'ejemplares'):
            valor = getattr(self, campo)
            if type(valor) is not int or valor < 0:
                raise ValueError(f'{campo}: el conteo debe ser un entero no negativo.')
        if not self.procesados <= self.total_objetivo <= self.total_recibidos:
            raise ValueError('Los conteos del lote son inconsistentes.')
        if detalle and (not isinstance(self.fichas_correctas, list)
                or any(type(ficha) is not int or ficha < 0 for ficha in self.fichas_correctas)
                or len(set(self.fichas_correctas)) != len(self.fichas_correctas)
                or len(self.fichas_correctas) != self.correctos):
            raise ValueError('El listado de fichas correctas no coincide con su conteo.')
        if self.estado == 'en_espera' and (self.procesados or self.etapa != 'recepcion'):
            raise ValueError('Un lote en espera no puede tener procesamiento iniciado.')
        if self.estado == 'concluido' and (self.pendientes or self.errores or self.incidencias or not self.total_objetivo or self.etapa != 'finalizado'):
            raise ValueError('El lote no puede concluir con pendientes, errores o sin registros.')
        if self.estado == 'con_incidencias' and not (self.errores or self.incidencias):
            raise ValueError('Falta describir la incidencia del lote.')
        if self.estado == 'detenido' and (not self.pendientes or self.etapa == 'finalizado'):
            raise ValueError('Un lote detenido debe conservar registros pendientes y la etapa interrumpida.')
        if not isinstance(self.destino, dict) or set(self.destino) - {'host', 'port', 'database'}:
            raise ValueError('El historial no admite credenciales de conexión.')
        if ((self.version_mapeo is None) != (self.huella_mapeo is None)
                or (self.version_mapeo is not None
                    and (not isinstance(self.version_mapeo, str) or not self.version_mapeo.strip()))
                or (self.huella_mapeo is not None
                    and (not isinstance(self.huella_mapeo, str)
                         or len(self.huella_mapeo) != 64
                         or any(caracter not in '0123456789abcdef'
                                for caracter in self.huella_mapeo)))):
            raise ValueError('La versión y huella del mapeo deben ser válidas y registrarse juntas.')
        if not isinstance(self.fuente, str) or not self.fuente or not isinstance(self.id, str) or not self.id:
            raise ValueError('El lote necesita identificador y fuente.')
        if self.lote_origen is not None and (
                not isinstance(self.lote_origen, str) or not self.lote_origen):
            raise ValueError('El lote de origen del reprocesamiento no es válido.')
        if self.usuario is not None and not isinstance(self.usuario, str):
            raise ValueError('El usuario del lote no es válido.')
        if type(self.omitir_existentes) is not bool:
            raise ValueError('La opción de omitir existentes debe ser booleana.')
        if self.resultados is not None:
            if not isinstance(self.resultados, list) or len(self.resultados) != self.procesados:
                raise ValueError('El detalle de fichas no coincide con el total procesado.')
            conteos = dict.fromkeys(ESTADOS_FICHA, 0)
            convertidas = []
            for fila in self.resultados:
                _validar_resultado(fila)
                conteos[fila['estado']] += 1
                if fila['estado'] == 'Convertida':
                    convertidas.append(fila.get('id'))
            if (list(conteos.values()) != [self.correctos, self.omitidos, self.errores]
                    or convertidas != self.fichas_correctas):
                raise ValueError('Los resultados por ficha no coinciden con sus conteos.')
        for campo in ('creado_en', 'actualizado_en'):
            if datetime.fromisoformat(getattr(self, campo)).tzinfo is None:
                raise ValueError('Las fechas del lote requieren zona horaria.')
        if self.iniciado_en is not None and datetime.fromisoformat(self.iniciado_en).tzinfo is None:
            raise ValueError('La fecha de ejecución requiere zona horaria.')
        for campo, claves in (('incidencias', {'referencia', 'mensaje'}), ('actividad', {'fecha', 'mensaje'})):
            elementos = getattr(self, campo)
            if (not isinstance(elementos, list) or len(elementos) > 100
                    or any(not isinstance(item, dict) or set(item) != claves
                           or any(not isinstance(valor, str) for valor in item.values()) for item in elementos)):
                raise ValueError(f'{campo}: formato no válido.')

    def evento(self, mensaje):
        self.actualizado_en = ahora()
        self.actividad.append({'fecha': self.actualizado_en, 'mensaje': mensaje})
        self.actividad = self.actividad[-100:]


def acciones_lote(lote, ocupado=False, fuente_validada=False, destino_coincide=False, demostracion=False,
                  lote_activo_id=None, detencion_solicitada=False):
    """Una sola política para botones y comprobaciones antes de ejecutar."""
    real = lote is not None and not demostracion
    activo = bool(real and ocupado and lote.id == lote_activo_id and lote.estado == 'en_proceso')
    return {
        'iniciar': bool(real and not ocupado and fuente_validada and lote.estado == 'en_espera'),
        'reprocesar': bool(
            real and not ocupado
            and lote.estado in ('concluido', 'con_incidencias', 'detenido')
        ),
        'resumen': bool(lote and lote.estado in ('concluido', 'con_incidencias', 'detenido')),
        'incidencias': bool(lote and (lote.errores or lote.incidencias)),
        'revision': bool(real and not ocupado and destino_coincide and lote.correctos),
        'exportar': bool(real and not ocupado and destino_coincide and lote.estado == 'concluido' and lote.correctos),
        'detener': bool(activo and not detencion_solicitada),
        'detencion_solicitada': bool(activo and detencion_solicitada),
    }


class HistorialLotes:
    def __init__(self, ruta=None):
        self.ruta = Path(ruta) if ruta is not None else ruta_historial()
        self.ruta_detalle = self.ruta.with_suffix('.sqlite3')
        self._lock = RLock()
        self._lotes = []
        self._incrementales = set()
        self.error_carga = None
        self.solo_lectura = False
        self._cargar()
        if not self.solo_lectura and self.ruta_detalle.exists():
            self._cargar_incrementales()

    def _conexion_detalle(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(self.ruta_detalle)
        try:
            with conexion:
                conexion.execute('CREATE TABLE IF NOT EXISTS lotes (id TEXT PRIMARY KEY, resumen TEXT NOT NULL)')
                conexion.execute(
                    'CREATE TABLE IF NOT EXISTS resultados ('
                    'lote TEXT NOT NULL, posicion INTEGER NOT NULL, datos TEXT NOT NULL, '
                    'PRIMARY KEY (lote, posicion))'
                )
            return conexion
        except Exception:
            conexion.close()
            raise

    def _cargar_incrementales(self):
        try:
            with closing(self._conexion_detalle()) as conexion:
                lotes = [Lote(**json.loads(fila[0])) for fila in conexion.execute(
                    'SELECT resumen FROM lotes ORDER BY rowid'
                )]
            for lote in lotes:
                lote.validar(detalle=False)
                if lote.estado == 'en_proceso':
                    lote.estado = 'con_incidencias'
                    lote.incidencias = (lote.incidencias + [{
                        'referencia': 'Ejecución',
                        'mensaje': 'La aplicación se cerró antes de confirmar el resultado. Revisa los últimos conteos guardados.',
                    }])[-100:]
                    lote.evento('Se detectó una ejecución interrumpida; requiere revisión.')
                    self._guardar_incremental(lote)
            self._incrementales.update(lote.id for lote in lotes)
            self._lotes = [lote for lote in self._lotes if lote.id not in self._incrementales] + lotes
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.error_carga = f'No se pudo cargar el detalle del historial: {exc}'
            self.solo_lectura = True

    def _guardar_incremental(self, lote, filas=()):
        if self.solo_lectura:
            raise OSError('El historial está en modo de consulta.')
        lote.validar(detalle=False)
        inicio = lote.procesados - len(filas)
        try:
            with closing(self._conexion_detalle()) as conexion, conexion:
                conexion.executemany(
                    'INSERT INTO resultados (lote, posicion, datos) VALUES (?, ?, ?)',
                    ((lote.id, pos, json.dumps(fila, ensure_ascii=False))
                     for pos, fila in enumerate(filas, inicio + 1)),
                )
                conexion.execute(
                    'INSERT INTO lotes (id, resumen) VALUES (?, ?) '
                    'ON CONFLICT(id) DO UPDATE SET resumen=excluded.resumen',
                    (lote.id, json.dumps(asdict(lote), ensure_ascii=False)),
                )
        except sqlite3.Error as exc:
            raise OSError(f'No se pudo guardar el avance del lote: {exc}') from exc

    def _detalle(self, lote):
        if lote.id in self._incrementales:
            with closing(self._conexion_detalle()) as conexion:
                filas = [json.loads(fila[0]) for fila in conexion.execute(
                    'SELECT datos FROM resultados WHERE lote=? AND posicion<=? ORDER BY posicion',
                    (lote.id, lote.procesados),
                )]
            lote.resultados = filas
            lote.fichas_correctas = [f['id'] for f in filas if f['estado'] == 'Convertida']
            lote.validar()
        return lote

    def _cargar(self):
        if not self.ruta.exists():
            return
        try:
            documento = json.loads(self.ruta.read_text(encoding='utf-8'))
            if documento.get('version') != 1 or not isinstance(documento.get('lotes'), list):
                raise ValueError('Formato no reconocido.')
            lotes = [Lote(**dato) for dato in documento['lotes']]
            if len({lote.id for lote in lotes}) != len(lotes):
                raise ValueError('Identificadores repetidos.')
            for lote in lotes:
                lote.validar()
            # Una ejecución de otro proceso no puede continuar por sí sola al reabrir.
            interrumpidos = False
            for lote in lotes:
                if lote.estado == 'en_proceso':
                    interrumpidos = True
                    lote.estado = 'con_incidencias'
                    lote.incidencias.append({'referencia': 'Ejecución', 'mensaje': 'La aplicación se cerró antes de confirmar el resultado. Revisa los últimos conteos guardados.'})
                    lote.incidencias = lote.incidencias[-100:]
                    lote.evento('Se detectó una ejecución interrumpida; requiere revisión.')
            self._lotes = lotes
            if interrumpidos:
                self._guardar(lotes)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.error_carga = f'No se pudo cargar el historial de lotes: {exc}'
            self.solo_lectura = True

    def _guardar(self, lotes):
        if self.solo_lectura:
            raise OSError('El historial está en modo de consulta para conservar el archivo anterior.')
        lotes = [lote for lote in lotes if lote.id not in self._incrementales]
        for lote in lotes:
            lote.validar()
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.ruta.parent, delete=False) as archivo:
                temporal = archivo.name
                json.dump({'version': 1, 'lotes': [asdict(lote) for lote in lotes]}, archivo, ensure_ascii=False, indent=2)
            os.replace(temporal, self.ruta)
        finally:
            if temporal and os.path.exists(temporal):
                os.unlink(temporal)

    def listar(self, *, resumen=False):
        with self._lock:
            lotes = list(reversed(self._lotes))
        if resumen:
            return [self._resumen(lote) for lote in lotes]
        return [self._detalle(copy.deepcopy(lote)) for lote in lotes]

    @staticmethod
    def _resumen(lote):
        return copy.deepcopy(replace(lote, fichas_correctas=[], resultados=None))

    def obtener(self, identificador, *, resumen=False):
        with self._lock:
            lote = next((lote for lote in self._lotes if lote.id == identificador), None)
        if lote is not None:
            return self._resumen(lote) if resumen else self._detalle(copy.deepcopy(lote))

    def _persistir(self, lote, *, incremental=False, filas=()):
        lotes = self._lotes.copy()
        indice = next((i for i, anterior in enumerate(lotes) if anterior.id == lote.id), len(lotes))
        lotes[indice:indice + 1] = [lote]
        if incremental or lote.id in self._incrementales:
            self._guardar_incremental(lote, filas)
            self._incrementales.add(lote.id)
        else:
            self._guardar(lotes)
        self._lotes = lotes

    def recibir(self, fuente, total, *, incremental=False):
        with self._lock:
            fuente = os.path.abspath(fuente)
            lote = next((item for item in reversed(self._lotes)
                         if item.fuente == fuente and item.estado == 'en_espera'), None)
            if lote is None:
                lote = Lote(f'LOTE-{datetime.now():%Y%m%d}-{uuid4().hex[:8].upper()}', fuente, total, total)
                lote.evento('Respaldo validado. Lote recibido y en espera de ejecución.')
            else:
                lote = copy.deepcopy(lote)
                lote.total_recibidos = lote.total_objetivo = total
                lote.evento('Se actualizó el conteo del respaldo validado.')
            self._persistir(lote, incremental=incremental)
            return copy.deepcopy(lote)

    def recibir_reprocesamiento(self, identificador, total, *, incremental=False):
        if type(total) is not int or total < 0:
            raise ValueError('El conteo del respaldo debe ser un entero no negativo.')
        with self._lock:
            origen = next(
                (item for item in self._lotes if item.id == identificador), None,
            )
            if origen is None:
                raise ValueError('No se encontró el lote que se desea reprocesar.')
            if origen.estado not in ('concluido', 'con_incidencias', 'detenido'):
                raise ValueError('Solo se pueden reprocesar lotes ya finalizados o detenidos.')
            if total != origen.total_recibidos:
                raise ValueError(
                    'El respaldo tiene un número de fichas distinto al lote original.'
                )
            if origen.total_objetivo > total:
                raise ValueError('El alcance del lote original no es válido para reprocesar.')

            nuevo = Lote(
                f'LOTE-{datetime.now():%Y%m%d}-{uuid4().hex[:8].upper()}',
                origen.fuente, total, origen.total_objetivo,
                lote_origen=origen.id,
            )
            nuevo.evento(
                f'Reprocesamiento del lote {origen.id}. Se conservarán los '
                'registros existentes y se completarán los faltantes.'
            )
            self._persistir(nuevo, incremental=incremental)
            return copy.deepcopy(nuevo)

    def actualizar(self, identificador, *, filas=None, **cambios):
        permitidos = {'estado', 'etapa', 'total_objetivo', 'destino', 'version_mapeo',
                      'huella_mapeo', 'correctos', 'omitidos', 'errores', 'ejemplares',
                      'fichas_correctas', 'incidencias', 'resultados', 'usuario',
                      'omitir_existentes', 'iniciado_en'}
        mensaje = cambios.pop('evento', None)
        if set(cambios) - permitidos:
            raise ValueError('Se intentó cambiar un campo no permitido del lote.')
        with self._lock:
            anterior = next((item for item in self._lotes if item.id == identificador), None)
            if anterior is None:
                raise ValueError('No se encontró el lote solicitado.')
            lote = copy.deepcopy(anterior)
            for campo, valor in cambios.items():
                setattr(lote, campo, copy.deepcopy(valor))
            if mensaje:
                lote.evento(mensaje)
            else:
                lote.actualizado_en = ahora()
            if identificador in self._incrementales or filas is not None:
                filas = filas or []
                for fila in filas:
                    _validar_resultado(fila)
                    id_ficha = fila.get('id')
                    if ((fila['estado'] != 'Rechazada' or id_ficha is not None)
                            and (type(id_ficha) is not int or id_ficha < 0)):
                        raise ValueError('El resultado requiere un identificador válido de Access.')
                conteos = [sum(f['estado'] == estado for f in filas) for estado in ESTADOS_FICHA]
                if (sum(conteos) != len(filas) or conteos != [
                    lote.correctos - anterior.correctos, lote.omitidos - anterior.omitidos,
                    lote.errores - anterior.errores,
                ] or (identificador not in self._incrementales and anterior.procesados)):
                    raise ValueError('Los resultados nuevos no coinciden con el avance del lote.')
                lote.resultados = None
                lote.fichas_correctas = []
                self._persistir(lote, incremental=True, filas=filas)
            else:
                self._persistir(lote)
            return copy.deepcopy(lote)


def lotes_de_ejemplo():
    """Escenarios aislados; nunca se guardan ni se ejecutan como migraciones."""
    resultado = []
    for indice, (estado, etapa, correctos, omitidos, errores) in enumerate((
        ('en_espera', 'recepcion', 0, 0, 0),
        ('en_proceso', 'conversion', 54, 6, 0),
        ('concluido', 'finalizado', 90, 10, 0),
        ('con_incidencias', 'revision', 80, 5, 10),
    ), start=1):
        lote = Lote(f'EJEMPLO-{indice:02}', f'Colección de ejemplo {indice}.mdb', 100, 100,
                    estado=estado, etapa=etapa, correctos=correctos, omitidos=omitidos, errores=errores,
                    fichas_correctas=list(range(1, correctos + 1)))
        if errores:
            lote.incidencias = [{'referencia': 'Ficha de ejemplo', 'mensaje': 'Falta información para convertir el registro. El detalle de este escenario es ilustrativo.'}]
        lote.evento('Escenario de demostración; no representa una migración real.')
        lote.validar()
        resultado.append(lote)
    return resultado
