"""Sistema de diseno NexoMARC.

Centraliza paleta de colores, tipografia, espaciado y componentes reutilizables
para que toda la aplicacion comparta un mismo lenguaje visual sin duplicar
definiciones de estilo en cada pantalla.
"""
from tkinter import ttk
import tkinter as tk


# ---------------------------------------------------------------------------
# Paleta de colores
# ---------------------------------------------------------------------------
# Tonos guinda (marca principal) y variantes
PRIMARIO = '#6d0c2e'          # Acciones principales, marca
PRIMARIO_HOVER = '#8e2a50'    # Estado hover de botones primarios
PRIMARIO_ACTIVO = '#4a0822'   # Estado presionado / seleccionado
PRIMARIO_SUAVE = '#f3e8ec'    # Fondos de estado primario suave

# Fondo y superficies
FONDO = '#f7f5f2'             # Fondo general de la aplicacion
SUPERFICIE = '#ffffff'        # Tarjetas, paneles, modales
SUPERFICIE_ALT = '#f1eeec'    # Superficie secundaria (listas, inputs deshabilitados)
BORDE = '#e8e2de'             # Bordes suaves de tarjetas y campos
BORDE_ENFOQUE = '#6d0c2e'     # Borde cuando un campo tiene el foco

# Texto
TEXTO = '#302a31'             # Texto principal (alto contraste)
TEXTO_SECUNDARIO = '#777078'  # Texto secundario, etiquetas de campo
TEXTO_MUTADO = '#a89ea3'      # Texto deshabilitado o de ayuda
TEXTO_INVERSO = '#ffffff'     # Texto sobre fondos oscuros

# Estados semanticos
EXITO = '#367963'
EXITO_SUAVE = '#e8f2ed'
ADVERTENCIA = '#a36d23'
ADVERTENCIA_SUAVE = '#f7eada'
ERROR = '#956c42'
ERROR_SUAVE = '#f5edea'
INFO = '#477bbb'
INFO_SUAVE = '#eef2f8'

# Barra lateral
BARRA_LATERAL = '#39232f'
BARRA_LATERAL_HOVER = '#503443'
BARRA_LATERAL_ACTIVA = '#654052'
BARRA_LATERAL_MUTADO = '#c5b7bf'


# ---------------------------------------------------------------------------
# Tipografia
# ---------------------------------------------------------------------------
FUENTE = 'Segoe UI'
FUENTE_MONO = 'Consolas'

TAM_TITULO_PAGINA = 20
TAM_SUBTITULO_PAGINA = 11
TAM_TARJETA_TITULO = 13
TAM_CAMPO_ETIQUETA = 9
TAM_CAMPO_ENTRADA = 10
TAM_CUERPO = 10
TAM_BOTON = 10
TAM_TABLA_ENCABEZADO = 9
TAM_TABLA_CUERPO = 9
TAM_METRICA_VALOR = 16
TAM_METRICA_ETIQUETA = 9


# ---------------------------------------------------------------------------
# Espaciado (sistema de 8px)
# ---------------------------------------------------------------------------
ESPACIO_XS = 4
ESPACIO_S = 8
ESPACIO_M = 16
ESPACIO_L = 24
ESPACIO_XL = 32


