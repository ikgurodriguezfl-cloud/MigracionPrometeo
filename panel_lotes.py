"""Panel Tkinter del sprint 2, integrado en el Notebook de MigracionApp."""
from dataclasses import asdict
from datetime import date, datetime, timedelta
import csv
from io import BytesIO
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from xml.etree import ElementTree

from lotes import ESTADOS, ETAPAS, lotes_de_ejemplo
from pymarc import MARCReader


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


class PanelLotes(ttk.Frame):
    def __init__(self, parent, listar, politica, iniciar, exportar, revisar,
                 conexiones, detener):
        super().__init__(parent, padding=16, style='Panel.TFrame')
        self.listar = listar
        self.politica = politica
        self.iniciar = iniciar
        self.exportar = exportar
        self.revisar = revisar
        self.conexiones = conexiones
        self.detener = detener
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
        ttk.Button(
            acciones_cabecera, text='Nueva migración', style='Primary.TButton',
            command=self.conexiones,
        ).pack(side='right')
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
            state='disabled' if self.demo.get() or not self.lotes else 'normal',
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
        if self.demo.get() or not self.lotes:
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
            self.siguiente.config(text=pasos[lote.estado])
            self.actualizado.config(text='Última actualización: ' + datetime.fromisoformat(lote.actualizado_en).strftime('%d/%m/%Y %H:%M:%S'))
        politica = self.politica(lote, self.demo.get())
        for accion, boton in (
            ('iniciar', self.btn_iniciar), ('detener', self.btn_detener),
            ('exportar', self.btn_exportar), ('revision', self.btn_revisar),
            ('incidencias', self.btn_incidencias), ('resumen', self.btn_resumen),
        ):
            boton.configure(state='normal' if politica[accion] else 'disabled')
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
            marco.rowconfigure(0, weight=1)

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
        titulos_ejemplar = (
            'Núm. adquisición', 'Biblioteca', 'Sucursal Koha', 'Volumen',
            'Ejemplar', 'Tomo', 'Accesible', 'Fecha ingreso', 'Signatura',
        )
        for columna, titulo in zip(columnas_ejemplar, titulos_ejemplar):
            tabla_ejemplares.heading(columna, text=titulo)
            tabla_ejemplares.column(columna, width=115, minwidth=75, anchor='w')
        tabla_ejemplares.grid(row=0, column=0, sticky='nsew')
        scroll_ejemplares = ttk.Scrollbar(
            marco_ejemplares, orient='vertical', command=tabla_ejemplares.yview,
        )
        scroll_ejemplares.grid(row=0, column=1, sticky='ns')
        scroll_ejemplares_x = ttk.Scrollbar(
            marco_ejemplares, orient='horizontal', command=tabla_ejemplares.xview,
        )
        scroll_ejemplares_x.grid(row=1, column=0, sticky='ew')
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
            lbl_registro.config(
                text=f'Ficha {registro["id_ficha_acceso"]} · '
                     f'MARC 001: {registro.get("id_control") or "Sin valor"} · '
                     f'{registro.get("estado") or "Sin estado"}',
            )
            tabla_campos.delete(*tabla_campos.get_children())
            tabla_ejemplares.delete(*tabla_ejemplares.get_children())
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
            for campo in campos:
                tabla_campos.insert(
                    '', 'end',
                    values=(campo['etiqueta'], campo['indicadores'], campo['contenido']),
                )
            for ejemplar in registro.get('ejemplares', []):
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
        boton_siguiente = ttk.Button(
            barra, text='Siguiente →',
            command=lambda: cargar_pagina(inicio_pagina + tamano_pagina),
        )
        boton_siguiente.grid(row=0, column=2)
        ttk.Button(barra, text='Cerrar', command=ventana.destroy).grid(
            row=0, column=3, padx=(8, 0),
        )
        cargar_pagina(0)

    def _detener(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['detener']:
            self.detener(lote.id)

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
