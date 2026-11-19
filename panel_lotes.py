"""Panel Tkinter del sprint 2, integrado en el Notebook de MigracionApp."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
import csv
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from xml.sax import SAXException
from xml.etree import ElementTree
from pymarc import Field, JSONReader, MARCReader, Record, Subfield, parse_xml_to_array
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter
from validacion_marc import (ERROR as ERROR_MARC, estado_ficha, es_repetible, inspeccionar_copias,
                             validar_ficha)

from lotes import ESTADOS, ETAPAS, lotes_de_ejemplo
from ui_kit import (
    FONDO, SUPERFICIE, SUPERFICIE_ALT, TEXTO, TEXTO_SECUNDARIO, TEXTO_MUTADO, TEXTO_INVERSO,
    PRIMARIO, PRIMARIO_HOVER, PRIMARIO_SUAVE, BORDE, BORDE_ENFOQUE,
    EXITO, EXITO_SUAVE, ADVERTENCIA, ADVERTENCIA_SUAVE, ERROR, ERROR_SUAVE, INFO, INFO_SUAVE,
    FUENTE, FUENTE_MONO,
    TAM_TITULO_PAGINA, TAM_SUBTITULO_PAGINA, TAM_TARJETA_TITULO,
    TAM_CAMPO_ETIQUETA, TAM_CAMPO_ENTRADA, TAM_CUERPO, TAM_BOTON,
    TAM_TABLA_ENCABEZADO, TAM_TABLA_CUERPO, TAM_METRICA_VALOR, TAM_METRICA_ETIQUETA,
    ESPACIO_XS, ESPACIO_S, ESPACIO_M, ESPACIO_L, ESPACIO_XL,
    instalar_estilos, tarjeta, seccion_tarjeta, encabezado_pagina, badge_estado,
    separador, animar_valor, crear_icono, colorear_icono,
    COLORES_ESTADO_LOTE,
)


def _celda_csv(valor):
    if isinstance(valor, str) and valor.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + valor
    return valor


def escribir_reporte_lote(ruta, lote, demostracion=False):
    """Exporta el resumen y las referencias disponibles del lote seleccionado."""
    ruta = Path(ruta)
    filas = lote.resultados
    traza_completa = filas is not None
    if filas is None:
        filas = [
            {'id': ficha, 'referencia': f'Ficha {ficha}', 'estado': 'Convertida',
             'titulo': '', 'motivos': []}
            for ficha in lote.fichas_correctas
        ]
    temporal = None
    try:
        es_csv = ruta.suffix.lower() == '.csv'
        with NamedTemporaryFile('w', encoding='utf-8-sig' if es_csv else 'utf-8',
                                newline='', dir=ruta.parent, delete=False) as archivo:
            temporal = archivo.name
            if es_csv:
                metadatos = {
                    'lote': lote.id, 'origen': os.path.basename(lote.fuente),
                    'lote_anterior': lote.lote_origen, 'usuario': lote.usuario or 'Sin registrar',
                    'fecha_ejecucion': lote.iniciado_en, 'creado_en': lote.creado_en,
                    'actualizado_en': lote.actualizado_en, 'estado_lote': ESTADOS[lote.estado],
                    'version_mapeo': lote.version_mapeo,
                    'recibidos': lote.total_recibidos, 'objetivo': lote.total_objetivo,
                    'convertidas': lote.correctos, 'omitidas': lote.omitidos,
                    'rechazadas': lote.errores, 'pendientes': lote.pendientes,
                    'fuera_del_alcance': lote.total_recibidos - lote.total_objetivo,
                    'ejemplares': lote.ejemplares, 'trazabilidad_completa': 'Sí' if traza_completa else 'No',
                    'demostracion': 'Sí' if demostracion else 'No',
                }
                columnas = ('ficha_access', 'referencia', 'estado_ficha', 'titulo', 'motivos')
                escritor = csv.writer(archivo)
                escritor.writerow((*metadatos, *columnas))
                datos_lote = [_celda_csv(valor) for valor in metadatos.values()]
                for fila in filas or [None]:
                    valores = (fila['id'], fila['referencia'], fila['estado'],
                               fila['titulo'], ' | '.join(fila['motivos'])) if fila else ('',) * len(columnas)
                    escritor.writerow((*datos_lote, *map(_celda_csv, valores)))
            else:
                json.dump({
                    'demostracion': demostracion, 'lote': asdict(lote),
                    'procesados': lote.procesados, 'pendientes': lote.pendientes,
                    'fuera_del_alcance': lote.total_recibidos - lote.total_objetivo,
                    'progreso': lote.progreso, 'trazabilidad_completa': traza_completa,
                }, archivo, ensure_ascii=False, indent=2)
        os.replace(temporal, ruta)
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def resumir_lotes(lotes):
    por_estado = {estado: 0 for estado in ESTADOS}
    for lote in lotes:
        por_estado[lote.estado] += 1
    return {
        'total_lotes': len(lotes),
        'fichas_correctas': sum(lote.correctos for lote in lotes),
        'ejemplares': sum(lote.ejemplares for lote in lotes),
        'requieren_revision': por_estado['con_incidencias'] + por_estado['detenido'],
        'por_estado': por_estado,
    }


def filtrar_lotes(lotes, estado='Todos', periodo='Todo el historial',
                  orden='Más recientes', hoy=None):
    estados_validos = ('Todos', *ESTADOS.values())
    if estado not in estados_validos:
        raise ValueError(f'Estado de historial no reconocido: {estado}')
    resultado = [
        lote for lote in lotes
        if estado == 'Todos' or ESTADOS[lote.estado] == estado
    ]
    fecha_hoy = hoy or date.today()
    if periodo != 'Todo el historial':
        if periodo == 'Últimos 7 días':
            desde = fecha_hoy - timedelta(days=6)
        elif periodo == 'Últimos 30 días':
            desde = fecha_hoy - timedelta(days=29)
        elif periodo == 'Este año':
            desde = date(fecha_hoy.year, 1, 1)
        else:
            raise ValueError(f'Periodo de historial no reconocido: {periodo}')
        resultado = [
            lote for lote in resultado
            if datetime.fromisoformat(lote.creado_en).date() >= desde
        ]
    ordenes = {
        'Más recientes': lambda lote: datetime.fromisoformat(lote.creado_en),
        'Más antiguos': lambda lote: datetime.fromisoformat(lote.creado_en),
        'Más errores': lambda lote: (
            lote.errores, datetime.fromisoformat(lote.creado_en),
        ),
        'Mayor avance': lambda lote: (
            lote.progreso, datetime.fromisoformat(lote.creado_en),
        ),
    }
    if orden not in ordenes:
        raise ValueError(f'Orden de historial no reconocido: {orden}')
    return sorted(
        resultado,
        key=ordenes[orden],
        reverse=orden != 'Más antiguos',
    )


def datos_grafico(lotes, resumen, tipo):
    if tipo == 'Estado de los lotes':
        return (
            'Cantidad de migraciones por estado',
            [ESTADOS[estado] for estado in ESTADOS],
            [resumen['por_estado'][estado] for estado in ESTADOS],
            ['#687287', PRIMARIO, EXITO, ADVERTENCIA, ERROR],
        )
    if tipo == 'Resultado de fichas':
        return (
            'Fichas agrupadas por resultado',
            ['Convertidas', 'Omitidas', 'Rechazadas', 'Pendientes'],
            [
                sum(lote.correctos for lote in lotes),
                sum(lote.omitidos for lote in lotes),
                sum(lote.errores for lote in lotes),
                sum(lote.pendientes for lote in lotes),
            ],
            [EXITO, INFO, ERROR, '#687287'],
        )
    if tipo == 'Fichas correctas por lote':
        tipo = 'Fichas convertidas por lote'
    if tipo not in ('Fichas convertidas por lote', 'Ejemplares por lote'):
        raise ValueError(f'Tipo de gráfico no reconocido: {tipo}')
    clave = 'correctos' if tipo == 'Fichas convertidas por lote' else 'ejemplares'
    titulo = 'Fichas convertidas por lote' if clave == 'correctos' else 'Ejemplares por lote'
    lotes_destacados = sorted(
        lotes,
        key=lambda lote: (
            getattr(lote, clave), datetime.fromisoformat(lote.actualizado_en),
        ),
        reverse=True,
    )[:10]
    return (
        titulo,
        [f'{lote.id} · {os.path.basename(lote.fuente)}' for lote in lotes_destacados],
        [getattr(lote, clave) for lote in lotes_destacados],
        [PRIMARIO] * len(lotes_destacados),
    )


def campos_desde_marcxml(contenido):
    if not contenido:
        raise ValueError('El registro no contiene MARCXML.')
    try:
        raiz = ElementTree.fromstring(contenido)
    except (ElementTree.ParseError, TypeError) as exc:
        raise ValueError(f'El registro contiene MARCXML inválido: {exc}') from exc

    registros = [raiz] if raiz.tag.rsplit('}', 1)[-1] == 'record' else [
        elemento for elemento in raiz.iter()
        if elemento.tag.rsplit('}', 1)[-1] == 'record'
    ]
    if not registros:
        raise ValueError('El MARCXML no contiene un elemento record.')

    campos = []
    for elemento in registros[0]:
        nombre = elemento.tag.rsplit('}', 1)[-1]
        if nombre == 'leader':
            campos.append({
                'etiqueta': 'LDR', 'indicadores': '',
                'contenido': (elemento.text or '').strip(),
            })
        elif nombre == 'controlfield':
            campos.append({
                'etiqueta': elemento.attrib.get('tag', ''),
                'indicadores': '',
                'contenido': (elemento.text or '').strip(),
            })
        elif nombre == 'datafield':
            subcampos = []
            for subcampo in elemento:
                if subcampo.tag.rsplit('}', 1)[-1] == 'subfield':
                    codigo = subcampo.attrib.get('code', '')
                    subcampos.append(f'${codigo} {subcampo.text or ""}'.strip())
            campos.append({
                'etiqueta': elemento.attrib.get('tag', ''),
                'indicadores': ''.join(
                    elemento.attrib.get(clave, ' ').strip() or '#'
                    for clave in ('ind1', 'ind2')
                ),
                'contenido': '  |  '.join(subcampos),
            })
    if not campos:
        raise ValueError('El registro MARCXML no contiene campos para mostrar.')
    return campos


def campos_desde_iso2709(contenido):
    if not contenido:
        raise ValueError('El registro no contiene MARC ISO2709 para recuperación.')
    try:
        registros = iter(MARCReader(BytesIO(contenido), to_unicode=True))
        registro = next(registros, None)
    except Exception as exc:
        raise ValueError(f'No se pudo leer el registro MARC ISO2709: {exc}') from exc
    if registro is None:
        raise ValueError('El registro MARC ISO2709 está vacío o no es válido.')

    campos = [{
        'etiqueta': 'LDR', 'indicadores': '',
        'contenido': str(registro.leader).strip(),
    }]
    for campo in registro.fields:
        if campo.is_control_field():
            campos.append({
                'etiqueta': campo.tag, 'indicadores': '',
                'contenido': campo.data or '',
            })
        else:
            subcampos = []
            for subcampo in campo.subfields:
                codigo = getattr(subcampo, 'code', None)
                valor = getattr(subcampo, 'value', None)
                if codigo is not None:
                    subcampos.append(f'${codigo} {valor or ""}'.strip())
            campos.append({
                'etiqueta': campo.tag,
                'indicadores': ''.join(
                    indicador.strip() or '#' for indicador in campo.indicators
                ),
                'contenido': '  |  '.join(subcampos),
            })
    return campos


def campos_para_revision(registro):
    try:
        return campos_desde_marcxml(registro.get('marca_marcxml')), ''
    except ValueError as error_xml:
        # ISO2709 permite revisar el registro aunque la copia MARCXML esté dañada.
        try:
            campos = campos_desde_iso2709(registro.get('marca_iso2709'))
        except ValueError as error_iso:
            raise ValueError(
                f'{error_xml} Tampoco se pudo recuperar el registro desde '
                f'ISO2709: {error_iso}'
            ) from error_iso
        return campos, (
            'Aviso: no se pudo leer el MARCXML almacenado. Los campos se '
            'muestran recuperados desde la copia ISO2709.'
        )


def ejemplares_desde_registro_marc(registro):
    try:
        record = record_desde_iso2709(registro.get('marca_iso2709'))
    except ValueError as error_iso:
        try:
            registros = parse_xml_to_array(
                StringIO(registro.get('marca_marcxml') or ''), strict=True,
            )
        except (ValueError, TypeError, UnicodeError, SAXException) as error_xml:
            raise ValueError(
                f'No se pudieron leer ejemplares desde MARCXML ni ISO2709: '
                f'{error_xml}; {error_iso}'
            ) from error_xml
        if len(registros) != 1:
            raise ValueError(
                'El MARCXML no contiene exactamente un registro para recuperar ejemplares.'
            )
        record = registros[0]

    def primer_subcampo(campo, codigo):
        valores = campo.get_subfields(codigo)
        return valores[0] if valores else None

    resultado = []
    for campo in record.get_fields('952'):
        homebranch = primer_subcampo(campo, 'a')
        holdingbranch = primer_subcampo(campo, 'b')
        sucursal = ' / '.join(
            valor for valor in (homebranch, holdingbranch) if valor
        )
        resultado.append({
            'num_adqui': primer_subcampo(campo, 'p') or '—',
            'biblioteca': '—',
            'branch_koha': sucursal or '—',
            'volumen': primer_subcampo(campo, 'h') or primer_subcampo(campo, 'c') or '—',
            'ejemplar': primer_subcampo(campo, 't') or '—',
            'tomo': '—',
            'accesible': primer_subcampo(campo, 'x') or primer_subcampo(campo, 'z') or '—',
            'fecha_ingreso': primer_subcampo(campo, 'd') or '—',
            'signatura': primer_subcampo(campo, 'o') or '—',
        })
    return resultado


def record_desde_iso2709(contenido):
    if not contenido:
        raise ValueError('El registro no contiene MARC ISO2709 para editar.')
    try:
        record = next(iter(MARCReader(BytesIO(contenido), to_unicode=True)), None)
    except Exception as exc:
        raise ValueError(f'No se pudo leer el registro MARC: {exc}') from exc
    if record is None:
        raise ValueError('El registro ISO2709 está vacío o no es válido.')
    return record


def record_para_edicion(registro):
    if registro.get('borrador_marc'):
        return next(iter(JSONReader(StringIO(registro['borrador_marc'])))), 'Borrador recuperado de la migración. Corrige los campos indicados.'
    errores = []
    try:
        iso = record_desde_iso2709(registro.get('marca_iso2709'))
        if registro.get('marca_marcxml'):
            try:
                copias = parse_xml_to_array(StringIO(registro['marca_marcxml']), strict=True)
                if len(copias) == 1 and copias[0].as_dict() != iso.as_dict():
                    return copias[0], 'Las copias difieren. Estás editando el MARCXML mostrado; comprueba sus campos contra el origen.'
            except (SAXException, ValueError, TypeError, UnicodeError):
                pass
        return iso, ''
    except ValueError as exc:
        errores.append(f'ISO2709: {exc}')

    try:
        registros = parse_xml_to_array(
            StringIO(registro.get('marca_marcxml') or ''), strict=True,
        )
        if len(registros) != 1:
            raise ValueError('El MARCXML no contiene exactamente un registro.')
        return registros[0], (
            'Aviso: la copia ISO2709 no se pudo leer; los campos se '
            'recuperaron desde MARCXML.'
        )
    except (ValueError, TypeError, UnicodeError, SAXException) as exc:
        errores.append(f'MARCXML: {exc}')

    record = Record(force_utf8=True)
    record.leader = '00000nam a2200000 i 4500'
    return record, (
        'Aviso: no se pudo recuperar ninguna copia del registro. Se abrió '
        'una ficha vacía para capturar todos los campos MARC obligatorios. '
        + ' '.join(errores)
    )


def texto_subcampos(campo):
    def escapar(valor):
        return valor.replace('\\', '\\\\').replace('|', '\\|')
    return ' | '.join(f'${sf.code} {escapar(sf.value)}' for sf in campo.subfields)


def parsear_subcampos(texto):
    partes = []
    actual = []
    chars = iter(texto)
    for char in chars:
        if char == '\\':
            siguiente = next(chars, '')
            if siguiente not in ('|', '\\'):
                actual.append('\\')
            actual.append(siguiente)
        elif char == '|':
            partes.append(''.join(actual))
            actual = []
        else:
            actual.append(char)
    partes.append(''.join(actual))
    resultado = []
    for parte in partes:
        coincidencia = re.fullmatch(r'\$([a-z0-9])\s+(.+)', parte.strip(), re.DOTALL)
        if not coincidencia:
            raise ValueError('Cada subcampo requiere código y contenido: «$a valor | $b valor».')
        resultado.append(Subfield(coincidencia[1], coincidencia[2]))
    return resultado


def campo_desde_editor(tag, indicadores, contenido):
    tag = tag.strip()
    if not re.fullmatch(r'[0-9]{3}', tag):
        raise ValueError('La etiqueta MARC debe contener tres dígitos.')
    if tag < '010':
        if not contenido.strip():
            raise ValueError(f'El campo de control {tag} requiere contenido.')
        if indicadores.strip():
            raise ValueError('Los campos de control no llevan indicadores.')
        return Field(tag=tag, data=contenido)
    indicadores = indicadores.replace('#', ' ')
    if len(indicadores) != 2 or any(ord(char) < 32 for char in indicadores):
        raise ValueError('Un campo de datos requiere exactamente dos indicadores.')
    return Field(
        tag=tag, indicators=list(indicadores),
        subfields=parsear_subcampos(contenido),
    )


def serializar_registro(record, perfil=None):
    errores = [i.texto() for i in validar_ficha(record, perfil) if i.gravedad == ERROR_MARC]
    if errores:
        raise ValueError('\n'.join(errores))
    xml = MarcConverter().record_a_marcxml(record)
    iso2709 = record.as_marc()
    MySQLWriter._validar_registro_propuesto(xml, iso2709, perfil)
    return xml, iso2709


class PanelLotes(ttk.Frame):
    def __init__(self, parent, listar, politica, iniciar, exportar, revisar,
                 proponer, listar_propuestas, resolver_propuesta,
                 listar_observaciones, registrar_observacion,
                 conexiones, detener, reprocesar, obtener, publicar, framework=None):
        super().__init__(parent, padding=24, style='Panel.TFrame')
        self.framework = framework or dict
        self.listar = listar
        self.obtener = obtener
        self.publicar = publicar
        self.politica = politica
        self.iniciar = iniciar
        self.exportar = exportar
        self.revisar = revisar
        self.proponer = proponer
        self.listar_propuestas = listar_propuestas
        self.resolver_propuesta = resolver_propuesta
        self.listar_observaciones = listar_observaciones
        self.registrar_observacion = registrar_observacion
        self.conexiones = conexiones
        self.detener = detener
        self.reprocesar = reprocesar
        self.seleccionado = None
        self.lotes = []
        self.demo = tk.BooleanVar(value=False)
        self.filtro = tk.StringVar(value='Todos')
        self.filtro_periodo = tk.StringVar(value='Todo el historial')
        self.orden = tk.StringVar(value='Más recientes')
        self.tipo_grafico = tk.StringVar(value='Estado de los lotes')
        self.consulta = tk.StringVar()
        self._estilos()
        self._crear()
        self.actualizar()

    def _estilos(self):
        estilo = ttk.Style(self)
        estilo.configure('Panel.TFrame', background=FONDO)
        estilo.configure('Tarjeta.TFrame', background=SUPERFICIE)
        estilo.configure('Panel.TLabel', background=FONDO, foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('Titulo.Panel.TLabel', background=FONDO, foreground=TEXTO,
                         font=(FUENTE, TAM_TITULO_PAGINA, 'bold'))
        estilo.configure('Tarjeta.TLabel', background=SUPERFICIE, foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('CardBody.TLabel', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, TAM_CUERPO))
        estilo.configure('CardHint.TLabel', background=SUPERFICIE, foreground=TEXTO_MUTADO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('CardTitle.TLabel', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, TAM_TARJETA_TITULO, 'bold'))
        estilo.configure('CardMetric.TLabel', background=SUPERFICIE, foreground=PRIMARIO,
                         font=(FUENTE, 11, 'bold'))
        estilo.configure('Nombre.TLabel', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, 15, 'bold'))
        estilo.configure('Numero.TLabel', background=SUPERFICIE, foreground=PRIMARIO,
                         font=(FUENTE, TAM_METRICA_VALOR, 'bold'))
        estilo.configure('Lotes.Treeview', rowheight=26, font=(FUENTE, TAM_TABLA_CUERPO),
                         background=SUPERFICIE, fieldbackground=SUPERFICIE, foreground=TEXTO,
                         bordercolor=BORDE, lightcolor=BORDE, darkcolor=BORDE)
        estilo.configure('Lotes.Treeview.Heading', background=SUPERFICIE_ALT,
                         foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_TABLA_ENCABEZADO, 'bold'), padding=(10, 7))
        estilo.map('Lotes.Treeview', background=[('selected', PRIMARIO_SUAVE)],
                   foreground=[('selected', PRIMARIO)])
        estilo.configure('Revision.TNotebook', background=SUPERFICIE, borderwidth=0)
        estilo.configure(
            'Revision.TNotebook.Tab', background=SUPERFICIE_ALT,
            foreground=TEXTO_SECUNDARIO, padding=(16, 10), borderwidth=0,
            font=(FUENTE, TAM_BOTON, 'bold'),
        )
        estilo.map(
            'Revision.TNotebook.Tab',
            background=[('selected', SUPERFICIE), ('active', PRIMARIO_SUAVE)],
            foreground=[('selected', PRIMARIO), ('active', TEXTO)],
        )
        estilo.configure(
            'RevisionAction.TButton', background=SUPERFICIE,
            foreground=TEXTO, borderwidth=0, padding=(6, 5),
            font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'),
        )
        estilo.map(
            'RevisionAction.TButton',
            background=[('active', PRIMARIO_SUAVE), ('disabled', SUPERFICIE)],
            foreground=[('active', PRIMARIO), ('disabled', TEXTO_MUTADO)],
        )
        estilo.configure('Lotes.Horizontal.TProgressbar', background=PRIMARIO,
                         troughcolor=BORDE, thickness=8)
        estilo.configure('Estado.TLabel', background=SUPERFICIE, foreground=PRIMARIO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'))
        estilo.configure('Hero.TFrame', background=SUPERFICIE)
        estilo.configure('HeroTitle.TLabel', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, TAM_TARJETA_TITULO, 'bold'))
        estilo.configure('HeroHint.TLabel', background=SUPERFICIE, foreground=TEXTO_MUTADO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('HeroQuiet.TButton', background=SUPERFICIE_ALT,
                         foreground=TEXTO_SECUNDARIO, borderwidth=0, padding=(8, 6))
        estilo.map('HeroQuiet.TButton',
                   background=[('active', SUPERFICIE_ALT), ('pressed', PRIMARIO_SUAVE)])

    def _crear(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # ---------- Cabecera ----------
        cabecera = tarjeta(self, padding=(ESPACIO_M, ESPACIO_M))
        cabecera.grid(row=0, column=0, sticky='ew', pady=(0, ESPACIO_S))
        self._cabecera_panel = cabecera
        cabecera.columnconfigure(1, weight=1)
        ttk.Label(
            cabecera, text='Panel de migraciones', style='Titulo.Panel.TLabel',
        ).grid(row=0, column=0, sticky='w')
        ttk.Label(
            cabecera, text='Estado general de los lotes y acciones rápidas.',
            style='CardHint.TLabel',
        ).grid(row=1, column=0, sticky='w', pady=(ESPACIO_XS, 0))
        acciones_cabecera = ttk.Frame(cabecera, style='Tarjeta.TFrame')
        acciones_cabecera.grid(row=0, column=1, rowspan=2, sticky='e')
        ttk.Button(
            acciones_cabecera, text='Actualizar', style='Quiet.TButton',
            command=self.actualizar,
        ).pack(side='left', padx=(0, ESPACIO_S))
        self.btn_exportar_historial = ttk.Button(
            acciones_cabecera, text='Exportar CSV',
            style='Secondary.TButton', command=self._exportar_historial,
        )
        self.btn_exportar_historial.pack(side='left', padx=(0, ESPACIO_S))
        self.btn_nueva_migracion = ttk.Button(
            acciones_cabecera, text='Nueva migración', style='Primary.TButton',
            command=self.conexiones,
        )
        self.btn_nueva_migracion.pack(side='left')

        self.aviso = ttk.Label(
            self, text='Selecciona un lote para ver su estado y las acciones disponibles.',
            style='Panel.TLabel',
        )
        self.aviso.grid(row=1, column=0, sticky='ew', pady=(0, ESPACIO_M))

        # ---------- Navegación de contenido ----------
        self._vistas_contenido = {}
        self._vistas_botones = {}
        navegacion = tk.Frame(self, bg=FONDO)
        navegacion.grid(row=2, column=0, sticky='ew', pady=(0, ESPACIO_S))
        self._navegacion_panel = navegacion
        for clave, etiqueta, icono in (
            ('resumen', 'Resumen', 'chart'),
            ('historial', 'Historial', 'file'),
            ('analisis', 'Análisis', 'activity'),
        ):
            elemento = tk.Frame(navegacion, bg=FONDO)
            elemento.pack(side='left', padx=(0, ESPACIO_S))
            indicador = tk.Frame(elemento, height=3, bg=FONDO)
            indicador.pack(side='bottom', fill='x')
            simbolo = crear_icono(
                elemento, icono, color=TEXTO_SECUNDARIO,
                size=17, fondo=FONDO,
            )
            simbolo.pack(side='left', padx=(ESPACIO_S, 4), pady=ESPACIO_XS)
            boton = tk.Button(
                elemento, text=etiqueta,
                command=lambda nombre=clave: self._mostrar_vista(nombre),
                anchor='w', padx=6, pady=9, bd=0, relief='flat',
                cursor='hand2', font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'),
                bg=FONDO, fg=TEXTO_SECUNDARIO,
                activebackground=SUPERFICIE_ALT,
                activeforeground=PRIMARIO, highlightthickness=0,
            )
            boton.pack(side='left', padx=(0, ESPACIO_S))
            simbolo.bind('<Button-1>', lambda _evento, control=boton: control.invoke())
            self._vistas_contenido[clave] = None
            self._vistas_botones[clave] = (boton, indicador, simbolo)

        area_vistas = ttk.Frame(self, style='Panel.TFrame')
        area_vistas.grid(row=3, column=0, sticky='nsew')
        area_vistas.columnconfigure(0, weight=1)
        area_vistas.rowconfigure(0, weight=1)
        self.resumen = ttk.Frame(area_vistas, style='Panel.TFrame')
        self.historial_tab = ttk.Frame(area_vistas, style='Panel.TFrame')
        self.analisis_tab = ttk.Frame(area_vistas, style='Panel.TFrame')
        self._vistas_contenido.update({
            'resumen': self.resumen,
            'historial': self.historial_tab,
            'analisis': self.analisis_tab,
        })
        for vista in self._vistas_contenido.values():
            vista.grid(row=0, column=0, sticky='nsew')
        self._mostrar_vista('historial')

        # -------- Pestaña: Resumen --------
        self.resumen.columnconfigure(0, weight=1)
        self.resumen.rowconfigure(2, weight=1)
        self.metricas = {}
        metricas_frame = ttk.Frame(self.resumen, style='Panel.TFrame')
        metricas_frame.grid(row=0, column=0, sticky='ew', pady=(0, ESPACIO_M))
        for indice in range(4):
            metricas_frame.columnconfigure(indice, weight=1, uniform='metricas')
        for indice, (clave, titulo) in enumerate((
            ('total_lotes', 'LOTES REGISTRADOS'),
            ('fichas_correctas', 'FICHAS CONVERTIDAS'),
            ('ejemplares', 'EJEMPLARES'),
            ('requieren_revision', 'REQUIEREN REVISIÓN'),
        )):
            tarjeta_m = tarjeta(metricas_frame, padding=(ESPACIO_M, ESPACIO_M))
            tarjeta_m.grid(
                row=0, column=indice, sticky='ew',
                padx=(0 if indice == 0 else ESPACIO_S, ESPACIO_S),
            )
            ttk.Label(tarjeta_m, text=titulo, style='Tarjeta.TLabel').pack(anchor='w')
            valor = ttk.Label(tarjeta_m, text='0', style='Numero.TLabel')
            valor.pack(anchor='w', pady=(ESPACIO_XS, 0))
            self.metricas[clave] = valor

        self.lbl_lectura_rapida = ttk.Label(
            self.resumen, style='Panel.TLabel', wraplength=1400, justify='left',
        )
        self.lbl_lectura_rapida.grid(
            row=1, column=0, sticky='ew', pady=(0, ESPACIO_M),
        )

        recientes = seccion_tarjeta(self.resumen, 'Actividad reciente')
        recientes.grid(row=2, column=0, sticky='nsew', pady=(0, ESPACIO_M))
        recientes.columnconfigure(0, weight=1)
        recientes.rowconfigure(0, weight=1)
        self.lista_recientes = ttk.Treeview(
            recientes, columns=('estado', 'avance', 'fecha'),
            show='tree headings', height=8, style='Lotes.Treeview',
        )
        self.lista_recientes.heading('#0', text='Lote / origen')
        self.lista_recientes.heading('estado', text='Estado')
        self.lista_recientes.heading('avance', text='Avance')
        self.lista_recientes.heading('fecha', text='Última actualización')
        self.lista_recientes.column('#0', width=460, minwidth=180, stretch=True)
        self.lista_recientes.column('estado', width=145, anchor='center')
        self.lista_recientes.column('avance', width=105, anchor='center')
        self.lista_recientes.column('fecha', width=190, anchor='center')
        self.lista_recientes.grid(row=0, column=0, sticky='nsew')
        recientes_scroll = ttk.Scrollbar(
            recientes, orient='vertical', command=self.lista_recientes.yview,
        )
        recientes_scroll.grid(row=0, column=1, sticky='ns')
        self.lista_recientes.configure(yscrollcommand=recientes_scroll.set)
        self.lista_recientes.bind('<<TreeviewSelect>>', self._seleccionar_reciente)

        # -------- Pestaña: Análisis --------
        self.analisis_tab.columnconfigure(0, weight=1)
        self.analisis_tab.rowconfigure(1, weight=1)
        barra_analisis = ttk.Frame(self.analisis_tab, style='Panel.TFrame')
        barra_analisis.grid(row=0, column=0, sticky='ew', pady=(0, ESPACIO_M))
        ttk.Label(barra_analisis, text='Visualizar', style='Panel.TLabel').pack(side='left', padx=(ESPACIO_XS, ESPACIO_S))
        selector_grafico = ttk.Combobox(
            barra_analisis, textvariable=self.tipo_grafico,
            values=('Estado de los lotes', 'Resultado de fichas',
                    'Fichas convertidas por lote', 'Ejemplares por lote'),
            state='readonly', width=28,
        )
        selector_grafico.pack(side='left')
        selector_grafico.bind('<<ComboboxSelected>>', lambda _evento: self._pintar_grafico())
        tarjeta_grafico = tarjeta(
            self.analisis_tab, padding=(ESPACIO_M, ESPACIO_M),
        )
        tarjeta_grafico.grid(row=1, column=0, sticky='nsew')
        tarjeta_grafico.columnconfigure(0, weight=1)
        tarjeta_grafico.rowconfigure(1, weight=1)
        self.lbl_titulo_grafico = ttk.Label(
            tarjeta_grafico, text='', style='Nombre.TLabel',
        )
        self.lbl_titulo_grafico.grid(row=0, column=0, sticky='w', pady=(0, ESPACIO_S))
        self.grafico = tk.Canvas(
            tarjeta_grafico, background=SUPERFICIE,
            highlightthickness=0, borderwidth=0,
        )
        self.grafico.grid(row=1, column=0, sticky='nsew')
        self.grafico.bind('<Configure>', lambda _evento: self._pintar_grafico())

        # -------- Pestaña: Historial --------
        cuerpo = ttk.Frame(self.historial_tab, style='Panel.TFrame')
        cuerpo.pack(fill='both', expand=True, pady=(0, ESPACIO_S))
        self._historial_contenedor = cuerpo
        cuerpo.columnconfigure(0, weight=1)
        cuerpo.rowconfigure(0, weight=1)
        listado = tarjeta(cuerpo, padding=ESPACIO_M)
        detalle = tarjeta(cuerpo, padding=ESPACIO_M)
        listado.grid(row=0, column=0, sticky='nsew')
        detalle.grid(row=0, column=0, sticky='nsew')
        self._historial_paginas = {
            'lista': listado,
            'detalle': detalle,
        }
        listado.columnconfigure(0, weight=1)
        listado.rowconfigure(1, weight=1)
        filtros = ttk.Frame(listado, style='Tarjeta.TFrame')
        filtros.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, ESPACIO_M))
        filtros.columnconfigure(5, weight=1)
        ttk.Label(filtros, text='Estado', style='Tarjeta.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, ESPACIO_XS),
        )
        combo = ttk.Combobox(
            filtros, textvariable=self.filtro,
            values=['Todos'] + list(ESTADOS.values()), state='readonly', width=12,
        )
        combo.grid(row=0, column=1, sticky='w', padx=(0, ESPACIO_S))
        combo.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        ttk.Label(filtros, text='Periodo', style='Tarjeta.TLabel').grid(
            row=0, column=2, sticky='w', padx=(0, ESPACIO_XS),
        )
        combo_periodo = ttk.Combobox(
            filtros, textvariable=self.filtro_periodo,
            values=('Todo el historial', 'Últimos 7 días',
                    'Últimos 30 días', 'Este año'),
            state='readonly', width=16,
        )
        combo_periodo.grid(row=0, column=3, sticky='w', padx=(0, ESPACIO_S))
        combo_periodo.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        control_detalle = ttk.Frame(filtros, style='Tarjeta.TFrame')
        control_detalle.grid(row=0, column=8, sticky='e')
        crear_icono(
            control_detalle, 'file', color=PRIMARIO, size=16, fondo=SUPERFICIE,
        ).pack(side='left', padx=(0, ESPACIO_XS))
        self.btn_abrir_detalle = ttk.Button(
            control_detalle, text='Ver detalle',
            style='Primary.TButton', command=self._abrir_detalle,
        )
        self.btn_abrir_detalle.pack(side='left')
        control_revision = ttk.Frame(filtros, style='Tarjeta.TFrame')
        control_revision.grid(row=0, column=9, sticky='e', padx=(ESPACIO_S, 0))
        crear_icono(
            control_revision, 'search', color=PRIMARIO, size=16, fondo=SUPERFICIE,
        ).pack(side='left', padx=(0, ESPACIO_XS))
        self.btn_revisar = ttk.Button(
            control_revision, text='Revisar fichas',
            style='Secondary.TButton', command=self._revisar,
        )
        self.btn_revisar.pack(side='left')
        ttk.Label(filtros, text='Buscar', style='Tarjeta.TLabel').grid(
            row=0, column=4, sticky='w', padx=(0, ESPACIO_XS),
        )
        entrada = ttk.Entry(filtros, textvariable=self.consulta, width=12)
        entrada.grid(row=0, column=5, sticky='ew', padx=(0, ESPACIO_S))
        ttk.Label(filtros, text='Ordenar', style='Tarjeta.TLabel').grid(
            row=0, column=6, sticky='w', padx=(0, ESPACIO_XS),
        )
        combo_orden = ttk.Combobox(
            filtros, textvariable=self.orden,
            values=('Más recientes', 'Más antiguos', 'Más errores',
                    'Mayor avance'),
            state='readonly', width=14,
        )
        combo_orden.grid(row=0, column=7, sticky='w')
        combo_orden.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        self.consulta.trace_add('write', lambda *_: self._pintar_tabla())
        self.tabla = ttk.Treeview(
            listado, columns=('lote', 'estado', 'avance', 'total'),
            show='headings', selectmode='browse', style='Lotes.Treeview',
            height=14,
        )
        for columna, titulo, ancho, minimo in (
            ('lote', 'Lote / origen', 560, 360),
            ('estado', 'Estado', 170, 130),
            ('avance', 'Avance', 120, 100),
            ('total', 'Recibidos', 150, 120),
        ):
            self.tabla.heading(columna, text=titulo)
            self.tabla.column(
                columna, width=ancho, minwidth=minimo, stretch=columna == 'lote',
                anchor='w' if columna == 'lote' else 'center',
            )
        self.tabla.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(listado, orient='vertical', command=self.tabla.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        self.tabla.configure(yscrollcommand=scroll.set)
        for estado, config in COLORES_ESTADO_LOTE.items():
            self.tabla.tag_configure(estado, foreground=config['texto'])
        self.tabla.bind('<<TreeviewSelect>>', self._seleccionar)
        self.tabla.bind('<Double-1>', lambda _evento: self._abrir_detalle())
        self.tabla.bind('<Return>', lambda _evento: self._abrir_detalle())
        self.sin_lotes = ttk.Label(listado, style='Tarjeta.TLabel', wraplength=900)
        self.sin_lotes.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(ESPACIO_M, 0))

        # -------- Detalle del lote: vistas internas sin ventanas emergentes --------
        detalle.columnconfigure(0, weight=1)
        detalle.rowconfigure(0, weight=1)
        marco_detalle = ttk.Frame(detalle, style='Tarjeta.TFrame')
        marco_detalle.grid(row=0, column=0, sticky='nsew')
        marco_detalle.columnconfigure(0, weight=1)
        marco_detalle.rowconfigure(1, weight=1)
        self._detalle_vistas = {}
        self._detalle_botones = {}
        navegacion_detalle = tk.Frame(marco_detalle, bg=SUPERFICIE)
        navegacion_detalle.grid(row=0, column=0, sticky='ew', pady=(0, ESPACIO_S))
        self.btn_volver_historial = ttk.Button(
            navegacion_detalle, text='← Todos los lotes',
            command=self._volver_a_historial, style='Secondary.TButton',
        )
        self.btn_volver_historial.pack(side='left', padx=(0, ESPACIO_M))
        area_detalle = ttk.Frame(marco_detalle, style='Tarjeta.TFrame')
        area_detalle.grid(row=1, column=0, sticky='nsew')
        area_detalle.columnconfigure(0, weight=1)
        area_detalle.rowconfigure(0, weight=1)
        self.detalle_resumen = ttk.Frame(
            area_detalle, style='Tarjeta.TFrame', padding=ESPACIO_M,
        )
        self.detalle_incidencias = ttk.Frame(
            area_detalle, style='Tarjeta.TFrame', padding=ESPACIO_M,
        )
        self.detalle_actividad = ttk.Frame(
            area_detalle, style='Tarjeta.TFrame', padding=ESPACIO_M,
        )
        self._detalle_vistas.update({
            'resumen': self.detalle_resumen,
            'incidencias': self.detalle_incidencias,
            'actividad': self.detalle_actividad,
        })
        for clave, etiqueta in (
            ('resumen', 'Resumen'),
            ('incidencias', 'Incidencias'),
            ('actividad', 'Actividad'),
        ):
            boton = tk.Button(
                navegacion_detalle, text=etiqueta,
                command=lambda nombre=clave: self._mostrar_detalle(nombre),
                anchor='w', padx=8, pady=6, bd=0, relief='flat',
                cursor='hand2', font=(FUENTE, 9, 'bold'),
                bg=SUPERFICIE, fg=TEXTO_SECUNDARIO,
                activebackground=SUPERFICIE_ALT,
                activeforeground=PRIMARIO, highlightthickness=0,
            )
            boton.pack(side='left', padx=(0, ESPACIO_XS))
            self._detalle_botones[clave] = boton
        for vista in self._detalle_vistas.values():
            vista.grid(row=0, column=0, sticky='nsew')
        self._mostrar_detalle('resumen')
        self.detalle_resumen.columnconfigure(0, weight=2, uniform='detalle_lote')
        self.detalle_resumen.columnconfigure(1, weight=1, uniform='detalle_lote')
        self.detalle_resumen.rowconfigure(0, weight=1)
        resumen_lote = seccion_tarjeta(self.detalle_resumen, 'Estado y avance')
        resumen_lote.grid(row=0, column=0, sticky='nsew', padx=(0, ESPACIO_S))
        resumen_lote.columnconfigure(0, weight=1)
        panel_acciones = seccion_tarjeta(self.detalle_resumen, 'Siguiente paso')
        panel_acciones.grid(row=0, column=1, sticky='nsew', padx=(ESPACIO_S, 0))
        panel_acciones.columnconfigure(0, weight=1)
        for marco, titulo, clave, vacio in (
            (self.detalle_incidencias, 'Incidencias del lote', 'incidencias',
             'No hay incidencias registradas para este lote.'),
            (self.detalle_actividad, 'Actividad del lote', 'actividad',
             'Aún no hay actividad registrada.'),
        ):
            marco.columnconfigure(0, weight=1)
            marco.rowconfigure(1, weight=1)
            ttk.Label(
                marco, text=titulo, style='Nombre.TLabel',
            ).grid(row=0, column=0, sticky='w', pady=(0, ESPACIO_M))
            texto = tk.Text(
                marco, wrap='word', font=(FUENTE, TAM_CUERPO),
                background=SUPERFICIE_ALT, foreground=TEXTO,
                relief='flat', padx=ESPACIO_M, pady=ESPACIO_M,
                highlightthickness=1, highlightbackground=BORDE,
                state='disabled',
            )
            texto.grid(row=1, column=0, sticky='nsew')
            scroll_texto = ttk.Scrollbar(marco, command=texto.yview)
            scroll_texto.grid(row=1, column=1, sticky='ns')
            texto.configure(yscrollcommand=scroll_texto.set)
            texto.mensaje_vacio = vacio
            setattr(self, f'txt_{clave}_lote', texto)

        self.identificador = ttk.Label(resumen_lote, style='Tarjeta.TLabel')
        self.identificador.grid(row=0, column=0, sticky='w', pady=(0, ESPACIO_XS))
        self.nombre = ttk.Label(resumen_lote, style='Nombre.TLabel')
        self.nombre.grid(row=1, column=0, sticky='ew', pady=(0, ESPACIO_M))
        self.estado = ttk.Label(resumen_lote, style='Estado.TLabel')
        self.estado.grid(row=2, column=0, sticky='w', pady=(0, ESPACIO_S))
        self.etapa = ttk.Label(resumen_lote, style='Tarjeta.TLabel')
        self.etapa.grid(row=3, column=0, sticky='ew', pady=(0, ESPACIO_M))
        self.barra = ttk.Progressbar(resumen_lote, maximum=100, style='Lotes.Horizontal.TProgressbar')
        self.barra.grid(row=4, column=0, sticky='ew', pady=(0, ESPACIO_S))
        self.conteos = ttk.Label(resumen_lote, style='Tarjeta.TLabel')
        self.conteos.grid(row=5, column=0, sticky='ew', pady=(0, ESPACIO_M))
        metricas = ttk.Frame(resumen_lote, style='Tarjeta.TFrame')
        metricas.grid(row=6, column=0, sticky='ew', pady=(0, ESPACIO_S))
        metricas.columnconfigure((0, 1), weight=1, uniform='metricas')
        self.metricas_lote = {}
        for indice, (campo, etiqueta) in enumerate((
            ('correctos', 'Convertidas'), ('omitidos', 'Ya existentes'),
            ('errores', 'Rechazadas'), ('pendientes', 'Pendientes'),
        )):
            tarjeta_m = tarjeta(metricas, padding=(ESPACIO_S, ESPACIO_S))
            tarjeta_m.grid(
                row=indice // 2, column=indice % 2, sticky='ew',
                padx=(0, ESPACIO_S), pady=(0, ESPACIO_XS),
            )
            ttk.Label(tarjeta_m, text=etiqueta, style='Tarjeta.TLabel').pack(
                side='left', anchor='w',
            )
            valor = ttk.Label(tarjeta_m, text='—', style='Numero.TLabel')
            valor.pack(side='right')
            self.metricas_lote[campo] = valor

        self.actualizado = ttk.Label(resumen_lote, style='Tarjeta.TLabel')
        self.actualizado.grid(row=7, column=0, sticky='ew', pady=(ESPACIO_S, 0))
        self.siguiente = ttk.Label(panel_acciones, style='Tarjeta.TLabel', wraplength=380)
        self.siguiente.grid(row=0, column=0, sticky='ew', pady=(0, ESPACIO_M))
        ttk.Label(
            panel_acciones, text='Acciones disponibles', style='Nombre.TLabel',
        ).grid(row=1, column=0, sticky='w', pady=(0, ESPACIO_S))
        acciones = ttk.Frame(panel_acciones, style='Tarjeta.TFrame')
        acciones.grid(row=2, column=0, sticky='ew')
        acciones.columnconfigure((0, 1), weight=1, uniform='acciones')
        self.btn_iniciar = ttk.Button(acciones, text='Iniciar migración', command=self._iniciar)
        self.btn_detener = ttk.Button(acciones, text='Detener migración', command=self._detener)
        self.btn_reprocesar = ttk.Button(acciones, text='Reprocesar pendientes', command=self._reprocesar)
        self.btn_exportar = ttk.Button(acciones, text='Exportar MARC21', command=self._exportar)
        self.btn_revisar_detalle = ttk.Button(acciones, text='Revisar fichas', command=self._revisar)
        self.btn_revisar_incidencias = ttk.Button(
            self.detalle_incidencias, text='Revisar fichas del lote', command=self._revisar,
        )
        self.btn_revisar_incidencias.grid(row=2, column=0, sticky='w', pady=ESPACIO_XS)
        self.aviso_destino_revision = ttk.Label(
            self.detalle_incidencias, style='Tarjeta.TLabel', wraplength=600,
        )
        self.aviso_destino_revision.grid(row=3, column=0, sticky='w')
        self.aviso_destino_revision.grid_remove()
        self.btn_incidencias = ttk.Button(acciones, text='Ver incidencias', command=self._incidencias)
        self.btn_resumen = ttk.Button(acciones, text='Guardar reporte', command=self._resumen)
        for indice, boton in enumerate((
            self.btn_iniciar, self.btn_detener, self.btn_reprocesar, self.btn_exportar,
            self.btn_incidencias, self.btn_revisar_detalle,
        )):
            boton.grid(
                row=indice // 2, column=indice % 2, sticky='ew',
                padx=(0, ESPACIO_S), pady=ESPACIO_XS,
            )
        self.btn_resumen.grid(row=3, column=0, columnspan=2, sticky='ew', padx=(0, ESPACIO_S), pady=ESPACIO_XS)
        def ajustar_wrap_resumen(evento):
            self.nombre.configure(wraplength=max(320, evento.width - 2 * ESPACIO_M))
            self.etapa.configure(wraplength=max(320, evento.width - 2 * ESPACIO_M))
            self.conteos.configure(wraplength=max(320, evento.width - 2 * ESPACIO_M))

        resumen_lote.bind('<Configure>', ajustar_wrap_resumen)
        panel_acciones.bind(
            '<Configure>',
            lambda evento: self.siguiente.configure(
                wraplength=max(240, evento.width - 2 * ESPACIO_M),
            ),
        )
        self._mostrar_pagina_historial('lista')

    def _mostrar_pagina_historial(self, pagina):
        if pagina not in self._historial_paginas:
            raise ValueError(f'Vista de historial no reconocida: {pagina}')
        self._historial_pagina_actual = pagina
        self._historial_paginas[pagina].tkraise()

    def _volver_a_historial(self):
        self._mostrar_pagina_historial('lista')

    def _mostrar_detalle(self, clave):
        if clave not in self._detalle_vistas:
            raise ValueError(f'Vista de detalle no reconocida: {clave}')
        self._detalle_actual = clave
        self._detalle_vistas[clave].tkraise()
        for nombre, boton in self._detalle_botones.items():
            seleccionada = nombre == clave
            boton.configure(
                bg=SUPERFICIE if seleccionada else SUPERFICIE_ALT,
                fg=PRIMARIO if seleccionada else TEXTO_SECUNDARIO,
                font=(FUENTE, 9, 'bold' if seleccionada else 'normal'),
            )

    def _mostrar_vista(self, clave):
        if clave not in self._vistas_contenido:
            raise ValueError(f'Vista de panel no reconocida: {clave}')
        self._vista_actual = clave
        self._vistas_contenido[clave].tkraise()
        for nombre, (boton, indicador, simbolo) in self._vistas_botones.items():
            seleccionada = nombre == clave
            fondo = SUPERFICIE if seleccionada else FONDO
            color = PRIMARIO if seleccionada else TEXTO_SECUNDARIO
            boton.configure(
                bg=fondo, fg=color,
                font=(FUENTE, TAM_CAMPO_ETIQUETA,
                      'bold' if seleccionada else 'normal'),
            )
            boton.master.configure(bg=fondo)
            indicador.configure(bg=PRIMARIO if seleccionada else FONDO)
            colorear_icono(simbolo, color, fondo)

    def _cambiar_modo(self):
        self.seleccionado = None
        self._mostrar_pagina_historial('lista')
        self.actualizar()

    def actualizar(self, seleccionar=None):
        self.lotes = lotes_de_ejemplo() if self.demo.get() else self.listar()
        self.aviso.config(text='DEMOSTRACIÓN: datos de ejemplo. No se ejecutan ni exportan migraciones reales.' if self.demo.get() else 'Historial de la aplicación. El avance se actualiza durante la migración.')
        resumen = resumir_lotes(self.lotes)
        for clave, etiqueta in self.metricas.items():
            etiqueta.config(text=f'{resumen[clave]:,}')
        self.resumen_estadistico = resumen
        self.lbl_lectura_rapida.config(text=self._texto_lectura_rapida(resumen))
        self._pintar_recientes()
        self.btn_exportar_historial.configure(
            state='normal' if (
                not self.demo.get() and self.lotes
                and self.politica(None, False).get('exportar_historial')
            ) else 'disabled',
        )
        self.btn_nueva_migracion.configure(
            state='normal' if (
                not self.demo.get()
                and self.politica(None, False).get('nueva_migracion', False)
            ) else 'disabled',
        )
        self._pintar_grafico()
        if seleccionar and not self.demo.get():
            self.seleccionado = seleccionar
        if not any(lote.id == self.seleccionado for lote in self.lotes):
            preferido = next((lote for lote in self.lotes if lote.estado == 'en_proceso'), self.lotes[0] if self.lotes else None)
            self.seleccionado = preferido.id if preferido else None
        self._pintar_tabla()
        self._pintar_detalle()

    def _texto_lectura_rapida(self, resumen):
        activos = resumen['por_estado']['en_proceso']
        pendientes = sum(lote.pendientes for lote in self.lotes)
        errores = sum(lote.errores for lote in self.lotes)
        incidencias = sum(len(lote.incidencias) for lote in self.lotes)
        procesados = sum(lote.procesados for lote in self.lotes)
        correctos = resumen['fichas_correctas']
        tasa = f'{correctos / procesados * 100:.1f} %' if procesados else 'Sin ejecuciones'
        if not self.lotes:
            return 'Aún no hay migraciones registradas. Inicia una nueva migración para ver aquí el estado general.'
        return (
            f'{activos} migraciones activas · {pendientes:,} fichas pendientes · '
            f'{errores:,} fichas con error · {incidencias:,} incidencias registradas · '
            f'{tasa} de fichas convertidas sobre las procesadas.'
        )

    def _pintar_recientes(self):
        self.lista_recientes.delete(*self.lista_recientes.get_children())
        recientes = sorted(
            self.lotes,
            key=lambda lote: datetime.fromisoformat(lote.actualizado_en),
            reverse=True,
        )[:8]
        for lote in recientes:
            self.lista_recientes.insert(
                '', 'end', iid=lote.id,
                text=f'{lote.id} · {os.path.basename(lote.fuente)}',
                values=(
                    ESTADOS[lote.estado], f'{lote.progreso:g} %',
                    datetime.fromisoformat(lote.actualizado_en).strftime('%d/%m/%Y %H:%M'),
                ),
                tags=(lote.estado,),
            )

    def _seleccionar_reciente(self, _evento=None):
        seleccion = self.lista_recientes.selection()
        if not seleccion:
            return
        self.seleccionado = seleccion[0]
        self.filtro.set('Todos')
        self.filtro_periodo.set('Todo el historial')
        self.orden.set('Más recientes')
        self.consulta.set('')
        self._mostrar_vista('historial')
        self._pintar_tabla()
        self._pintar_detalle()
        self._mostrar_pagina_historial('detalle')

    def _pintar_grafico(self):
        if not hasattr(self, 'grafico'):
            return
        self.grafico.delete('all')
        tipo = self.tipo_grafico.get()
        titulo, etiquetas, valores, colores = datos_grafico(
            self.lotes, self.resumen_estadistico, tipo,
        )
        self.lbl_titulo_grafico.config(text=titulo)
        ancho = max(self.grafico.winfo_width(), 1)
        alto = max(self.grafico.winfo_height(), 1)
        if not etiquetas:
            self.grafico.create_text(
                ancho / 2, alto / 2, text='No hay datos para mostrar.',
                fill=TEXTO_SECUNDARIO, font=('Segoe UI', 11), anchor='center',
            )
            return
        maximo = max(valores, default=0) or 1
        margen_izquierdo = min(340, max(150, ancho * 0.36))
        ancho_barra = max(20, ancho - margen_izquierdo - 100)
        espacio = max(24, min(58, (alto - 32) / max(len(etiquetas), 1)))
        for indice, (etiqueta, valor, color) in enumerate(zip(etiquetas, valores, colores)):
            y = 16 + indice * espacio
            self.grafico.create_text(
                margen_izquierdo - 12, y + 9, text=etiqueta,
                fill=TEXTO_SECUNDARIO, font=('Segoe UI', 9), anchor='e',
                width=margen_izquierdo - 20,
            )
            self.grafico.create_rectangle(
                margen_izquierdo, y, margen_izquierdo + ancho_barra, y + 18,
                fill=SUPERFICIE_ALT, outline='',
            )
            if valor:
                self.grafico.create_rectangle(
                    margen_izquierdo, y,
                    margen_izquierdo + ancho_barra * valor / maximo, y + 18,
                    fill=color, outline='',
                )
            self.grafico.create_text(
                margen_izquierdo + ancho_barra + 10, y + 9,
                text=f'{valor:,}', fill=color, font=('Segoe UI', 9, 'bold'),
                anchor='w',
            )

    def _exportar_historial(self):
        if (self.demo.get() or not self.lotes
                or not self.politica(None, False).get('exportar_historial')):
            return
        ruta = filedialog.asksaveasfilename(
            parent=self, title='Exportar historial de migraciones',
            initialfile='historial_migraciones.csv', defaultextension='.csv',
            filetypes=[('Archivo CSV', '*.csv')],
        )
        if not ruta:
            return
        columnas = (
            'lote', 'fuente', 'usuario', 'fecha_ejecucion', 'lote_anterior',
            'estado', 'etapa', 'progreso_porcentaje',
            'recibidos', 'objetivo', 'procesados', 'pendientes', 'correctos',
            'omitidos', 'errores', 'ejemplares', 'servidor_destino',
            'base_datos', 'creado_en', 'actualizado_en', 'version_mapeo',
        )
        try:
            with open(ruta, 'w', encoding='utf-8-sig', newline='') as archivo:
                escritor = csv.DictWriter(archivo, fieldnames=columnas)
                escritor.writeheader()
                for lote in self.lotes:
                    escritor.writerow({
                        'lote': lote.id,
                        'fuente': os.path.basename(lote.fuente),
                        'usuario': _celda_csv(lote.usuario or 'Sin registrar'),
                        'fecha_ejecucion': lote.iniciado_en or '',
                        'lote_anterior': lote.lote_origen or '',
                        'estado': ESTADOS[lote.estado],
                        'etapa': ETAPAS[lote.etapa],
                        'progreso_porcentaje': lote.progreso,
                        'recibidos': lote.total_recibidos,
                        'objetivo': lote.total_objetivo,
                        'procesados': lote.procesados,
                        'pendientes': lote.pendientes,
                        'correctos': lote.correctos,
                        'omitidos': lote.omitidos,
                        'errores': lote.errores,
                        'ejemplares': lote.ejemplares,
                        'servidor_destino': lote.destino.get('host', ''),
                        'base_datos': lote.destino.get('database', ''),
                        'creado_en': lote.creado_en,
                        'actualizado_en': lote.actualizado_en,
                        'version_mapeo': lote.version_mapeo or '',
                    })
            messagebox.showinfo(
                'Historial exportado', 'Se guardó el historial de migraciones.',
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror('No se pudo exportar el historial', str(exc), parent=self)

    def seleccionar_real(self, identificador):
        self.demo.set(False)
        self.filtro.set('Todos')
        self.filtro_periodo.set('Todo el historial')
        self.orden.set('Más recientes')
        self.consulta.set('')
        self.actualizar(identificador)
        self._mostrar_vista('historial')
        self._mostrar_pagina_historial('detalle')

    def _pintar_tabla(self):
        seleccion_anterior = self.seleccionado
        self.tabla.delete(*self.tabla.get_children())
        consulta = self.consulta.get().strip().casefold()
        visibles = []
        lotes_visibles = filtrar_lotes(
            self.lotes, estado=self.filtro.get(),
            periodo=self.filtro_periodo.get(), orden=self.orden.get(),
        )
        for lote in lotes_visibles:
            if consulta and consulta not in (lote.id + ' ' + lote.fuente).casefold():
                continue
            self.tabla.insert('', 'end', iid=lote.id, values=(f'{lote.id} · {os.path.basename(lote.fuente)}', ESTADOS[lote.estado], f'{lote.progreso:g} %', f'{lote.total_recibidos:,}'), tags=(lote.estado,))
            visibles.append(lote.id)
        if self.seleccionado in visibles:
            self.tabla.selection_set(self.seleccionado)
        else:
            self.seleccionado = visibles[0] if visibles else None
            if self.seleccionado:
                self.tabla.selection_set(self.seleccionado)
        if self.seleccionado != seleccion_anterior:
            self._pintar_detalle()
        self.sin_lotes.config(
            text=('Aún no hay lotes. Ve a «1 Conexión» para validar tu archivo Access.'
                  if not self.lotes else
                  f'{len(visibles)} de {len(self.lotes)} lotes visibles. '
                  'Selecciona uno y pulsa «Ver detalle»; también puedes hacer doble clic.')
        )

    def _seleccionar(self, _evento=None):
        seleccion = self.tabla.selection()
        if seleccion:
            self.seleccionado = seleccion[0]
            self._pintar_detalle()

    def _abrir_detalle(self):
        if self.lote_actual():
            self._mostrar_pagina_historial('detalle')

    def lote_actual(self):
        return next((lote for lote in self.lotes if lote.id == self.seleccionado), None)

    def _pintar_detalle(self):
        lote = self.lote_actual()
        if lote is None:
            self.identificador.config(text='NINGÚN LOTE SELECCIONADO')
            self.nombre.config(text='Todo listo para comenzar')
            for etiqueta in (self.estado, self.etapa, self.conteos, self.siguiente, self.actualizado):
                etiqueta.config(text='')
            for valor in self.metricas_lote.values():
                valor.config(text='—')
            animar_valor(self.barra, 0)
            self._actualizar_texto_lote('incidencias', '')
            self._actualizar_texto_lote('actividad', '')
        else:
            self.identificador.config(text=lote.id)
            self.nombre.config(text=os.path.basename(lote.fuente))
            colores_estado = {
                'en_espera': '#777078',
                'en_proceso': '#6d0c2e',
                'concluido': '#367963',
                'con_incidencias': '#a36d23',
                'detenido': '#956c42',
            }
            self.estado.config(
                text=ESTADOS[lote.estado],
                foreground=colores_estado[lote.estado],
            )
            inicio = (datetime.fromisoformat(lote.iniciado_en).strftime('%d/%m/%Y %H:%M')
                      if lote.iniciado_en else '')
            usuario = f'Ejecutada por {lote.usuario}' if lote.usuario else 'Usuario sin registrar'
            self.etapa.config(text=(
                usuario
                + (f' · {inicio}' if inicio else '')
                + f'\n{ETAPAS[lote.etapa]}'
            ))
            animar_valor(self.barra, lote.progreso)
            self.conteos.config(text=(
                f'Procesadas  {lote.procesados:,} / {lote.total_objetivo:,}  ·  {lote.progreso:g} %\n'
                f'Ejemplares guardados  {lote.ejemplares:,}'
            ))
            for campo, valor in self.metricas_lote.items():
                valor.config(text=f'{getattr(lote, campo):,}')
            pasos = {
                'en_espera': 'Valida las conexiones y ejecuta este lote.',
                'en_proceso': 'Migración en curso. El avance se actualiza automáticamente.',
                'concluido': 'Listo para revisar o exportar. No se ha importado a Koha.',
                'con_incidencias': 'Abre Revisar fichas para ver la validación actual. Las advertencias permiten exportar.',
                'detenido': 'Avance conservado. Este lote no se reanuda automáticamente.',
            }
            siguiente = pasos[lote.estado]
            if lote.procesados and not lote.correctos:
                if lote.errores:
                    siguiente = 'Consulta los rechazos de la migración y reprocesa el lote una vez resuelta la causa.'
                elif lote.omitidos:
                    siguiente = 'Las fichas procesadas ya existían. Abre el lote que las convirtió para revisarlas.'
            elif lote.correctos and not self.politica(lote, self.demo.get())['revision']:
                siguiente += ' Para editar, usa el destino del lote y un perfil de Revisión, Aprobación o Administración.'
            if lote.lote_origen:
                siguiente = f'Reprocesamiento de {lote.lote_origen}. {siguiente}'
            self.siguiente.config(text=siguiente)
            self.actualizado.config(text='Última actualización: ' + datetime.fromisoformat(lote.actualizado_en).strftime('%d/%m/%Y %H:%M:%S'))
            detalle_incidencias = '\n\n'.join(
                f'{item["referencia"]}\n{item["mensaje"]}'
                for item in lote.incidencias
            )
            texto_incidencias = (
                f'{lote.errores:,} fichas con error · '
                f'{len(lote.incidencias):,} incidencias recientes al migrar. Abre Revisar fichas para consultar su estado actual.\n\n'
                f'{detalle_incidencias}'
            )
            self._actualizar_texto_lote('incidencias', texto_incidencias)
            tecnico = (
                f'Lote {lote.id}\n'
                f'Versión del mapeo: {lote.version_mapeo or "Sin registrar"}\n'
                f'Huella del mapeo: {lote.huella_mapeo or "Sin registrar"}\n\n'
            )
            eventos = '\n\n'.join(
                f'{item["fecha"]}\n{item["mensaje"]}'
                for item in reversed(lote.actividad)
            )
            self._actualizar_texto_lote('actividad', tecnico + eventos)
        politica = self.politica(lote, self.demo.get())
        principal = next((accion for accion in (
            'detener', 'iniciar', 'exportar', 'incidencias', 'reprocesar', 'revision', 'resumen',
        ) if politica[accion]), None)
        for accion, boton in (
            ('iniciar', self.btn_iniciar), ('detener', self.btn_detener),
            ('reprocesar', self.btn_reprocesar),
            ('exportar', self.btn_exportar), ('revision', self.btn_revisar),
            ('incidencias', self.btn_incidencias), ('resumen', self.btn_resumen),
            ('revision', self.btn_revisar_detalle), ('revision', self.btn_revisar_incidencias),
        ):
            boton.configure(
                state='normal' if politica[accion] else 'disabled',
                style='Primary.TButton' if accion == principal else 'TButton',
            )
        self.btn_nueva_migracion.configure(
            state='normal' if politica.get('nueva_migracion', False) else 'disabled',
        )
        self.btn_abrir_detalle.configure(
            state='normal' if lote else 'disabled',
        )
        aviso_destino = politica.get('aviso_destino_revision')
        if aviso_destino:
            self.aviso_destino_revision.configure(text=aviso_destino)
            self.aviso_destino_revision.grid()
        else:
            self.aviso_destino_revision.grid_remove()
        solicitada = politica['detencion_solicitada']
        self.btn_detener.configure(text='Deteniendo…' if solicitada else 'Detener migración')
        if solicitada:
            self.siguiente.configure(text='Detención solicitada. Se terminará la ficha u operación en curso antes de guardar el último avance.')

    def _actualizar_texto_lote(self, clave, contenido):
        texto = getattr(self, f'txt_{clave}_lote')
        texto.configure(state='normal')
        texto.delete('1.0', tk.END)
        texto.insert('1.0', contenido or texto.mensaje_vacio)
        texto.configure(state='disabled')

    def _iniciar(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['iniciar']:
            self.iniciar(lote.id)

    def _exportar(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['exportar']:
            self.exportar(lote.id)

    def _revisar(self):
        lote = self.lote_actual()
        if not lote or not self.politica(lote, self.demo.get())['revision']:
            return
        # La paginación evita consultar todo el lote de una vez.
        tamano_pagina = 50
        try:
            perfil = self.framework()
            registros = self.revisar(lote.id, 0, tamano_pagina)
            if registros is None:
                return
        except Exception as exc:
            messagebox.showerror(
                'No se pudieron consultar los registros', str(exc), parent=self,
            )
            return

        raiz = self.winfo_toplevel()
        estado_ventana_previo = raiz.state()
        geometria_previa = raiz.geometry()
        maximizada_por_revision = (
            raiz.winfo_viewable() and estado_ventana_previo != 'zoomed'
        )
        if maximizada_por_revision:
            raiz.state('zoomed')

        ventana = ttk.Frame(self._historial_contenedor, style='Panel.TFrame')
        ventana.grid(row=0, column=0, sticky='nsew')
        self._historial_paginas['revision'] = ventana
        ventana.columnconfigure(0, weight=1)
        ventana.rowconfigure(1, weight=1)
        cabecera_revision = ttk.Frame(ventana, style='Panel.TFrame')
        cabecera_revision.grid(row=0, column=0, sticky='ew', padx=ESPACIO_M)
        cabecera_revision.columnconfigure(1, weight=1)
        crear_icono(
            cabecera_revision, 'file', color=PRIMARIO, size=24, fondo=FONDO,
        ).grid(row=0, column=0, rowspan=2, sticky='w', padx=(0, ESPACIO_S))
        ttk.Label(
            cabecera_revision, text='Revisión individual de fichas',
            style='Titulo.Panel.TLabel',
        ).grid(row=0, column=1, sticky='w', pady=(8, 2))
        ttk.Label(
            cabecera_revision,
            text=f'{lote.id} · {os.path.basename(lote.fuente)}  —  '
                 'Selecciona una ficha para revisar sus campos.',
            style='Panel.TLabel',
        ).grid(row=1, column=1, sticky='w', pady=(0, 4))

        def cerrar_revision():
            self._historial_paginas.pop('revision', None)
            ventana.destroy()
            self._mostrar_pagina_historial('detalle')
            self._cabecera_panel.grid()
            self.aviso.grid()
            self._navegacion_panel.grid()
            if maximizada_por_revision:
                raiz.state('normal')
                raiz.geometry(geometria_previa)

        ttk.Button(
            cabecera_revision, text='← Volver al lote',
            command=cerrar_revision, style='Secondary.TButton',
        ).grid(row=0, column=2, sticky='e', padx=(ESPACIO_M, 0))
        navegacion_pagina = ttk.Frame(cabecera_revision, style='Panel.TFrame')
        navegacion_pagina.grid(row=1, column=2, sticky='e', padx=(ESPACIO_M, 0))
        navegacion_pagina.columnconfigure(1, weight=1)
        estado_pagina = ttk.Label(navegacion_pagina, style='Panel.TLabel')
        estado_pagina.grid(row=0, column=1, sticky='ew', padx=ESPACIO_XS)

        area = ttk.Panedwindow(ventana, orient='horizontal')
        area.grid(row=1, column=0, sticky='nsew', padx=12, pady=8)
        listado = ttk.Frame(area, padding=10, style='Tarjeta.TFrame')
        detalle = ttk.Frame(area, padding=10, style='Tarjeta.TFrame')
        area.add(listado, weight=1)
        area.add(detalle, weight=2)
        listado.columnconfigure(0, weight=1)
        listado.rowconfigure(1, weight=1)
        detalle.columnconfigure(0, weight=1)
        detalle.rowconfigure(2, weight=1)

        def ajustar_divisor():
            if not ventana.winfo_exists():
                return
            ancho = area.winfo_width()
            if ancho > 1:
                area.sashpos(0, min(330, max(180, int(ancho * 0.23))))

        ajuste_pendiente = ventana.after_idle(ajustar_divisor)
        busqueda_pendiente = None

        def cancelar_temporizadores(evento):
            if evento.widget is ventana:
                for pendiente in (ajuste_pendiente, busqueda_pendiente):
                    if pendiente is not None:
                        ventana.after_cancel(pendiente)
        ventana.bind('<Destroy>', cancelar_temporizadores, add='+')

        encabezado_lista = ttk.Frame(listado, style='Tarjeta.TFrame')
        encabezado_lista.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        crear_icono(
            encabezado_lista, 'database', color=PRIMARIO, size=18,
            fondo=SUPERFICIE,
        ).pack(side='left', padx=(0, ESPACIO_XS))
        ttk.Label(
            encabezado_lista, text='Fichas del lote', style='Nombre.TLabel',
        ).pack(side='left')
        lista_registros = ttk.Treeview(
            listado, columns=('ficha', 'estado'),
            show='headings', selectmode='browse', style='Lotes.Treeview',
            height=18,
        )
        for columna, titulo, ancho in (
            ('ficha', 'Ficha', 120),
            ('estado', 'Estado', 150),
        ):
            lista_registros.heading(columna, text=titulo)
            lista_registros.column(
                columna, width=ancho, minwidth=48, anchor='center',
            )
        lista_registros.grid(row=1, column=0, sticky='nsew')
        scroll_registros = ttk.Scrollbar(
            listado, orient='vertical', command=lista_registros.yview,
        )
        scroll_registros.grid(row=1, column=1, sticky='ns')
        lista_registros.configure(yscrollcommand=scroll_registros.set)

        encabezado_registro = ttk.Frame(detalle, style='Tarjeta.TFrame')
        encabezado_registro.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        encabezado_registro.columnconfigure(1, weight=1)
        crear_icono(
            encabezado_registro, 'file', color=PRIMARIO, size=18,
            fondo=SUPERFICIE,
        ).grid(row=0, column=0, sticky='w', padx=(0, ESPACIO_XS))
        lbl_registro = ttk.Label(
            encabezado_registro,
            text='Selecciona un registro para revisar sus campos.',
            style='Nombre.TLabel',
        )
        lbl_registro.grid(row=0, column=1, sticky='w')
        acciones_revision = ttk.Frame(encabezado_registro, style='Tarjeta.TFrame')
        acciones_revision.grid(row=1, column=0, columnspan=3, sticky='w', pady=(5, 0))
        lbl_aviso_registro = ttk.Label(
            detalle, text='', style='Tarjeta.TLabel', wraplength=680,
        )
        lbl_aviso_registro.grid(row=1, column=0, sticky='w', pady=(0, 6))
        vistas_detalle = ttk.Notebook(detalle, style='Revision.TNotebook')
        vistas_detalle.grid(row=2, column=0, sticky='nsew')
        marco_campos = ttk.Frame(vistas_detalle, padding=8)
        marco_ejemplares = ttk.Frame(vistas_detalle, padding=8)
        marco_xml = ttk.Frame(vistas_detalle, padding=8)
        vistas_detalle.add(marco_campos, text='▤  Campos MARC21')
        tab_issues = ttk.Frame(vistas_detalle, padding=8)
        tab_issues.columnconfigure(0, weight=1)
        tab_issues.rowconfigure(0, weight=1)
        texto_issues = tk.Text(tab_issues, wrap='word', font=(FUENTE, TAM_CUERPO), padx=8, pady=8)
        texto_issues.grid(row=0, column=0, sticky='nsew')
        scroll_issues = ttk.Scrollbar(tab_issues, command=texto_issues.yview)
        scroll_issues.grid(row=0, column=1, sticky='ns')
        texto_issues.configure(yscrollcommand=scroll_issues.set, state='disabled')
        vistas_detalle.add(tab_issues, text='Incidencias de la ficha')
        vistas_detalle.add(marco_ejemplares, text='▦  Ejemplares')
        vistas_detalle.add(marco_xml, text='<>  MARCXML')
        for marco in (marco_campos, marco_ejemplares, marco_xml):
            marco.columnconfigure(0, weight=1)
        marco_campos.rowconfigure(0, weight=1)
        marco_ejemplares.rowconfigure(1, weight=1)
        marco_xml.rowconfigure(0, weight=1)

        tabla_campos = ttk.Treeview(
            marco_campos, columns=('etiqueta', 'indicadores', 'contenido'),
            show='headings', style='Lotes.Treeview', height=24,
        )
        for columna, titulo, ancho in (
            ('etiqueta', 'Campo', 75),
            ('indicadores', 'Indicadores', 90),
            ('contenido', 'Contenido / subcampos', 340),
        ):
            tabla_campos.heading(columna, text=titulo)
            tabla_campos.column(
                columna, width=ancho, minwidth=65,
                anchor='w' if columna == 'contenido' else 'center',
                stretch=columna == 'contenido',
            )
        tabla_campos.grid(row=0, column=0, sticky='nsew')
        scroll_campos = ttk.Scrollbar(
            marco_campos, orient='vertical', command=tabla_campos.yview,
        )
        scroll_campos.grid(row=0, column=1, sticky='ns')
        scroll_campos_x = ttk.Scrollbar(
            marco_campos, orient='horizontal', command=tabla_campos.xview,
        )
        scroll_campos_x.grid(row=1, column=0, sticky='ew')
        tabla_campos.configure(
            yscrollcommand=scroll_campos.set, xscrollcommand=scroll_campos_x.set,
        )

        campos_ejemplar = (
            ('num_adqui', 'Núm. adquisición'),
            ('biblioteca', 'Biblioteca'),
            ('branch_koha', 'Sucursal Koha'),
            ('volumen', 'Volumen'),
            ('ejemplar', 'Ejemplar'),
            ('tomo', 'Tomo'),
            ('accesible', 'Accesible'),
            ('fecha_ingreso', 'Fecha ingreso'),
            ('signatura', 'Signatura'),
        )
        tabla_ejemplares = ttk.Treeview(
            marco_ejemplares, columns=('dato', 'valor'),
            show='tree headings', style='Lotes.Treeview',
        )
        lbl_estado_ejemplares = ttk.Label(
            marco_ejemplares, text='', style='Panel.TLabel', wraplength=700,
        )
        lbl_estado_ejemplares.grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 7),
        )
        tabla_ejemplares.heading('#0', text='Ejemplar')
        tabla_ejemplares.column('#0', width=120, minwidth=95, stretch=False)
        tabla_ejemplares.heading('dato', text='Dato')
        tabla_ejemplares.column('dato', width=155, minwidth=115, stretch=False)
        tabla_ejemplares.heading('valor', text='Valor')
        tabla_ejemplares.column('valor', width=320, minwidth=200, stretch=True)
        tabla_ejemplares.grid(row=1, column=0, sticky='nsew')
        scroll_ejemplares = ttk.Scrollbar(
            marco_ejemplares, orient='vertical', command=tabla_ejemplares.yview,
        )
        scroll_ejemplares.grid(row=1, column=1, sticky='ns')
        tabla_ejemplares.configure(yscrollcommand=scroll_ejemplares.set)

        texto_xml = tk.Text(
            marco_xml, wrap='none', font=('Consolas', 10),
            background='#fbfaf9', foreground='#302a31',
            insertbackground='#6d0c2e', relief='flat',
            padx=10, pady=8,
        )
        texto_xml.grid(row=0, column=0, sticky='nsew')
        texto_xml_y = ttk.Scrollbar(
            marco_xml, orient='vertical', command=texto_xml.yview,
        )
        texto_xml_y.grid(row=0, column=1, sticky='ns')
        texto_xml_x = ttk.Scrollbar(
            marco_xml, orient='horizontal', command=texto_xml.xview,
        )
        texto_xml_x.grid(row=1, column=0, sticky='ew')
        texto_xml.configure(
            yscrollcommand=texto_xml_y.set, xscrollcommand=texto_xml_x.set,
            state='disabled',
        )

        def boton_con_icono(parent, nombre_icono, texto, comando, estado='normal'):
            grupo = ttk.Frame(parent, style='Tarjeta.TFrame')
            posicion = len(parent.winfo_children()) - 1
            grupo.grid(row=posicion // 2, column=posicion % 2, sticky='w', padx=(0, ESPACIO_S), pady=2)
            icono = crear_icono(
                grupo, nombre_icono, color=PRIMARIO, size=16, fondo=SUPERFICIE,
            )
            icono.pack(side='left', padx=(0, ESPACIO_XS))
            boton = ttk.Button(
                grupo, text=texto, command=comando, state=estado,
                style='RevisionAction.TButton',
            )
            boton.pack(side='left')
            icono.configure(cursor='hand2')
            icono.bind('<Button-1>', lambda _evento: boton.invoke())
            return boton

        inicio_pagina = 0
        registros_actuales = []
        registro_seleccionado = [None]

        def abrir_pagina_auxiliar(clave, titulo, nombre_icono):
            pagina = ttk.Frame(self._historial_contenedor, style='Panel.TFrame')
            pagina.grid(row=0, column=0, sticky='nsew')
            pagina.columnconfigure(0, weight=1)
            pagina.rowconfigure(1, weight=1)
            self._historial_paginas[clave] = pagina
            encabezado = ttk.Frame(pagina, style='Panel.TFrame')
            encabezado.grid(row=0, column=0, sticky='ew', padx=ESPACIO_M)
            encabezado.columnconfigure(1, weight=1)
            crear_icono(
                encabezado, nombre_icono, color=PRIMARIO, size=24, fondo=FONDO,
            ).grid(row=0, column=0, sticky='w', padx=(0, ESPACIO_S))
            ttk.Label(
                encabezado, text=titulo, style='Titulo.Panel.TLabel',
            ).grid(row=0, column=1, sticky='w', pady=ESPACIO_S)
            ttk.Button(
                encabezado, text='← Volver a revisión',
                command=lambda: cerrar_pagina_auxiliar(clave, pagina),
                style='Secondary.TButton',
            ).grid(row=0, column=2, sticky='e')
            contenido = ttk.Frame(pagina, style='Panel.TFrame', padding=ESPACIO_M)
            contenido.grid(row=1, column=0, sticky='nsew')
            contenido.columnconfigure(0, weight=1)
            contenido.rowconfigure(1, weight=1)
            self._mostrar_pagina_historial(clave)
            return contenido, pagina

        def cerrar_pagina_auxiliar(clave, pagina):
            if self._historial_paginas.get(clave) is pagina:
                self._historial_paginas.pop(clave)
            pagina.destroy()
            self._mostrar_pagina_historial('revision')

        def mostrar_registro(_evento=None):
            seleccion = lista_registros.selection()
            if not seleccion:
                return
            registro = next(
                (item for item in registros_actuales
                 if str(item['id_ficha_acceso']) == seleccion[0]),
                None,
            )
            if registro is None:
                return
            registro_seleccionado[0] = registro
            boton_reparar.configure(state='disabled')
            boton_observaciones.configure(
                state='normal' if self.politica(
                    lote, self.demo.get(),
                ).get('registrar_observacion') else 'disabled',
            )
            issues = registro['incidencias_actuales']
            texto_issues.configure(state='normal')
            texto_issues.delete('1.0', 'end')
            texto_issues.insert('1.0', '\n\n'.join(i.texto() for i in issues) or 'Ficha válida para exportación.')
            originales = registro.get('motivos_migracion', [])
            if originales:
                texto_issues.insert('end', '\n\nObservaciones guardadas al migrar\n' + '\n'.join(originales))
            texto_issues.configure(state='disabled')
            vistas_detalle.tab(tab_issues, text=f'Incidencias ({len(issues)})')
            lbl_registro.config(
                text=f'Ficha {registro["id_ficha_acceso"]} · '
                     f'MARC 001: {registro.get("id_control") or "Sin valor"} · '
                     f'{estado_ficha(issues)}',
            )
            tabla_campos.delete(*tabla_campos.get_children())
            tabla_ejemplares.delete(*tabla_ejemplares.get_children())
            lbl_estado_ejemplares.config(text='')
            texto_xml.configure(state='normal')
            texto_xml.delete('1.0', tk.END)
            texto_xml.configure(state='disabled')
            try:
                campos, aviso = campos_para_revision(registro)
            except ValueError as exc:
                campos = []
                aviso = f'No se pudieron cargar los campos MARC: {exc}'
                tabla_campos.insert(
                    '', 'end',
                    values=('—', '—', 'Campos MARC no disponibles para esta ficha.'),
                )
            lbl_aviso_registro.config(
                text=aviso,
                foreground=ADVERTENCIA if aviso else TEXTO_MUTADO,
            )
            if aviso and self.politica(
                    lote, self.demo.get()).get('proponer_correccion'):
                boton_reparar.configure(state='normal')
            if campos:
                for campo in campos:
                    tabla_campos.insert(
                        '', 'end',
                        values=(
                            campo['etiqueta'], campo['indicadores'],
                            campo['contenido'],
                        ),
                    )
            ejemplares = registro.get('ejemplares', [])
            recuperados_marc = False
            if not ejemplares:
                try:
                    # MARC 952 es respaldo; no contiene todos los datos tabulares.
                    ejemplares = ejemplares_desde_registro_marc(registro)
                    recuperados_marc = bool(ejemplares)
                except ValueError as exc:
                    lbl_estado_ejemplares.config(
                        text=f'No se pudieron consultar ejemplares: {exc}',
                        foreground='#a36d23',
                    )
            if registro.get('estado') == 'VALIDADO' and not recuperados_marc and ejemplares:
                lbl_estado_ejemplares.config(text='Ejemplares del origen. Los campos 952 en la pestaña MARC21 muestran la versión aprobada para exportar.')
            elif recuperados_marc:
                lbl_estado_ejemplares.config(
                    text='No hay filas guardadas en la tabla de ejemplares. '
                         'Se muestran los datos disponibles del campo MARC 952; '
                         'los datos originales de Access no se pueden recuperar desde aquí.',
                    foreground='#a36d23',
                )
            elif ejemplares:
                lbl_estado_ejemplares.config(
                    text=f'{len(ejemplares):,} ejemplar(es) recuperado(s) de MySQL.',
                    foreground='#686168',
                )
            elif not lbl_estado_ejemplares.cget('text'):
                lbl_estado_ejemplares.config(
                    text='No hay ejemplares guardados ni campos MARC 952 para esta ficha.',
                    foreground='#686168',
                )
            for indice, ejemplar in enumerate(ejemplares, start=1):
                iid = f'ejemplar-{indice}'
                tabla_ejemplares.insert(
                    '', 'end', iid=iid, text=f'Ejemplar {indice}',
                    values=('', ''), open=True,
                )
                for clave, etiqueta in campos_ejemplar:
                    valor = ejemplar.get(clave)
                    tabla_ejemplares.insert(
                        iid, 'end', text='',
                        values=(etiqueta, '—' if valor is None or valor == '' else valor),
                    )
            texto_xml.configure(state='normal')
            texto_xml.delete('1.0', tk.END)
            texto_xml.insert(
                '1.0', registro.get('marca_marcxml') or
                'No hay MARCXML almacenado para esta ficha.',
            )
            texto_xml.configure(state='disabled')

        def registrar_observacion():
            registro = registro_seleccionado[0]
            if (registro is None or not self.politica(
                    lote, self.demo.get()).get('registrar_observacion')):
                return
            dialogo, pagina_observaciones = abrir_pagina_auxiliar(
                'observaciones',
                f'Observaciones de la ficha {registro["id_ficha_acceso"]}',
                'activity',
            )
            ttk.Label(
                dialogo,
                text='Observaciones previas de esta ficha (autor, fecha y nota):',
                style='Panel.TLabel',
            ).grid(row=0, column=0, sticky='w', padx=12, pady=(12, 6))
            tabla_notas = ttk.Treeview(
                dialogo, columns=('fecha', 'usuario', 'nota'),
                show='headings', style='Lotes.Treeview',
            )
            for columna, titulo, ancho in (
                ('fecha', 'Fecha', 150), ('usuario', 'Usuario', 120),
                ('nota', 'Observación', 420),
            ):
                tabla_notas.heading(columna, text=titulo)
                tabla_notas.column(
                    columna, width=ancho, minwidth=90,
                    stretch=columna == 'nota',
                    anchor='w' if columna == 'nota' else 'center',
                )
            tabla_notas.grid(
                row=1, column=0, sticky='nsew', padx=12, pady=(0, 8),
            )
            notas_scroll = ttk.Scrollbar(
                dialogo, orient='vertical', command=tabla_notas.yview,
            )
            notas_scroll.grid(row=1, column=1, sticky='ns', pady=(0, 8))
            tabla_notas.configure(yscrollcommand=notas_scroll.set)

            def cargar_observaciones():
                try:
                    # El historial queda acotado a la ficha y al lote abiertos.
                    observaciones = self.listar_observaciones(
                        lote.id, registro['id_ficha_acceso'],
                    )
                except Exception as exc:
                    messagebox.showerror(
                        'No se pudieron consultar las observaciones',
                        str(exc), parent=dialogo,
                    )
                    return False
                tabla_notas.delete(*tabla_notas.get_children())
                for observacion in observaciones:
                    fecha = observacion['fecha']
                    tabla_notas.insert(
                        '', 'end',
                        values=(
                            fecha.strftime('%Y-%m-%d %H:%M:%S')
                            if hasattr(fecha, 'strftime') else str(fecha),
                            observacion['usuario'], observacion['observacion'],
                        ),
                    )
                return True

            ttk.Label(
                dialogo, text='Nueva observación (máximo 5000 caracteres):',
                style='Panel.TLabel',
            ).grid(row=2, column=0, sticky='w', padx=12, pady=(0, 4))
            texto_observacion = tk.Text(
                dialogo, height=4, wrap='word',
                font=('Segoe UI', 10), relief='solid', bd=1,
            )
            texto_observacion.grid(
                row=3, column=0, sticky='ew', padx=12,
            )

            def guardar_observacion():
                texto = texto_observacion.get('1.0', 'end-1c')
                try:
                    self.registrar_observacion(
                        lote.id, registro['id_ficha_acceso'], texto,
                    )
                except Exception as exc:
                    messagebox.showerror(
                        'No se pudo guardar la observación', str(exc),
                        parent=dialogo,
                    )
                    return
                texto_observacion.delete('1.0', tk.END)
                cargar_observaciones()

            botones_observacion = ttk.Frame(dialogo, padding=12)
            botones_observacion.grid(row=4, column=0, sticky='ew')
            ttk.Button(
                botones_observacion, text='Volver a revisión',
                command=lambda: cerrar_pagina_auxiliar(
                    'observaciones', pagina_observaciones,
                ),
            ).pack(side='right')
            ttk.Button(
                botones_observacion, text='Guardar observación',
                style='Primary.TButton', command=guardar_observacion,
            ).pack(side='right', padx=(0, 8))
            cargar_observaciones()

        def proponer_reparacion_xml():
            registro = registro_seleccionado[0]
            if (registro is None or not self.politica(
                    lote, self.demo.get()).get('proponer_correccion')):
                return
            try:
                # La reparación desde ISO2709 queda pendiente de aprobación.
                record = record_desde_iso2709(registro.get('marca_iso2709'))
                marcxml, iso2709 = serializar_registro(record, perfil)
                propuesta_id = self.proponer(
                    lote.id, registro['id_ficha_acceso'], marcxml, iso2709,
                    registro['huella_revision'],
                )
            except Exception as exc:
                messagebox.showerror(
                    'No se pudo proponer la reparación',
                    f'No se pudo regenerar el MARCXML desde ISO2709. '
                    f'Revisa o completa los campos manualmente: {exc}',
                    parent=ventana,
                )
                return
            messagebox.showinfo(
                'Reparación pendiente',
                f'La reparación MARCXML de la ficha '
                f'{registro["id_ficha_acceso"]} quedó como propuesta '
                f'#{propuesta_id}. Aprobación debe revisarla y aplicarla.',
                parent=ventana,
            )
            cargar_pagina(inicio_pagina)

        def editar_registro():
            registro = registro_seleccionado[0]
            if (registro is None
                    or not self.politica(lote, self.demo.get()).get('proponer_correccion')):
                return
            record, aviso_edicion = record_para_edicion(registro)
            if aviso_edicion:
                messagebox.showwarning(
                    'Recuperación del registro', aviso_edicion, parent=ventana,
                )

            editor, pagina_editor = abrir_pagina_auxiliar(
                'editor',
                f'Proponer corrección · ficha {registro["id_ficha_acceso"]}',
                'settings',
            )
            editor.columnconfigure(0, weight=1)
            editor.rowconfigure(2, weight=1)
            aviso_editor = tk.StringVar()
            ttk.Label(
                editor,
                textvariable=aviso_editor,
                style='Panel.TLabel', wraplength=850,
            ).grid(row=0, column=0, sticky='w', padx=14, pady=(12, 8))
            leader_var = tk.StringVar(value=record.leader)
            leader_frame = ttk.Frame(editor, padding=(12, 4))
            leader_frame.grid(row=1, column=0, sticky='ew')
            ttk.Label(leader_frame, text='LDR (24 caracteres)').pack(side='left', padx=(0, 8))
            ttk.Entry(leader_frame, textvariable=leader_var, width=35).pack(side='left')

            marco_campos = ttk.Frame(editor, padding=12)
            marco_campos.grid(row=2, column=0, sticky='nsew')
            marco_campos.columnconfigure(0, weight=1)
            marco_campos.rowconfigure(0, weight=1)
            tabla_edicion = ttk.Treeview(
                marco_campos,
                columns=('tag', 'indicadores', 'contenido', 'revision'),
                show='headings', style='Lotes.Treeview',
            )
            for columna, titulo, ancho in (
                ('tag', 'Campo', 85), ('indicadores', 'Indicadores', 95),
                ('contenido', 'Contenido / subcampos', 460), ('revision', 'Revisión', 140),
            ):
                tabla_edicion.heading(columna, text=titulo)
                tabla_edicion.column(
                    columna, width=ancho, minwidth=75,
                    stretch=columna == 'contenido',
                    anchor='w' if columna == 'contenido' else 'center',
                )
            tabla_edicion.grid(row=0, column=0, sticky='nsew')
            edicion_scroll = ttk.Scrollbar(
                marco_campos, orient='vertical', command=tabla_edicion.yview,
            )
            edicion_scroll.grid(row=0, column=1, sticky='ns')
            edicion_scroll_x = ttk.Scrollbar(
                marco_campos, orient='horizontal', command=tabla_edicion.xview,
            )
            edicion_scroll_x.grid(row=1, column=0, sticky='ew')
            tabla_edicion.configure(
                yscrollcommand=edicion_scroll.set,
                xscrollcommand=edicion_scroll_x.set,
            )

            formulario = ttk.LabelFrame(
                editor, text='  Campo seleccionado o nuevo  ', padding=(12, 8),
            )
            formulario.grid(row=3, column=0, sticky='ew', padx=12)
            formulario.columnconfigure(3, weight=1)
            tag_var = tk.StringVar()
            indicadores_var = tk.StringVar()
            ttk.Label(formulario, text='Campo').grid(row=0, column=0, padx=(0, 5), sticky='w')
            ttk.Entry(formulario, textvariable=tag_var, width=8).grid(row=1, column=0, sticky='w')
            ttk.Label(
                formulario, text='Indicadores (# = espacio)',
            ).grid(row=0, column=1, padx=(12, 5), sticky='w')
            ttk.Entry(
                formulario, textvariable=indicadores_var, width=10,
            ).grid(row=1, column=1, sticky='w')
            ttk.Label(
                formulario, text='Contenido / subcampos ($a texto | $b texto)',
            ).grid(
                row=0, column=2, columnspan=2, padx=(12, 5), sticky='w',
            )
            contenido_editor = tk.Text(
                formulario, height=3, wrap='word',
                font=('Consolas', 10), background='#fbfaf9',
                foreground='#302a31', insertbackground='#6d0c2e',
                relief='solid', bd=1, padx=7, pady=5,
            )
            contenido_editor.grid(
                row=1, column=2, columnspan=2, sticky='ew',
                padx=(12, 0), pady=(2, 0),
            )

            campos_editables = list(record.fields)

            def registro_editado():
                propuesta = Record(force_utf8=True)
                propuesta.leader = leader_var.get()
                propuesta.fields = list(campos_editables)
                return propuesta

            def presentar_campos(seleccionar=None):
                tabla_edicion.delete(*tabla_edicion.get_children())
                problemas = validar_ficha(registro_editado(), perfil)
                ocurrencias = {}
                for indice, campo in enumerate(campos_editables):
                    if campo.is_control_field():
                        indicadores, contenido = '', campo.data or ''
                    else:
                        indicadores = ''.join(
                            indicador.strip() or '#' for indicador in campo.indicators
                        )
                        contenido = texto_subcampos(campo)
                    ocurrencias[campo.tag] = ocurrencias.get(campo.tag, 0) + 1
                    del_campo = [i for i in problemas if i.campo == campo.tag
                                 and i.ocurrencia in (0, ocurrencias[campo.tag])]
                    tabla_edicion.insert(
                        '', 'end', iid=str(indice),
                        values=(campo.tag, indicadores, contenido, estado_ficha(del_campo)),
                    )
                primero = next((i for i in problemas if i.gravedad == ERROR_MARC), None)
                aviso_editor.set(f'{estado_ficha(problemas)} · {len(problemas)} incidencias'
                                 + (f' · {primero.texto()}' if primero else ''))
                if seleccionar is None:
                    boton_duplicar.configure(state='disabled')
                if seleccionar is not None and 0 <= seleccionar < len(campos_editables):
                    tabla_edicion.selection_set(str(seleccionar))

            def limpiar_formulario():
                tag_var.set('')
                indicadores_var.set('')
                contenido_editor.delete('1.0', tk.END)
                tabla_edicion.selection_remove(*tabla_edicion.selection())
                formulario_estado.config(text='')
                boton_duplicar.configure(state='disabled')

            def seleccionar_campo(_evento=None):
                seleccion = tabla_edicion.selection()
                if not seleccion:
                    return
                campo = campos_editables[int(seleccion[0])]
                boton_duplicar.configure(state='normal' if es_repetible(campo.tag, perfil) else 'disabled')
                tag_var.set(campo.tag)
                if campo.is_control_field():
                    indicadores_var.set('')
                    contenido_editor.delete('1.0', tk.END)
                    contenido_editor.insert('1.0', campo.data or '')
                else:
                    indicadores_var.set(''.join(
                        indicador.strip() or '#' for indicador in campo.indicators
                    ))
                    contenido = texto_subcampos(campo)
                    contenido_editor.delete('1.0', tk.END)
                    contenido_editor.insert('1.0', contenido)
                num = sum(f.tag == campo.tag for f in campos_editables[:int(seleccion[0])+1])
                actuales = [i for i in validar_ficha(registro_editado(), perfil)
                            if i.campo == campo.tag and i.ocurrencia in (0, num)]
                formulario_estado.configure(text=actuales[0].texto() if actuales else '')

            def campo_validado(indice=None):
                campo = campo_desde_editor(
                    tag_var.get(), indicadores_var.get(),
                    contenido_editor.get('1.0', 'end-1c'),
                )

                if not es_repetible(campo.tag, perfil) and any(
                        f.tag == campo.tag for pos, f in enumerate(campos_editables) if pos != indice):
                    raise ValueError(f'{campo.tag} no es repetible.')
                return campo

            def agregar_campo():
                try:
                    campo = campo_validado()
                    campos_editables.append(campo)
                except ValueError as exc:
                    messagebox.showerror('Campo no válido', str(exc), parent=editor)
                    return
                presentar_campos(len(campos_editables) - 1)

            def actualizar_campo():
                seleccion = tabla_edicion.selection()
                if not seleccion:
                    messagebox.showwarning(
                        'Selecciona un campo', 'Selecciona un campo MARC para actualizar.',
                        parent=editor,
                    )
                    return
                try:
                    campo = campo_validado(int(seleccion[0]))
                except ValueError as exc:
                    messagebox.showerror('Campo no válido', str(exc), parent=editor)
                    return
                indice = int(seleccion[0])
                campos_editables[indice] = campo
                presentar_campos(indice)

            def duplicar_campo():
                seleccion = tabla_edicion.selection()
                if not seleccion:
                    return
                indice = int(seleccion[0])
                campo = campos_editables[indice]
                if es_repetible(campo.tag, perfil):
                    campos_editables.insert(indice + 1, deepcopy(campo))
                    presentar_campos(indice + 1)

            def eliminar_campo():
                seleccion = tabla_edicion.selection()
                if not seleccion:
                    messagebox.showwarning(
                        'Selecciona un campo', 'Selecciona el campo que deseas quitar.',
                        parent=editor,
                    )
                    return
                indice = int(seleccion[0])
                del campos_editables[indice]
                presentar_campos()
                limpiar_formulario()

            tabla_edicion.bind('<<TreeviewSelect>>', seleccionar_campo)
            acciones_campo = ttk.Frame(editor, padding=(12, 8))
            acciones_campo.grid(row=4, column=0, sticky='ew')
            ttk.Button(
                acciones_campo, text='Agregar campo', command=agregar_campo,
            ).pack(side='left', padx=(0, 6))
            ttk.Button(
                acciones_campo, text='Actualizar campo', command=actualizar_campo,
            ).pack(side='left', padx=(0, 6))
            ttk.Button(
                acciones_campo, text='Eliminar campo', command=eliminar_campo,
            ).pack(side='left')
            boton_duplicar = ttk.Button(acciones_campo, text='Duplicar campo', command=duplicar_campo, state='disabled')
            boton_duplicar.pack(side='left', padx=6)
            formulario_estado = ttk.Label(
                acciones_campo, style='Panel.TLabel',
            )
            formulario_estado.pack(side='left', padx=8)
            formulario_estado.configure(wraplength=280)

            def enviar_propuesta():
                seleccion = tabla_edicion.selection()
                if seleccion:
                    activo = campos_editables[int(seleccion[0])]
                    try:
                        pendiente = campo_desde_editor(tag_var.get(), indicadores_var.get(), contenido_editor.get('1.0', 'end-1c'))
                        if pendiente != activo and str(pendiente) != str(activo):
                            raise ValueError('Pulsa Actualizar campo antes de enviar los cambios.')
                    except ValueError as exc:
                        messagebox.showwarning('Campo pendiente', str(exc), parent=editor)
                        return
                elif tag_var.get().strip() or contenido_editor.get('1.0', 'end-1c').strip():
                    messagebox.showwarning('Campo pendiente', 'Pulsa Agregar campo antes de enviar.', parent=editor)
                    return
                try:
                    marcxml, iso2709 = serializar_registro(registro_editado(), perfil)
                    propuesta_id = self.proponer(
                        lote.id, registro['id_ficha_acceso'], marcxml, iso2709,
                        registro['huella_revision'],
                    )
                except Exception as exc:
                    messagebox.showerror(
                        'No se pudo proponer la corrección', str(exc), parent=editor,
                    )
                    return
                cerrar_pagina_auxiliar('editor', pagina_editor)
                messagebox.showinfo(
                    'Corrección pendiente',
                    f'La propuesta #{propuesta_id} quedó pendiente de revisión '
                    'por un usuario con perfil Aprobación. No se modificó aún el registro.',
                    parent=ventana,
                )
                cargar_pagina(inicio_pagina)

            barra_editor = ttk.Frame(editor, padding=(12, 6, 12, 12))
            barra_editor.grid(row=5, column=0, sticky='ew')
            def validar_edicion():
                try:
                    issues = validar_ficha(registro_editado(), perfil)
                    mensaje = '\n'.join(i.texto() for i in issues) or 'La ficha está lista para exportar.'
                    messagebox.showinfo(estado_ficha(issues), mensaje, parent=editor)
                except ValueError as exc:
                    messagebox.showerror('Leader no válido', str(exc), parent=editor)
            ttk.Button(barra_editor, text='Validar ficha', command=validar_edicion).pack(side='left')
            ttk.Button(
                barra_editor, text='Volver a revisión',
                command=lambda: cerrar_pagina_auxiliar('editor', pagina_editor),
            ).pack(side='right')
            ttk.Button(
                barra_editor, text='Enviar a aprobación',
                style='Primary.TButton', command=enviar_propuesta,
            ).pack(side='right', padx=(0, 8))
            pendiente = next((i for i in registro['incidencias_actuales'] if i.gravedad == ERROR_MARC
                              and i.campo.isdecimal()), None)
            indice = next((p for p, campo in enumerate(campos_editables)
                           if pendiente and campo.tag == pendiente.campo
                           and sum(f.tag == campo.tag for f in campos_editables[:p+1]) == (pendiente.ocurrencia or 1)), None)
            presentar_campos(indice)
            if pendiente and indice is None:
                tag_var.set(pendiente.campo)
                formulario_estado.configure(text=pendiente.detalle)

        def revisar_propuestas():
            if not self.politica(lote, self.demo.get()).get('aprobar_correccion'):
                return
            try:
                propuestas = self.listar_propuestas(lote.id)
            except Exception as exc:
                messagebox.showerror(
                    'No se pudieron consultar las propuestas', str(exc),
                    parent=ventana,
                )
                return
            if not propuestas:
                messagebox.showinfo(
                    'Sin propuestas pendientes',
                    'Este lote no tiene correcciones pendientes de aprobación.',
                    parent=ventana,
                )
                return

            revision, pagina_propuestas = abrir_pagina_auxiliar(
                'propuestas', f'Correcciones pendientes · {lote.id}', 'check',
            )
            revision.columnconfigure(0, weight=1)
            ttk.Label(
                revision,
                text='Compara la versión actual con la propuesta antes de resolverla.',
                style='Panel.TLabel',
            ).grid(row=0, column=0, sticky='w', padx=14, pady=10)
            propuesta_tabla = ttk.Treeview(
                revision, columns=('ficha', 'usuario', 'fecha'),
                show='headings', height=5, style='Lotes.Treeview',
            )
            for columna, titulo, ancho in (
                ('ficha', 'Ficha', 100), ('usuario', 'Propuesta por', 150),
                ('fecha', 'Fecha', 180),
            ):
                propuesta_tabla.heading(columna, text=titulo)
                propuesta_tabla.column(columna, width=ancho, anchor='center')
            propuesta_tabla.grid(row=1, column=0, sticky='new', padx=14)
            for propuesta in propuestas:
                propuesta_tabla.insert(
                    '', 'end', iid=str(propuesta['id']),
                    values=(
                        propuesta['id_ficha_acceso'], propuesta['propuesto_por'],
                        str(propuesta['fecha_creacion']),
                    ),
                )
            comparacion = ttk.Panedwindow(revision, orient='horizontal')
            comparacion.grid(row=2, column=0, sticky='nsew', padx=14, pady=10)
            revision.rowconfigure(2, weight=1)
            vistas_comparacion = []
            for titulo in ('Versión actual', 'Versión propuesta'):
                bloque = ttk.Frame(comparacion, padding=8, style='Tarjeta.TFrame')
                bloque.columnconfigure(0, weight=1)
                bloque.rowconfigure(1, weight=1)
                ttk.Label(bloque, text=titulo, style='Nombre.TLabel').grid(
                    row=0, column=0, sticky='w', pady=(0, 6),
                )
                tabla = ttk.Treeview(
                    bloque, columns=('tag', 'ind', 'contenido'),
                    show='headings', style='Lotes.Treeview',
                )
                for columna, texto, ancho in (
                    ('tag', 'Campo', 65), ('ind', 'Ind.', 60),
                    ('contenido', 'Subcampos', 380),
                ):
                    tabla.heading(columna, text=texto)
                    tabla.column(
                        columna, width=ancho,
                        anchor='w' if columna == 'contenido' else 'center',
                        stretch=columna == 'contenido',
                    )
                tabla.grid(row=1, column=0, sticky='nsew')
                scroll = ttk.Scrollbar(
                    bloque, orient='vertical', command=tabla.yview,
                )
                scroll.grid(row=1, column=1, sticky='ns')
                tabla.configure(yscrollcommand=scroll.set)
                comparacion.add(bloque, weight=1)
                vistas_comparacion.append(tabla)

            estado_propuesta = ttk.Label(revision, style='Panel.TLabel')
            estado_propuesta.grid(row=3, column=0, sticky='ew', padx=14)

            def pintar_propuesta(_evento=None):
                seleccion = propuesta_tabla.selection()
                if not seleccion:
                    return
                propuesta = next(
                    (item for item in propuestas
                     if str(item['id']) == seleccion[0]),
                    None,
                )
                if propuesta is None:
                    return
                versiones = (
                    {
                        'marca_marcxml': propuesta['marca_marcxml_actual'],
                        'marca_iso2709': propuesta['marca_iso2709_actual'],
                    },
                    {
                        'marca_marcxml': propuesta['marca_marcxml_propuesta'],
                        'marca_iso2709': propuesta['marca_iso2709_propuesta'],
                    },
                )
                try:
                    campos_versiones = [
                        campos_para_revision(version)[0] for version in versiones
                    ]
                except ValueError as exc:
                    messagebox.showerror(
                        'Propuesta inválida', str(exc), parent=revision,
                    )
                    return
                for tabla, campos in zip(vistas_comparacion, campos_versiones):
                    tabla.delete(*tabla.get_children())
                    for campo in campos:
                        tabla.insert(
                            '', 'end',
                            values=(
                                campo['etiqueta'], campo['indicadores'],
                                campo['contenido'],
                            ),
                        )
                estado_propuesta.config(
                    text=f'Propuesta #{propuesta["id"]} · ficha '
                         f'{propuesta["id_ficha_acceso"]} · autor: '
                         f'{propuesta["propuesto_por"]}. Al aprobar se actualizará '
                         'MARCXML, ISO2709 y el estado del registro.',
                )

            def resolver_seleccion(aprobar):
                seleccion = propuesta_tabla.selection()
                if not seleccion:
                    messagebox.showwarning(
                        'Selecciona una propuesta',
                        'Selecciona la corrección que deseas revisar.',
                        parent=revision,
                    )
                    return
                propuesta_id = int(seleccion[0])
                if not messagebox.askyesno(
                    'Confirmar decisión',
                    '¿Aprobar y aplicar esta corrección en MySQL?'
                    if aprobar else '¿Rechazar esta propuesta de corrección?',
                    parent=revision,
                ):
                    return
                try:
                    self.resolver_propuesta(lote.id, propuesta_id, aprobar)
                except Exception as exc:
                    messagebox.showerror(
                        'No se pudo resolver la corrección', str(exc),
                        parent=revision,
                    )
                    return
                cerrar_pagina_auxiliar('propuestas', pagina_propuestas)
                self.actualizar(seleccionar=lote.id)
                self._mostrar_pagina_historial('revision')
                cargar_pagina(inicio_pagina, seleccionar=next(p['id_ficha_acceso'] for p in propuestas if p['id'] == propuesta_id))

            propuesta_tabla.bind('<<TreeviewSelect>>', pintar_propuesta)
            botonera = ttk.Frame(revision, padding=12)
            botonera.grid(row=4, column=0, sticky='ew')
            ttk.Button(
                botonera, text='Volver a revisión',
                command=lambda: cerrar_pagina_auxiliar(
                    'propuestas', pagina_propuestas,
                ),
            ).pack(side='right')
            ttk.Button(
                botonera, text='Rechazar', command=lambda: resolver_seleccion(False),
            ).pack(side='right', padx=(0, 8))
            ttk.Button(
                botonera, text='Aprobar y aplicar',
                style='Primary.TButton',
                command=lambda: resolver_seleccion(True),
            ).pack(side='right', padx=(0, 8))
            propuesta_tabla.selection_set(str(propuestas[0]['id']))
            pintar_propuesta()

        def cargar_pagina(inicio, inicial=None, seleccionar=None):
            nonlocal inicio_pagina, registros_actuales
            try:
                pagina = (
                    inicial if inicial is not None
                    else self.revisar(lote.id, inicio, tamano_pagina)
                )
                if pagina is None:
                    return
                if not pagina:
                    raise ValueError('El lote no contiene registros para esta página.')
            except Exception as exc:
                messagebox.showerror(
                    'No se pudieron consultar los registros', str(exc),
                    parent=ventana,
                )
                return
            inicio_pagina = inicio
            registros_actuales = pagina
            lista_registros.delete(*lista_registros.get_children())
            for registro in registros_actuales:
                ficha = str(registro['id_ficha_acceso'])
                _, issues = inspeccionar_copias(registro.get('marca_marcxml'), registro.get('marca_iso2709'),
                                                perfil, registro.get('duplicado'))
                if registro.get('borrador_marc'):
                    borrador, _ = record_para_edicion(registro)
                    issues.extend(validar_ficha(borrador, perfil))
                registro['incidencias_actuales'] = issues
                lista_registros.insert(
                    '', 'end', iid=ficha,
                    values=(
                        ficha, estado_ficha(issues),
                    ),
                )
            fin = inicio_pagina + len(registros_actuales)
            estado_pagina.config(
                text=f'Registros {inicio_pagina + 1:,}–{fin:,} de '
                     f'{lote.correctos:,} convertidos',
            )
            boton_anterior.configure(
                state='normal' if inicio_pagina > 0 else 'disabled',
            )
            boton_siguiente.configure(
                state='normal' if fin < lote.correctos else 'disabled',
            )
            clave = str(seleccionar)
            if not lista_registros.exists(clave):
                clave = str(registros_actuales[0]['id_ficha_acceso'])
            lista_registros.selection_set(clave)
            lista_registros.see(clave)
            mostrar_registro()
            return True

        def buscar_incidencia(direccion):
            actual = registro_seleccionado[0]
            if not actual:
                return
            pos = next(i for i, fila in enumerate(registros_actuales) if fila is actual)
            nonlocal busqueda_pendiente
            if busqueda_pendiente is not None:
                ventana.after_cancel(busqueda_pendiente)
            def buscar(indice):
                nonlocal busqueda_pendiente
                busqueda_pendiente = None
                if not ventana.winfo_exists() or self._historial_pagina_actual != 'revision':
                    return
                while 0 <= indice < len(registros_actuales):
                    fila = registros_actuales[indice]
                    if fila['incidencias_actuales']:
                        clave = str(fila['id_ficha_acceso'])
                        lista_registros.selection_set(clave)
                        lista_registros.see(clave)
                        mostrar_registro()
                        vistas_detalle.select(tab_issues)
                        return
                    indice += direccion
                pagina = inicio_pagina + direccion * tamano_pagina
                if 0 <= pagina < lote.correctos and cargar_pagina(pagina):
                    busqueda_pendiente = ventana.after(1, buscar, 0 if direccion > 0 else len(registros_actuales) - 1)
                else:
                    messagebox.showinfo('Revisión de incidencias', 'Llegaste al final de la búsqueda.', parent=ventana)
            buscar(pos + direccion)

        saltos = ttk.Frame(listado, style='Tarjeta.TFrame')
        saltos.grid(row=2, column=0, columnspan=2, sticky='ew')
        for indice, (etiqueta, sentido) in enumerate((('← Incidencia', -1), ('Incidencia →', 1))):
            ttk.Button(saltos, text=etiqueta, command=lambda d=sentido: buscar_incidencia(d)).grid(row=0, column=indice, sticky='ew')
        lista_registros.bind('<<TreeviewSelect>>', mostrar_registro)
        boton_anterior = ttk.Button(
            navegacion_pagina, text='← Anterior',
            command=lambda: cargar_pagina(max(0, inicio_pagina - tamano_pagina)),
        )
        boton_anterior.grid(row=0, column=0, sticky='w')
        politica_revision = self.politica(lote, self.demo.get())
        boton_observaciones = boton_con_icono(
            acciones_revision, 'activity', 'Observaciones',
            registrar_observacion, 'disabled',
        )
        boton_reparar = boton_con_icono(
            acciones_revision, 'refresh', 'Proponer reparación XML',
            proponer_reparacion_xml, 'disabled',
        )
        boton_editar = boton_con_icono(
            acciones_revision, 'settings', 'Corregir / proponer',
            editar_registro,
            estado='normal' if politica_revision.get('proponer_correccion') else 'disabled',
        )
        boton_propuestas = boton_con_icono(
            acciones_revision, 'check', 'Revisar propuestas',
            revisar_propuestas,
            'normal' if politica_revision.get('aprobar_correccion') else 'disabled',
        )
        boton_siguiente = ttk.Button(
            navegacion_pagina, text='Siguiente →',
            command=lambda: cargar_pagina(inicio_pagina + tamano_pagina),
        )
        boton_siguiente.grid(row=0, column=2, sticky='e')
        self._cabecera_panel.grid_remove()
        self.aviso.grid_remove()
        self._navegacion_panel.grid_remove()
        self._mostrar_pagina_historial('revision')
        cargar_pagina(0, inicial=registros)
        ventana.after_idle(lista_registros.focus_set)

    def _detener(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['detener']:
            self.detener(lote.id)

    def _reprocesar(self):
        lote = self.lote_actual()
        if lote and self.politica(lote, self.demo.get()).get('reprocesar'):
            self.reprocesar(lote.id)

    def _incidencias(self):
        lote = self.lote_actual()
        if lote and self.politica(lote, self.demo.get())['incidencias']:
            self._mostrar_detalle('incidencias')

    def _actividad(self):
        lote = self.lote_actual()
        if lote:
            self._mostrar_detalle('actividad')

    def _resumen(self):
        lote = self.lote_actual()
        if not lote or not self.politica(lote, self.demo.get())['resumen']:
            return
        demostracion = self.demo.get()
        ruta = filedialog.asksaveasfilename(
            parent=self, title='Guardar reporte del lote',
            initialfile=f'{"EJEMPLO-" if demostracion else ""}{lote.id}.csv',
            defaultextension='.csv',
            filetypes=[('Detalle por ficha CSV', '*.csv'), ('Resumen JSON', '*.json')],
        )
        if not ruta:
            return

        def guardar():
            try:
                detalle = lote if demostracion else self.obtener(lote.id)
                escribir_reporte_lote(ruta, detalle, demostracion)
                self.publicar(messagebox.showinfo, 'Reporte guardado', 'Se guardó el reporte del lote.')
            except Exception as exc:
                self.publicar(messagebox.showerror, 'No se pudo guardar el reporte', str(exc))

        Thread(target=guardar, daemon=True).start()
