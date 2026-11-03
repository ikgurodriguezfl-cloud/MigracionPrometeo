"""Seguimiento local de ejecuciones; no modifica el esquema de Access o MySQL."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
import copy
import json
import os
from pathlib import Path
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

    @property
    def procesados(self):
        return self.correctos + self.omitidos + self.errores

    @property
    def pendientes(self):
        return self.total_objetivo - self.procesados

    @property
    def progreso(self):
        return round(self.procesados * 100 / self.total_objetivo, 1) if self.total_objetivo else 0

    def validar(self):
        if self.estado not in ESTADOS or self.etapa not in ETAPAS:
            raise ValueError('Estado o etapa del lote no reconocido.')
        for campo in ('total_recibidos', 'total_objetivo', 'correctos', 'omitidos', 'errores', 'ejemplares'):
            valor = getattr(self, campo)
            if type(valor) is not int or valor < 0:
                raise ValueError(f'{campo}: el conteo debe ser un entero no negativo.')
        if not self.procesados <= self.total_objetivo <= self.total_recibidos:
            raise ValueError('Los conteos del lote son inconsistentes.')
        if (not isinstance(self.fichas_correctas, list)
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
        for campo in ('creado_en', 'actualizado_en'):
            if datetime.fromisoformat(getattr(self, campo)).tzinfo is None:
                raise ValueError('Las fechas del lote requieren zona horaria.')
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
        'resumen': bool(lote and lote.estado in ('concluido', 'con_incidencias', 'detenido')),
        'incidencias': bool(lote and (lote.errores or lote.incidencias)),
        'exportar': bool(real and not ocupado and destino_coincide and lote.estado == 'concluido' and lote.correctos),
        'detener': bool(activo and not detencion_solicitada),
        'detencion_solicitada': bool(activo and detencion_solicitada),
    }


class HistorialLotes:
    def __init__(self, ruta=None):
        self.ruta = Path(ruta) if ruta is not None else ruta_historial()
        self._lock = RLock()
        self._lotes = []
        self.error_carga = None
        self.solo_lectura = False
        self._cargar()

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

    def listar(self):
        with self._lock:
            return copy.deepcopy(list(reversed(self._lotes)))

    def obtener(self, identificador):
        return next((lote for lote in self.listar() if lote.id == identificador), None)

    def recibir(self, fuente, total):
        with self._lock:
            lotes = copy.deepcopy(self._lotes)
            fuente = os.path.abspath(fuente)
            lote = next((item for item in reversed(lotes) if item.fuente == fuente and item.estado == 'en_espera'), None)
            if lote is None:
                lote = Lote(f'LOTE-{datetime.now():%Y%m%d}-{uuid4().hex[:8].upper()}', fuente, total, total)
                lote.evento('Respaldo validado. Lote recibido y en espera de ejecución.')
                lotes.append(lote)
            else:
                lote.total_recibidos = lote.total_objetivo = total
                lote.evento('Se actualizó el conteo del respaldo validado.')
            self._guardar(lotes)
            self._lotes = lotes
            return copy.deepcopy(lote)

    def actualizar(self, identificador, **cambios):
        permitidos = {'estado', 'etapa', 'total_objetivo', 'destino', 'version_mapeo',
                      'huella_mapeo', 'correctos', 'omitidos', 'errores', 'ejemplares',
                      'fichas_correctas', 'incidencias'}
        mensaje = cambios.pop('evento', None)
        if set(cambios) - permitidos:
            raise ValueError('Se intentó cambiar un campo no permitido del lote.')
        with self._lock:
            lotes = copy.deepcopy(self._lotes)
            lote = next((item for item in lotes if item.id == identificador), None)
            if lote is None:
                raise ValueError('No se encontró el lote solicitado.')
            for campo, valor in cambios.items():
                setattr(lote, campo, copy.deepcopy(valor))
            if mensaje:
                lote.evento(mensaje)
            else:
                lote.actualizado_en = ahora()
            self._guardar(lotes)
            self._lotes = lotes
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