# ---------------------------------------------------------------------------
# Estilos ttk
# ---------------------------------------------------------------------------
def instalar_estilos(raiz: tk.Tk) -> ttk.Style:
    """Configura y devuelve el estilo ttk de la aplicacion."""
    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use('clam')
    except tk.TclError:
        pass

    fuente = (FUENTE, TAM_CUERPO)

    # Base
    estilo.configure('.', font=fuente, foreground=TEXTO, background=FONDO)
    estilo.configure('TFrame', background=FONDO)
    estilo.configure('App.TFrame', background=FONDO)
    estilo.configure('Panel.TFrame', background=FONDO)
    estilo.configure('Tarjeta.TFrame', background=SUPERFICIE)

    # Labels
    estilo.configure('TLabel', background=FONDO, foreground=TEXTO, font=fuente)
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
    estilo.configure('Field.TLabel', background=SUPERFICIE, foreground=TEXTO_SECUNDARIO,
                     font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'))

    # Encabezados de pagina
    estilo.configure('AppTitle.TLabel', background=FONDO, foreground=TEXTO,
                     font=(FUENTE, TAM_TITULO_PAGINA, 'bold'))
    estilo.configure('PageTitle.TLabel', background=FONDO, foreground=TEXTO,
                     font=(FUENTE, TAM_TITULO_PAGINA, 'bold'))
    estilo.configure('PageSubtitle.TLabel', background=FONDO, foreground=TEXTO_SECUNDARIO,
                     font=(FUENTE, TAM_SUBTITULO_PAGINA))

    # Entradas
    estilo.configure('TEntry', fieldbackground=SUPERFICIE, foreground=TEXTO,
                     bordercolor=BORDE, lightcolor=BORDE_ENFOQUE, darkcolor=BORDE_ENFOQUE,
                     padding=(8, 7), font=(FUENTE, TAM_CAMPO_ENTRADA))
    estilo.map('TEntry', bordercolor=[('focus', BORDE_ENFOQUE), ('!focus', BORDE)])

    # Botones
    estilo.configure('TButton', font=(FUENTE, TAM_BOTON, 'bold'), padding=(12, 8),
                     background=SUPERFICIE_ALT, foreground=TEXTO, bordercolor=BORDE)
    estilo.map('TButton',
               background=[('active', SUPERFICIE), ('disabled', SUPERFICIE_ALT)],
               foreground=[('disabled', TEXTO_MUTADO)])

    estilo.configure('Primary.TButton', background=PRIMARIO, foreground=TEXTO_INVERSO,
                     bordercolor=PRIMARIO)
    estilo.map('Primary.TButton',
               background=[('active', PRIMARIO_HOVER), ('pressed', PRIMARIO_ACTIVO),
                           ('disabled', '#c8b7bd')],
               foreground=[('disabled', TEXTO_MUTADO)])

    estilo.configure('Secondary.TButton', background=PRIMARIO_SUAVE, foreground=PRIMARIO,
                     bordercolor=BORDE)
    estilo.map('Secondary.TButton',
               background=[('active', PRIMARIO), ('pressed', PRIMARIO_ACTIVO)],
               foreground=[('active', TEXTO_INVERSO), ('pressed', TEXTO_INVERSO)])

    estilo.configure('Quiet.TButton', background=FONDO, foreground=TEXTO_SECUNDARIO,
                     borderwidth=0, padding=(8, 6))
    estilo.map('Quiet.TButton', foreground=[('active', PRIMARIO)])

    estilo.configure('Peligro.TButton', background=ERROR, foreground=TEXTO_INVERSO,
                     bordercolor=ERROR)
    estilo.map('Peligro.TButton',
               background=[('active', '#b55a3c'), ('pressed', '#8c5338')],
               foreground=[('disabled', TEXTO_MUTADO)])

    # Separadores
    estilo.configure('TSeparator', background=BORDE)

    # Progressbar
    estilo.configure('Horizontal.TProgressbar', troughcolor=BORDE, background=PRIMARIO,
                     thickness=8, borderwidth=0)

    # Checkbutton / Radiobutton
    estilo.configure('TCheckbutton', background=FONDO, foreground=TEXTO, font=fuente)

    # Labelframe
    estilo.configure('TLabelframe', background=SUPERFICIE, bordercolor=BORDE,
                     relief='solid', borderwidth=1)
    estilo.configure('TLabelframe.Label', background=SUPERFICIE, foreground=TEXTO,
                     font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'))

    # Notebook (pestanas)
    estilo.configure('TNotebook', background=FONDO, borderwidth=0)
    estilo.configure('TNotebook.Tab', background=SUPERFICIE_ALT, foreground=TEXTO_SECUNDARIO,
                     font=(FUENTE, TAM_BOTON, 'bold'), padding=(16, 10), borderwidth=0)
    estilo.map('TNotebook.Tab',
               background=[('selected', SUPERFICIE), ('active', SUPERFICIE)],
               foreground=[('selected', TEXTO), ('active', TEXTO)])

    # Treeview (tablas)
    estilo.configure('Lotes.Treeview', background=SUPERFICIE, fieldbackground=SUPERFICIE,
                     foreground=TEXTO, rowheight=34, font=(FUENTE, TAM_TABLA_CUERPO),
                     bordercolor=BORDE, lightcolor=BORDE, darkcolor=BORDE)
    estilo.configure('Lotes.Treeview.Heading', background=SUPERFICIE_ALT,
                     foreground=TEXTO_SECUNDARIO, font=(FUENTE, TAM_TABLA_ENCABEZADO, 'bold'),
                     padding=(8, 9))
    estilo.map('Lotes.Treeview',
               background=[('selected', PRIMARIO_SUAVE)],
               foreground=[('selected', PRIMARIO)])

    # Progreso de lote
    estilo.configure('Lotes.Horizontal.TProgressbar', background=PRIMARIO,
                     troughcolor=BORDE, thickness=8)

    return estilo


# ---------------------------------------------------------------------------
# Componentes de ayuda
# ---------------------------------------------------------------------------
def tarjeta(parent, padding=(ESPACIO_M, ESPACIO_M), **kwargs):
    """Devuelve un Frame con estilo de tarjeta."""
    frame = ttk.Frame(parent, style='Tarjeta.TFrame', padding=padding, **kwargs)
    return frame


def seccion_tarjeta(parent, texto, padding=(ESPACIO_M, ESPACIO_M)):
    """LabelFrame con estilo de tarjeta para agrupar controles."""
    return ttk.LabelFrame(parent, text=f'  {texto}  ', padding=padding, style='Tarjeta.TFrame')


def campo_formulario(parent, texto, variable, ancho=30, show=None, estilo_label='Field.TLabel'):
    """Crea una etiqueta + entrada alineada horizontalmente."""
    fila = ttk.Frame(parent, style='App.TFrame')
    fila.columnconfigure(1, weight=1)
    ttk.Label(fila, text=texto, style=estilo_label).grid(
        row=0, column=0, sticky='w', padx=(0, 8), pady=ESPACIO_S)
    entrada = ttk.Entry(fila, textvariable=variable, width=ancho, show=show)
    entrada.grid(row=0, column=1, sticky='ew', pady=ESPACIO_S)
    return fila, entrada


def encabezado_pagina(parent, titulo, descripcion, estilo_pagina='App.TFrame'):
    """Encabezado estandar de cada pantalla: titulo + subtitulo."""
    contenedor = ttk.Frame(parent, style=estilo_pagina)
    contenedor.pack(fill='x', padx=ESPACIO_L, pady=(ESPACIO_L, ESPACIO_M))
    ttk.Label(contenedor, text=titulo, style='PageTitle.TLabel').pack(anchor='w')
    ttk.Label(
        contenedor, text=descripcion, style='PageSubtitle.TLabel',
        wraplength=950,
    ).pack(anchor='w', pady=(ESPACIO_S, 0))
    return contenedor


def boton_accion(parent, texto, comando, estilo='Primary.TButton', ancho=None, estado='normal'):
    """Botón de acción con estilo consistente."""
    return ttk.Button(
        parent, text=texto, command=comando, style=estilo, state=estado,
    )


def badge_estado(parent, texto, color, fondo=None):
    """Etiqueta tipo badge para estados."""
    return tk.Label(
        parent, text=texto, bg=fondo or SUPERFICIE, fg=color,
        font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'), padx=ESPACIO_M, pady=ESPACIO_XS,
    )


def mensaje_estado(parent, tipo, texto):
    """Devuelve un Frame con icono (texto) y mensaje segun el tipo semantico."""
    iconos = {
        'exito': ('✔', EXITO),
        'advertencia': ('⚠', ADVERTENCIA),
        'error': ('✖', ERROR),
        'info': ('ℹ', INFO),
    }
    icono, color = iconos.get(tipo, ('ℹ', INFO))
    frame = tk.Frame(parent, bg=SUPERFICIE)
    tk.Label(frame, text=icono, bg=SUPERFICIE, fg=color,
             font=(FUENTE, 12, 'bold')).pack(side='left', padx=(0, ESPACIO_S))
    tk.Label(frame, text=texto, bg=SUPERFICIE, fg=TEXTO,
             font=(FUENTE, TAM_CUERPO)).pack(side='left', anchor='w')
    return frame


def separador(parent, orient='horizontal', pady=ESPACIO_M, padx=0):
    """Separador visual consistente."""
    sep = ttk.Separator(parent, orient=orient)
    if orient == 'horizontal':
        sep.pack(fill='x', pady=pady, padx=padx)
    else:
        sep.pack(fill='y', padx=pady, pady=padx)
    return sep


# Colores de estado de lote (reutilizados en panel_lotes)
COLORES_ESTADO_LOTE = {
    'en_espera': {'texto': '#777078', 'fondo': '#edeef0'},
    'en_proceso': {'texto': '#6d0c2e', 'fondo': '#f3e8ec'},
    'concluido': {'texto': '#367963', 'fondo': '#e8f2ed'},
    'con_incidencias': {'texto': '#a36d23', 'fondo': '#f7eada'},
    'detenido': {'texto': '#956c42', 'fondo': '#f5edea'},
}
