"""Panel Tkinter del sprint 2, integrado en el Notebook de MigracionApp."""
from dataclasses import asdict
from datetime import date, datetime, timedelta
import csv
from io import BytesIO, StringIO
import json
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from xml.sax import SAXException
from xml.etree import ElementTree
from pymarc import Field, MARCReader, Record, Subfield, parse_xml_to_array
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter

from lotes import ESTADOS, ETAPAS, lotes_de_ejemplo


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
            ['#90909a', '#477bbb', '#358265', '#a36d23', '#956c42'],
        )
    if tipo == 'Resultado de fichas':
        return (
            'Fichas agrupadas por resultado',
            ['Correctas', 'Omitidas', 'Con error', 'Pendientes'],
            [
                sum(lote.correctos for lote in lotes),
                sum(lote.omitidos for lote in lotes),
                sum(lote.errores for lote in lotes),
                sum(lote.pendientes for lote in lotes),
            ],
            ['#358265', '#477bbb', '#a36d23', '#90909a'],
        )
    if tipo not in ('Fichas correctas por lote', 'Ejemplares por lote'):
        raise ValueError(f'Tipo de gráfico no reconocido: {tipo}')
    clave = 'correctos' if tipo == 'Fichas correctas por lote' else 'ejemplares'
    titulo = 'Fichas correctas por lote' if clave == 'correctos' else 'Ejemplares por lote'
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
        ['#6d0c2e'] * len(lotes_destacados),
    )


def campos_desde_marcxml(contenido):
    try:
        raiz = ElementTree.fromstring(contenido)
    except ElementTree.ParseError as exc:
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
                    indicador or '#' for indicador in campo.indicators
                ),
                'contenido': '  |  '.join(subcampos),
            })
    return campos


def campos_para_revision(registro):
    try:
        return campos_desde_marcxml(registro['marca_marcxml']), ''
    except ValueError as error_xml:
        try:
            campos = campos_desde_iso2709(registro.get('marca_iso2709'))
        except ValueError as error_iso:
            raise ValueError(
                f'{error_xml} Tampoco se pudo recuperar el registro desde '
                f'ISO2709: {error_iso}'
            ) from error_iso
        return campos, (
            'Aviso: el MARCXML almacenado no es válido. Los campos se '
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
            'volumen': primer_subcampo(campo, 'c') or '—',
            'ejemplar': '—',
            'tomo': '—',
            'accesible': primer_subcampo(campo, 'z') or '—',
            'fecha_ingreso': '—',
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
    errores = []
    try:
        return record_desde_iso2709(registro.get('marca_iso2709')), ''
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


def parsear_subcampos(texto):
    resultado = []
    for parte in texto.split('|'):
        parte = parte.strip()
        coincidencia = re.fullmatch(r'\$([a-z0-9])\s+(.+)', parte, re.DOTALL)
        if not coincidencia:
            raise ValueError(
                'Escribe los subcampos como «$a valor | $b valor». '
                'Cada subcampo requiere código y contenido.'
            )
        resultado.append(Subfield(coincidencia.group(1), coincidencia.group(2).strip()))
    if not resultado:
        raise ValueError('Agrega por lo menos un subcampo.')
    return resultado


def campo_desde_editor(tag, indicadores, contenido):
    tag = tag.strip()
    if not re.fullmatch(r'\d{3}', tag):
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


def serializar_registro(record):
    xml = MarcConverter().record_a_marcxml(record)
    iso2709 = record.as_marc()
    MySQLWriter._validar_registro_propuesto(xml, iso2709)
    return xml, iso2709


class PanelLotes(ttk.Frame):
    def __init__(self, parent, listar, politica, iniciar, exportar, revisar,
                 proponer, listar_propuestas, resolver_propuesta,
                 listar_observaciones, registrar_observacion,
                 conexiones, detener, reprocesar):
        super().__init__(parent, padding=16, style='Panel.TFrame')
        self.listar = listar
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
        estilo.configure('Panel.TFrame', background='#f7f5f2')
        estilo.configure('Tarjeta.TFrame', background='#ffffff')
        estilo.configure('Panel.TLabel', background='#f7f5f2', foreground='#777078', font=('Segoe UI', 9))
        estilo.configure('Titulo.Panel.TLabel', background='#f7f5f2', foreground='#302a31', font=('Segoe UI', 19, 'bold'))
        estilo.configure('Tarjeta.TLabel', background='#ffffff', foreground='#686168', font=('Segoe UI', 9))
        estilo.configure('Nombre.TLabel', background='#ffffff', foreground='#302a31', font=('Segoe UI', 14, 'bold'))
        estilo.configure('Numero.TLabel', background='#ffffff', foreground='#6d0c2e', font=('Segoe UI', 20, 'bold'))
        estilo.configure('Lotes.Treeview', rowheight=36, font=('Segoe UI', 9),
                         background='#ffffff', fieldbackground='#ffffff', foreground='#302a31')
        estilo.configure('Lotes.Treeview.Heading', font=('Segoe UI', 9, 'bold'),
                         background='#f7f5f2', foreground='#686168', padding=(8, 9))
        estilo.map('Lotes.Treeview', background=[('selected', '#f3e8ec')],
                   foreground=[('selected', '#6d0c2e')])
        estilo.configure('Lotes.Horizontal.TProgressbar', background='#6d0c2e', troughcolor='#e8e2de',
                         thickness=8)
        estilo.configure('Estado.TLabel', background='#ffffff', foreground='#6d0c2e',
                         font=('Segoe UI', 9, 'bold'))

    def _crear(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        cabecera = ttk.Frame(self, style='Panel.TFrame')
        cabecera.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        ttk.Label(cabecera, text='Lotes recientes', style='Titulo.Panel.TLabel').pack(side='left')
        acciones_cabecera = ttk.Frame(cabecera, style='Panel.TFrame')
        acciones_cabecera.pack(side='right')
        ttk.Button(
            acciones_cabecera, text='Actualizar', style='Quiet.TButton',
            command=self.actualizar,
        ).pack(side='left', padx=(0, 6))
        self.btn_exportar_historial = ttk.Button(
            acciones_cabecera, text='Exportar historial CSV',
            style='Secondary.TButton', command=self._exportar_historial,
        )
        self.btn_exportar_historial.pack(side='left', padx=(0, 8))
        self.btn_nueva_migracion = ttk.Button(
            acciones_cabecera, text='Nueva migración', style='Primary.TButton',
            command=self.conexiones,
        )
        self.btn_nueva_migracion.pack(side='right')
        self.aviso = ttk.Label(
            self, text='Selecciona un lote para ver su estado y las acciones disponibles.',
            style='Panel.TLabel',
        )
        self.aviso.grid(row=1, column=0, sticky='ew', pady=(0, 12))

        self.vistas = ttk.Notebook(self)
        self.vistas.grid(row=2, column=0, sticky='nsew')
        self.resumen = ttk.Frame(self.vistas, padding=(4, 12), style='Panel.TFrame')
        self.historial_tab = ttk.Frame(self.vistas, padding=(4, 12), style='Panel.TFrame')
        self.analisis_tab = ttk.Frame(self.vistas, padding=(4, 12), style='Panel.TFrame')
        self.vistas.add(self.resumen, text='Resumen')
        self.vistas.add(self.historial_tab, text='Historial')
        self.vistas.add(self.analisis_tab, text='Análisis')
        for indice in range(4):
            self.resumen.columnconfigure(indice, weight=1, uniform='metricas')
        self.resumen.rowconfigure(2, weight=1)
        self.metricas = {}
        for indice, (clave, titulo) in enumerate((
            ('total_lotes', 'LOTES REGISTRADOS'),
            ('fichas_correctas', 'FICHAS CORRECTAS'),
            ('ejemplares', 'EJEMPLARES'),
            ('requieren_revision', 'REQUIEREN REVISIÓN'),
        )):
            tarjeta = ttk.Frame(self.resumen, padding=(12, 8), style='Tarjeta.TFrame')
            tarjeta.grid(row=0, column=indice, sticky='ew', padx=(0 if indice == 0 else 6, 6))
            ttk.Label(tarjeta, text=titulo, style='Tarjeta.TLabel').pack(anchor='w')
            valor = ttk.Label(tarjeta, text='0', style='Numero.TLabel')
            valor.pack(anchor='w', pady=(2, 0))
            self.metricas[clave] = valor
        orientacion = ttk.LabelFrame(
            self.resumen, text='  Lectura rápida  ', padding=(14, 10),
        )
        orientacion.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(14, 0))
        self.lbl_lectura_rapida = ttk.Label(
            orientacion, style='Tarjeta.TLabel', wraplength=950, justify='left',
        )
        self.lbl_lectura_rapida.pack(anchor='w', fill='x')
        recientes = ttk.LabelFrame(
            self.resumen, text='  Actividad reciente  ', padding=(14, 10),
        )
        recientes.grid(row=2, column=0, columnspan=4, sticky='nsew', pady=(12, 0))
        recientes.columnconfigure(0, weight=1)
        recientes.rowconfigure(0, weight=1)
        self.lista_recientes = ttk.Treeview(
            recientes, columns=('estado', 'avance', 'fecha'),
            show='tree headings', height=5, style='Lotes.Treeview',
        )
        self.lista_recientes.heading('#0', text='Lote / origen')
        self.lista_recientes.heading('estado', text='Estado')
        self.lista_recientes.heading('avance', text='Avance')
        self.lista_recientes.heading('fecha', text='Última actualización')
        self.lista_recientes.column('#0', width=420, minwidth=180, stretch=True)
        self.lista_recientes.column('estado', width=135, anchor='w')
        self.lista_recientes.column('avance', width=90, anchor='center')
        self.lista_recientes.column('fecha', width=175, anchor='w')
        self.lista_recientes.grid(row=0, column=0, sticky='nsew')
        recientes_scroll = ttk.Scrollbar(
            recientes, orient='vertical', command=self.lista_recientes.yview,
        )
        recientes_scroll.grid(row=0, column=1, sticky='ns')
        self.lista_recientes.configure(yscrollcommand=recientes_scroll.set)
        self.lista_recientes.bind('<<TreeviewSelect>>', self._seleccionar_reciente)

        self.analisis_tab.columnconfigure(0, weight=1)
        self.analisis_tab.rowconfigure(1, weight=1)
        barra_analisis = ttk.Frame(self.analisis_tab, style='Panel.TFrame')
        barra_analisis.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(barra_analisis, text='Visualizar', style='Panel.TLabel').pack(side='left', padx=(2, 8))
        selector_grafico = ttk.Combobox(
            barra_analisis, textvariable=self.tipo_grafico,
            values=('Estado de los lotes', 'Resultado de fichas',
                    'Fichas correctas por lote', 'Ejemplares por lote'),
            state='readonly', width=28,
        )
        selector_grafico.pack(side='left')
        selector_grafico.bind('<<ComboboxSelected>>', lambda _evento: self._pintar_grafico())
        tarjeta_grafico = ttk.Frame(
            self.analisis_tab, padding=(16, 14), style='Tarjeta.TFrame',
        )
        tarjeta_grafico.grid(row=1, column=0, sticky='nsew')
        tarjeta_grafico.columnconfigure(0, weight=1)
        tarjeta_grafico.rowconfigure(1, weight=1)
        self.lbl_titulo_grafico = ttk.Label(
            tarjeta_grafico, text='', style='Nombre.TLabel',
        )
        self.lbl_titulo_grafico.grid(row=0, column=0, sticky='w', pady=(0, 4))
        self.grafico = tk.Canvas(
            tarjeta_grafico, background='#ffffff',
            highlightthickness=0, borderwidth=0,
        )
        self.grafico.grid(row=1, column=0, sticky='nsew')
        self.grafico.bind('<Configure>', lambda _evento: self._pintar_grafico())

        cuerpo = ttk.Panedwindow(self.historial_tab, orient='horizontal')
        cuerpo.pack(fill='both', expand=True, pady=(0, 6))
        listado = ttk.Frame(cuerpo, padding=12, style='Tarjeta.TFrame')
        detalle = ttk.Frame(cuerpo, padding=18, style='Tarjeta.TFrame')
        cuerpo.add(listado, weight=3)
        cuerpo.add(detalle, weight=2)
        listado.columnconfigure(0, weight=1)
        listado.rowconfigure(2, weight=1)
        filtros = ttk.Frame(listado, style='Tarjeta.TFrame')
        filtros.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        ttk.Label(filtros, text='Estado', style='Tarjeta.TLabel').pack(side='left', padx=(0, 6))
        combo = ttk.Combobox(
            filtros, textvariable=self.filtro,
            values=['Todos'] + list(ESTADOS.values()), state='readonly', width=15,
        )
        combo.pack(side='left', padx=(0, 10))
        combo.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        ttk.Label(filtros, text='Periodo', style='Tarjeta.TLabel').pack(side='left', padx=(0, 6))
        combo_periodo = ttk.Combobox(
            filtros, textvariable=self.filtro_periodo,
            values=('Todo el historial', 'Últimos 7 días',
                    'Últimos 30 días', 'Este año'),
            state='readonly', width=17,
        )
        combo_periodo.pack(side='left')
        combo_periodo.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        filtros_orden = ttk.Frame(listado, style='Tarjeta.TFrame')
        filtros_orden.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        ttk.Label(filtros_orden, text='Buscar', style='Tarjeta.TLabel').pack(side='left', padx=(0, 6))
        entrada = ttk.Entry(filtros_orden, textvariable=self.consulta)
        entrada.pack(side='left', fill='x', expand=True, padx=(0, 10))
        ttk.Label(filtros_orden, text='Ordenar', style='Tarjeta.TLabel').pack(side='left', padx=(0, 6))
        combo_orden = ttk.Combobox(
            filtros_orden, textvariable=self.orden,
            values=('Más recientes', 'Más antiguos', 'Más errores',
                    'Mayor avance'),
            state='readonly', width=16,
        )
        combo_orden.pack(side='left')
        combo_orden.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        self.consulta.trace_add('write', lambda *_: self._pintar_tabla())
        self.tabla = ttk.Treeview(listado, columns=('lote', 'estado', 'avance', 'total'), show='headings', selectmode='browse', style='Lotes.Treeview')
        for columna, titulo, ancho in (('lote', 'Lote / origen', 240), ('estado', 'Estado', 130), ('avance', 'Avance', 70), ('total', 'Recibidos', 75)):
            self.tabla.heading(columna, text=titulo)
            self.tabla.column(columna, width=ancho, minwidth=65, stretch=columna == 'lote', anchor='w')
        self.tabla.grid(row=2, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(listado, orient='vertical', command=self.tabla.yview)
        scroll.grid(row=2, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(listado, orient='horizontal', command=self.tabla.xview)
        horizontal.grid(row=3, column=0, sticky='ew')
        self.tabla.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        for estado, color in (('en_espera', '#777d91'), ('en_proceso', '#477bbb'), ('concluido', '#358265'), ('con_incidencias', '#a36d23'), ('detenido', '#956c42')):
            self.tabla.tag_configure(estado, foreground=color)
        self.tabla.bind('<<TreeviewSelect>>', self._seleccionar)
        self.sin_lotes = ttk.Label(listado, style='Tarjeta.TLabel', wraplength=430)
        self.sin_lotes.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(8, 0))

        detalle.columnconfigure(0, weight=1)
        self.identificador = ttk.Label(detalle, style='Tarjeta.TLabel')
        self.identificador.grid(row=0, column=0, sticky='w')
        self.nombre = ttk.Label(detalle, style='Nombre.TLabel', wraplength=340)
        self.nombre.grid(row=1, column=0, sticky='ew', pady=(4, 8))
        self.estado = ttk.Label(detalle, style='Estado.TLabel')
        self.estado.grid(row=2, column=0, sticky='ew')
        self.etapa = ttk.Label(detalle, style='Tarjeta.TLabel')
        self.etapa.grid(row=3, column=0, sticky='ew', pady=(4, 8))
        self.barra = ttk.Progressbar(detalle, maximum=100, style='Lotes.Horizontal.TProgressbar')
        self.barra.grid(row=4, column=0, sticky='ew')
        self.conteos = ttk.Label(detalle, style='Tarjeta.TLabel', wraplength=350)
        self.conteos.grid(row=5, column=0, sticky='ew', pady=(7, 10))
        self.siguiente = ttk.Label(detalle, style='Tarjeta.TLabel', wraplength=350)
        self.siguiente.grid(row=6, column=0, sticky='ew', pady=(0, 12))
        acciones = ttk.Frame(detalle, style='Tarjeta.TFrame')
        acciones.grid(row=7, column=0, sticky='ew')
        control = ttk.Frame(acciones, style='Tarjeta.TFrame')
        control.pack(fill='x', pady=3)
        self.btn_iniciar = ttk.Button(control, text='Ejecutar migración', command=self._iniciar)
        self.btn_iniciar.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.btn_detener = ttk.Button(control, text='Detener migración', command=self._detener)
        self.btn_detener.pack(side='left', fill='x', expand=True)
        self.btn_reprocesar = ttk.Button(
            acciones, text='Reprocesar pendientes',
            command=self._reprocesar,
        )
        self.btn_reprocesar.pack(fill='x', pady=3)
        self.btn_exportar = ttk.Button(acciones, text='Exportar MARCXML del lote', command=self._exportar)
        self.btn_exportar.pack(fill='x', pady=3)
        self.btn_revisar = ttk.Button(
            acciones, text='Visualizar registros migrados',
            command=self._revisar,
        )
        self.btn_revisar.pack(fill='x', pady=3)
        fila = ttk.Frame(acciones, style='Tarjeta.TFrame')
        fila.pack(fill='x', pady=3)
        self.btn_incidencias = ttk.Button(fila, text='Ver incidencias', command=self._incidencias)
        self.btn_incidencias.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.btn_resumen = ttk.Button(fila, text='Guardar resumen', command=self._resumen)
        self.btn_resumen.pack(side='left', fill='x', expand=True)
        self.actualizado = ttk.Label(detalle, style='Tarjeta.TLabel', wraplength=350)
        self.actualizado.grid(row=8, column=0, sticky='ew', pady=(12, 0))
        ttk.Button(
            self.historial_tab, text='Ver actividad del lote', style='Quiet.TButton',
            command=self._actividad,
        ).pack(anchor='e', pady=(2, 0))

    def _cambiar_modo(self):
        self.seleccionado = None
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
            f'{tasa} de fichas correctas sobre las procesadas.'
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
        self.vistas.select(self.historial_tab)
        self._pintar_tabla()
        self._pintar_detalle()

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
                fill='#777078', font=('Segoe UI', 11), anchor='center',
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
                fill='#686168', font=('Segoe UI', 9), anchor='e',
                width=margen_izquierdo - 20,
            )
            self.grafico.create_rectangle(
                margen_izquierdo, y, margen_izquierdo + ancho_barra, y + 18,
                fill='#f1eeec', outline='',
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
            'lote', 'fuente', 'estado', 'etapa', 'progreso_porcentaje',
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

    def _pintar_tabla(self):
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
        self.sin_lotes.config(
            text=('Aún no hay lotes. Ve a «1 Conexión» para validar tu archivo Access.'
                  if not self.lotes else
                  f'{len(visibles)} de {len(self.lotes)} lotes visibles. Selecciona uno para ver el detalle.')
        )

    def _seleccionar(self, _evento=None):
        seleccion = self.tabla.selection()
        if seleccion:
            self.seleccionado = seleccion[0]
            self._pintar_detalle()

    def lote_actual(self):
        return next((lote for lote in self.lotes if lote.id == self.seleccionado), None)

    def _pintar_detalle(self):
        lote = self.lote_actual()
        if lote is None:
            self.identificador.config(text='NINGÚN LOTE SELECCIONADO')
            self.nombre.config(text='Todo listo para comenzar')
            for etiqueta in (self.estado, self.etapa, self.conteos, self.siguiente, self.actualizado):
                etiqueta.config(text='')
            self.barra['value'] = 0
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
            self.etapa.config(text='Etapa: ' + ETAPAS[lote.etapa])
            self.barra['value'] = lote.progreso
            self.conteos.config(text=(
                f'{lote.procesados:,} de {lote.total_objetivo:,} fichas · {lote.progreso:g} %\n'
                f'{lote.correctos:,} correctas  ·  {lote.omitidos:,} omitidas  ·  {lote.errores:,} errores\n'
                f'{lote.pendientes:,} pendientes  ·  {lote.ejemplares:,} ejemplares\n'
                f'Mapeo MARC21 {lote.version_mapeo or "no registrado"}'
                f'{(" · SHA-256 " + lote.huella_mapeo) if lote.huella_mapeo else ""}'
            ))
            pasos = {
                'en_espera': 'Valida las conexiones y ejecuta este lote.',
                'en_proceso': 'Migración en curso. El avance se actualiza automáticamente.',
                'concluido': 'Listo para revisar o exportar. No se ha importado a Koha.',
                'con_incidencias': 'Revisa las incidencias antes de continuar.',
                'detenido': 'Avance conservado. Este lote no se reanuda automáticamente.',
            }
            siguiente = pasos[lote.estado]
            if lote.lote_origen:
                siguiente = f'Reprocesamiento de {lote.lote_origen}. {siguiente}'
            self.siguiente.config(text=siguiente)
            self.actualizado.config(text='Última actualización: ' + datetime.fromisoformat(lote.actualizado_en).strftime('%d/%m/%Y %H:%M:%S'))
        politica = self.politica(lote, self.demo.get())
        for accion, boton in (
            ('iniciar', self.btn_iniciar), ('detener', self.btn_detener),
            ('reprocesar', self.btn_reprocesar),
            ('exportar', self.btn_exportar), ('revision', self.btn_revisar),
            ('incidencias', self.btn_incidencias), ('resumen', self.btn_resumen),
        ):
            boton.configure(state='normal' if politica[accion] else 'disabled')
        self.btn_nueva_migracion.configure(
            state='normal' if politica.get('nueva_migracion', False) else 'disabled',
        )
        solicitada = politica['detencion_solicitada']
        self.btn_detener.configure(text='Deteniendo…' if solicitada else 'Detener migración')
        if solicitada:
            self.siguiente.configure(text='Detención solicitada. Se terminará la ficha u operación en curso antes de guardar el último avance.')

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
        tamano_pagina = 50
        try:
            registros = self.revisar(lote.id, 0, tamano_pagina)
        except Exception as exc:
            messagebox.showerror(
                'No se pudieron consultar los registros', str(exc), parent=self,
            )
            return

        ventana = tk.Toplevel(self)
        ventana.title(f'Revisión de registros · {lote.id}')
        ventana.geometry('1120x720')
        ventana.minsize(850, 560)
        ventana.transient(self.winfo_toplevel())
        ventana.columnconfigure(0, weight=1)
        ventana.rowconfigure(1, weight=1)
        ttk.Label(
            ventana,
            text=f'{lote.id} · {os.path.basename(lote.fuente)}',
            style='Titulo.Panel.TLabel',
        ).grid(row=0, column=0, sticky='w', padx=16, pady=(14, 4))

        area = ttk.Panedwindow(ventana, orient='horizontal')
        area.grid(row=1, column=0, sticky='nsew', padx=12, pady=8)
        listado = ttk.Frame(area, padding=10, style='Tarjeta.TFrame')
        detalle = ttk.Frame(area, padding=10, style='Tarjeta.TFrame')
        area.add(listado, weight=2)
        area.add(detalle, weight=3)
        listado.columnconfigure(0, weight=1)
        listado.rowconfigure(1, weight=1)
        detalle.columnconfigure(0, weight=1)
        detalle.rowconfigure(1, weight=1)

        ttk.Label(
            listado, text='Registros MARC21', style='Nombre.TLabel',
        ).grid(row=0, column=0, sticky='w', pady=(0, 8))
        lista_registros = ttk.Treeview(
            listado, columns=('ficha', 'estado', 'control'),
            show='headings', selectmode='browse', style='Lotes.Treeview',
        )
        for columna, titulo, ancho in (
            ('ficha', 'Ficha Access', 100),
            ('estado', 'Estado', 90),
            ('control', 'MARC 001', 130),
        ):
            lista_registros.heading(columna, text=titulo)
            lista_registros.column(columna, width=ancho, minwidth=75, anchor='w')
        lista_registros.grid(row=1, column=0, sticky='nsew')
        scroll_registros = ttk.Scrollbar(
            listado, orient='vertical', command=lista_registros.yview,
        )
        scroll_registros.grid(row=1, column=1, sticky='ns')
        lista_registros.configure(yscrollcommand=scroll_registros.set)

        lbl_registro = ttk.Label(
            detalle, text='Selecciona un registro para revisar sus campos.',
            style='Nombre.TLabel',
        )
        lbl_registro.grid(row=0, column=0, sticky='w', pady=(0, 8))
        lbl_aviso_registro = ttk.Label(
            detalle, text='', style='Tarjeta.TLabel', wraplength=680,
        )
        lbl_aviso_registro.grid(row=1, column=0, sticky='w', pady=(0, 6))
        vistas_detalle = ttk.Notebook(detalle)
        vistas_detalle.grid(row=2, column=0, sticky='nsew')
        marco_campos = ttk.Frame(vistas_detalle, padding=8)
        marco_ejemplares = ttk.Frame(vistas_detalle, padding=8)
        marco_xml = ttk.Frame(vistas_detalle, padding=8)
        vistas_detalle.add(marco_campos, text='Campos MARC21')
        vistas_detalle.add(marco_ejemplares, text='Ejemplares')
        vistas_detalle.add(marco_xml, text='MARCXML')
        for marco in (marco_campos, marco_ejemplares, marco_xml):
            marco.columnconfigure(0, weight=1)
        marco_campos.rowconfigure(0, weight=1)
        marco_ejemplares.rowconfigure(1, weight=1)
        marco_xml.rowconfigure(0, weight=1)

        tabla_campos = ttk.Treeview(
            marco_campos, columns=('etiqueta', 'indicadores', 'contenido'),
            show='headings', style='Lotes.Treeview',
        )
        for columna, titulo, ancho in (
            ('etiqueta', 'Campo', 75),
            ('indicadores', 'Indicadores', 90),
            ('contenido', 'Contenido / subcampos', 540),
        ):
            tabla_campos.heading(columna, text=titulo)
            tabla_campos.column(
                columna, width=ancho, minwidth=65, anchor='w',
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

        columnas_ejemplar = (
            'codigo', 'biblioteca', 'sucursal', 'volumen', 'numero',
            'tomo', 'accesible', 'fecha', 'signatura',
        )
        tabla_ejemplares = ttk.Treeview(
            marco_ejemplares, columns=columnas_ejemplar,
            show='headings', style='Lotes.Treeview',
        )
        lbl_estado_ejemplares = ttk.Label(
            marco_ejemplares, text='', style='Panel.TLabel', wraplength=700,
        )
        lbl_estado_ejemplares.grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 7),
        )
        titulos_ejemplar = (
            'Núm. adquisición', 'Biblioteca', 'Sucursal Koha', 'Volumen',
            'Ejemplar', 'Tomo', 'Accesible', 'Fecha ingreso', 'Signatura',
        )
        for columna, titulo in zip(columnas_ejemplar, titulos_ejemplar):
            tabla_ejemplares.heading(columna, text=titulo)
            tabla_ejemplares.column(
                columna, width=105, minwidth=75, anchor='w',
                stretch=columna in ('codigo', 'sucursal', 'signatura'),
            )
        tabla_ejemplares.grid(row=1, column=0, sticky='nsew')
        scroll_ejemplares = ttk.Scrollbar(
            marco_ejemplares, orient='vertical', command=tabla_ejemplares.yview,
        )
        scroll_ejemplares.grid(row=1, column=1, sticky='ns')
        scroll_ejemplares_x = ttk.Scrollbar(
            marco_ejemplares, orient='horizontal', command=tabla_ejemplares.xview,
        )
        scroll_ejemplares_x.grid(row=2, column=0, sticky='ew')
        tabla_ejemplares.configure(
            yscrollcommand=scroll_ejemplares.set,
            xscrollcommand=scroll_ejemplares_x.set,
        )

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

        barra = ttk.Frame(ventana, padding=(12, 4, 12, 12))
        barra.grid(row=2, column=0, sticky='ew')
        barra.columnconfigure(1, weight=1)
        estado_pagina = ttk.Label(barra, style='Panel.TLabel')
        estado_pagina.grid(row=0, column=1, sticky='ew', padx=8)
        inicio_pagina = 0
        registros_actuales = []
        registro_seleccionado = [None]

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
            lbl_registro.config(
                text=f'Ficha {registro["id_ficha_acceso"]} · '
                     f'MARC 001: {registro.get("id_control") or "Sin valor"} · '
                     f'{registro.get("estado") or "Sin estado"}',
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
                lbl_aviso_registro.config(text='')
                messagebox.showerror(
                    'Registro MARC inválido', str(exc), parent=ventana,
                )
                return
            lbl_aviso_registro.config(
                text=aviso, foreground='#a36d23' if aviso else '#686168',
            )
            if aviso and self.politica(
                    lote, self.demo.get()).get('proponer_correccion'):
                boton_reparar.configure(state='normal')
            for campo in campos:
                tabla_campos.insert(
                    '', 'end',
                    values=(campo['etiqueta'], campo['indicadores'], campo['contenido']),
                )
            ejemplares = registro.get('ejemplares', [])
            recuperados_marc = False
            if not ejemplares:
                try:
                    ejemplares = ejemplares_desde_registro_marc(registro)
                    recuperados_marc = bool(ejemplares)
                except ValueError as exc:
                    lbl_estado_ejemplares.config(
                        text=f'No se pudieron consultar ejemplares: {exc}',
                        foreground='#a36d23',
                    )
            if recuperados_marc:
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
            for ejemplar in ejemplares:
                tabla_ejemplares.insert(
                    '', 'end',
                    values=tuple(
                        ejemplar.get(clave) if ejemplar.get(clave) is not None else ''
                        for clave in (
                            'num_adqui', 'biblioteca', 'branch_koha', 'volumen',
                            'ejemplar', 'tomo', 'accesible', 'fecha_ingreso',
                            'signatura',
                        )
                    ),
                )
            texto_xml.configure(state='normal')
            texto_xml.delete('1.0', tk.END)
            texto_xml.insert('1.0', registro['marca_marcxml'])
            texto_xml.configure(state='disabled')

        def registrar_observacion():
            registro = registro_seleccionado[0]
            if (registro is None or not self.politica(
                    lote, self.demo.get()).get('registrar_observacion')):
                return
            dialogo = tk.Toplevel(ventana)
            dialogo.title(
                f'Observaciones · ficha {registro["id_ficha_acceso"]}',
            )
            dialogo.geometry('760x510')
            dialogo.minsize(620, 420)
            dialogo.transient(ventana)
            dialogo.columnconfigure(0, weight=1)
            dialogo.rowconfigure(1, weight=1)
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
                    stretch=columna == 'nota', anchor='w',
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
                botones_observacion, text='Cerrar',
                command=dialogo.destroy,
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
                record = record_desde_iso2709(registro.get('marca_iso2709'))
                marcxml, iso2709 = serializar_registro(record)
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

            editor = tk.Toplevel(ventana)
            editor.title(f'Proponer corrección · ficha {registro["id_ficha_acceso"]}')
            editor.geometry('1120x700')
            editor.minsize(900, 600)
            editor.transient(ventana)
            editor.grab_set()
            editor.columnconfigure(0, weight=1)
            editor.rowconfigure(2, weight=1)
            ttk.Label(
                editor,
                text='Agrega o corrige campos MARC. El cambio no se guarda en MySQL '
                     'hasta que Aprobación lo autorice.',
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
                columns=('tag', 'indicadores', 'contenido'),
                show='headings', style='Lotes.Treeview',
            )
            for columna, titulo, ancho in (
                ('tag', 'Campo', 85), ('indicadores', 'Indicadores', 95),
                ('contenido', 'Contenido / subcampos', 820),
            ):
                tabla_edicion.heading(columna, text=titulo)
                tabla_edicion.column(
                    columna, width=ancho, minwidth=75,
                    stretch=columna == 'contenido', anchor='w',
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

            def presentar_campos(seleccionar=None):
                tabla_edicion.delete(*tabla_edicion.get_children())
                for indice, campo in enumerate(campos_editables):
                    if campo.is_control_field():
                        indicadores, contenido = '', campo.data or ''
                    else:
                        indicadores = ''.join(
                            indicador or '#' for indicador in campo.indicators
                        )
                        contenido = ' | '.join(
                            f'${subcampo.code} {subcampo.value}'
                            for subcampo in campo.subfields
                        )
                    tabla_edicion.insert(
                        '', 'end', iid=str(indice),
                        values=(campo.tag, indicadores, contenido),
                    )
                if seleccionar is not None and 0 <= seleccionar < len(campos_editables):
                    tabla_edicion.selection_set(str(seleccionar))

            def limpiar_formulario():
                tag_var.set('')
                indicadores_var.set('')
                contenido_editor.delete('1.0', tk.END)
                tabla_edicion.selection_remove(*tabla_edicion.selection())
                formulario_estado.config(text='')

            def seleccionar_campo(_evento=None):
                seleccion = tabla_edicion.selection()
                if not seleccion:
                    return
                campo = campos_editables[int(seleccion[0])]
                tag_var.set(campo.tag)
                if campo.is_control_field():
                    indicadores_var.set('')
                    contenido_editor.delete('1.0', tk.END)
                    contenido_editor.insert('1.0', campo.data or '')
                else:
                    indicadores_var.set(''.join(
                        indicador or '#' for indicador in campo.indicators
                    ))
                    contenido = ' | '.join(
                        f'${subcampo.code} {subcampo.value}'
                        for subcampo in campo.subfields
                    )
                    contenido_editor.delete('1.0', tk.END)
                    contenido_editor.insert('1.0', contenido)
                formulario_estado.config(
                    text='Edita los valores y pulsa «Actualizar campo».',
                )

            def campo_validado():
                return campo_desde_editor(
                    tag_var.get(), indicadores_var.get(),
                    contenido_editor.get('1.0', 'end-1c'),
                )

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
                    campo = campo_validado()
                except ValueError as exc:
                    messagebox.showerror('Campo no válido', str(exc), parent=editor)
                    return
                indice = int(seleccion[0])
                campos_editables[indice] = campo
                presentar_campos(indice)

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
            formulario_estado = ttk.Label(
                acciones_campo, style='Panel.TLabel',
            )
            formulario_estado.pack(side='left', padx=10)

            def enviar_propuesta():
                propuesta = Record(force_utf8=True)
                propuesta.leader = leader_var.get()
                propuesta.fields = list(campos_editables)
                try:
                    marcxml, iso2709 = serializar_registro(propuesta)
                    propuesta_id = self.proponer(
                        lote.id, registro['id_ficha_acceso'], marcxml, iso2709,
                        registro['huella_revision'],
                    )
                except Exception as exc:
                    messagebox.showerror(
                        'No se pudo proponer la corrección', str(exc), parent=editor,
                    )
                    return
                editor.destroy()
                messagebox.showinfo(
                    'Corrección pendiente',
                    f'La propuesta #{propuesta_id} quedó pendiente de revisión '
                    'por un usuario con perfil Aprobación. No se modificó aún el registro.',
                    parent=ventana,
                )
                cargar_pagina(inicio_pagina)

            barra_editor = ttk.Frame(editor, padding=(12, 6, 12, 12))
            barra_editor.grid(row=5, column=0, sticky='ew')
            ttk.Button(
                barra_editor, text='Cancelar', command=editor.destroy,
            ).pack(side='right')
            ttk.Button(
                barra_editor, text='Enviar a aprobación',
                style='Primary.TButton', command=enviar_propuesta,
            ).pack(side='right', padx=(0, 8))
            presentar_campos()

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

            revision = tk.Toplevel(ventana)
            revision.title(f'Correcciones pendientes · {lote.id}')
            revision.geometry('1180x690')
            revision.minsize(900, 520)
            revision.transient(ventana)
            revision.columnconfigure(0, weight=1)
            revision.rowconfigure(1, weight=1)
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
                propuesta_tabla.column(columna, width=ancho, anchor='w')
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
                    tabla.column(columna, width=ancho, anchor='w',
                                  stretch=columna == 'contenido')
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
                revision.destroy()
                self.actualizar(seleccionar=lote.id)
                cargar_pagina(inicio_pagina)

            propuesta_tabla.bind('<<TreeviewSelect>>', pintar_propuesta)
            botonera = ttk.Frame(revision, padding=12)
            botonera.grid(row=4, column=0, sticky='ew')
            ttk.Button(
                botonera, text='Cerrar', command=revision.destroy,
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

        def cargar_pagina(inicio):
            nonlocal inicio_pagina, registros_actuales
            try:
                registros_actuales = (
                    registros if inicio == 0
                    else self.revisar(lote.id, inicio, tamano_pagina)
                )
                if not registros_actuales:
                    raise ValueError('El lote no contiene registros para esta página.')
            except Exception as exc:
                messagebox.showerror(
                    'No se pudieron consultar los registros', str(exc),
                    parent=ventana,
                )
                return
            inicio_pagina = inicio
            lista_registros.delete(*lista_registros.get_children())
            for registro in registros_actuales:
                ficha = str(registro['id_ficha_acceso'])
                lista_registros.insert(
                    '', 'end', iid=ficha,
                    values=(
                        ficha, registro.get('estado') or '',
                        registro.get('id_control') or '',
                    ),
                )
            fin = inicio_pagina + len(registros_actuales)
            estado_pagina.config(
                text=f'Registros {inicio_pagina + 1:,}–{fin:,} de '
                     f'{lote.correctos:,} correctos',
            )
            boton_anterior.configure(
                state='normal' if inicio_pagina > 0 else 'disabled',
            )
            boton_siguiente.configure(
                state='normal' if fin < lote.correctos else 'disabled',
            )
            lista_registros.selection_set(str(registros_actuales[0]['id_ficha_acceso']))
            mostrar_registro()

        lista_registros.bind('<<TreeviewSelect>>', mostrar_registro)
        boton_anterior = ttk.Button(
            barra, text='← Anterior',
            command=lambda: cargar_pagina(max(0, inicio_pagina - tamano_pagina)),
        )
        boton_anterior.grid(row=0, column=0)
        politica_revision = self.politica(lote, self.demo.get())
        boton_observaciones = ttk.Button(
            barra, text='Observaciones',
            command=registrar_observacion,
            state='disabled',
        )
        boton_observaciones.grid(row=0, column=2, padx=(0, 6))
        boton_reparar = ttk.Button(
            barra, text='Proponer reparación XML',
            command=proponer_reparacion_xml, state='disabled',
        )
        boton_reparar.grid(row=0, column=3, padx=(0, 6))
        boton_editar = ttk.Button(
            barra, text='Corregir / proponer',
            command=editar_registro,
            state='normal' if politica_revision.get('proponer_correccion') else 'disabled',
        )
        boton_editar.grid(row=0, column=4, padx=(0, 6))
        boton_propuestas = ttk.Button(
            barra, text='Revisar propuestas',
            command=revisar_propuestas,
            state='normal' if politica_revision.get('aprobar_correccion') else 'disabled',
        )
        boton_propuestas.grid(row=0, column=5, padx=(0, 6))
        boton_siguiente = ttk.Button(
            barra, text='Siguiente →',
            command=lambda: cargar_pagina(inicio_pagina + tamano_pagina),
        )
        boton_siguiente.grid(row=0, column=6)
        ttk.Button(barra, text='Cerrar', command=ventana.destroy).grid(
            row=0, column=7, padx=(8, 0),
        )
        cargar_pagina(0)

    def _detener(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['detener']:
            self.detener(lote.id)

    def _reprocesar(self):
        lote = self.lote_actual()
        if lote and self.politica(lote, self.demo.get()).get('reprocesar'):
            self.reprocesar(lote.id)

    def _ventana_texto(self, titulo, contenido):
        ventana = tk.Toplevel(self)
        ventana.title(titulo)
        ventana.geometry('700x430')
        ventana.transient(self.winfo_toplevel())
        ventana.columnconfigure(0, weight=1)
        ventana.rowconfigure(0, weight=1)
        marco = ttk.Frame(ventana, padding=12)
        marco.grid(row=0, column=0, sticky='nsew')
        texto = tk.Text(marco, wrap='word', font=('Segoe UI', 10))
        texto.pack(side='left', fill='both', expand=True)
        barra = ttk.Scrollbar(marco, command=texto.yview)
        barra.pack(side='right', fill='y')
        texto.configure(yscrollcommand=barra.set)
        texto.insert('1.0', contenido)
        texto.configure(state='disabled')
        ttk.Button(ventana, text='Cerrar', command=ventana.destroy).grid(row=1, column=0, pady=(0, 12))

    def _incidencias(self):
        lote = self.lote_actual()
        if lote and self.politica(lote, self.demo.get())['incidencias']:
            detalle = '\n\n'.join(f'{item["referencia"]}\n{item["mensaje"]}' for item in lote.incidencias)
            self._ventana_texto(f'Incidencias · {lote.id}', f'{lote.errores} registros con error. Se conservan hasta 100 incidencias recientes.\n\n{detalle}')

    def _actividad(self):
        lote = self.lote_actual()
        if lote:
            self._ventana_texto(f'Actividad · {lote.id}', '\n\n'.join(f'{item["fecha"]}\n{item["mensaje"]}' for item in reversed(lote.actividad)))

    def _resumen(self):
        lote = self.lote_actual()
        if not lote or not self.politica(lote, self.demo.get())['resumen']:
            return
        ruta = filedialog.asksaveasfilename(parent=self, title='Guardar resumen del lote', initialfile=f'{"EJEMPLO-" if self.demo.get() else ""}{lote.id}.json', defaultextension='.json', filetypes=[('Resumen JSON', '*.json')])
        if not ruta:
            return
        try:
            with open(ruta, 'w', encoding='utf-8') as archivo:
                json.dump({'demostracion': self.demo.get(), 'lote': asdict(lote), 'procesados': lote.procesados, 'pendientes': lote.pendientes, 'progreso': lote.progreso}, archivo, ensure_ascii=False, indent=2)
            messagebox.showinfo('Resumen guardado', 'Se guardó el reporte de seguimiento del lote.', parent=self)
        except OSError as exc:
            messagebox.showerror('No se pudo guardar', str(exc), parent=self)
