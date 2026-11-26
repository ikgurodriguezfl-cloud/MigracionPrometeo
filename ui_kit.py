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
PRIMARIO = '#6d0c2e'
PRIMARIO_HOVER = '#8e2a50'
PRIMARIO_ACTIVO = '#4a0822'
PRIMARIO_SUAVE = '#f3e8ec'

# Fondo y superficies
FONDO = '#f7f5f2'
SUPERFICIE = '#ffffff'
SUPERFICIE_ALT = '#f1eeec'
BORDE = '#e8e2de'
BORDE_ENFOQUE = '#6d0c2e'

# Texto
TEXTO = '#302a31'
TEXTO_SECUNDARIO = '#777078'
TEXTO_MUTADO = '#a89ea3'
TEXTO_INVERSO = '#ffffff'

# Estados semanticos
EXITO = '#367963'
EXITO_SUAVE = '#e8f2ed'
ADVERTENCIA = '#a36d23'
ADVERTENCIA_SUAVE = '#f7eada'
ERROR = '#956c42'
ERROR_SUAVE = '#f5edea'
INFO = '#477bbb'
INFO_SUAVE = '#eef2f8'

# Shell tipo aplicacion web.
NOCHE = '#171d2d'
NOCHE_ALT = '#222a3d'
NOCHE_BORDE = '#30394f'
BARRA_LATERAL = '#39232f'
BARRA_LATERAL_HOVER = '#503443'
BARRA_LATERAL_ACTIVA = '#654052'
BARRA_LATERAL_MUTADO = '#c5b7bf'
TARJETA_METRICA = ('#27334a', '#762040', '#17666a', '#51477e')
ACENTO_TEAL = '#26a69a'


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
    estilo.configure('Hero.TFrame', background=NOCHE)
    estilo.configure('HeroTitle.TLabel', background=NOCHE, foreground=TEXTO_INVERSO,
                     font=(FUENTE, 19, 'bold'))
    estilo.configure('HeroHint.TLabel', background=NOCHE, foreground='#c2c9d8',
                     font=(FUENTE, TAM_CAMPO_ETIQUETA))
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

    estilo.configure('Nav.TButton', background=BARRA_LATERAL, foreground='#d2d7e2',
                     borderwidth=0, anchor='w', padding=(14, 11),
                     font=(FUENTE, TAM_CUERPO))
    estilo.map('Nav.TButton',
               background=[('active', BARRA_LATERAL_HOVER), ('disabled', BARRA_LATERAL)],
               foreground=[('active', TEXTO_INVERSO), ('disabled', '#687287')])
    estilo.configure('NavActive.TButton', background=BARRA_LATERAL_ACTIVA,
                     foreground=TEXTO_INVERSO, borderwidth=0, anchor='w',
                     padding=(14, 11), font=(FUENTE, TAM_CUERPO, 'bold'))
    estilo.map('NavActive.TButton', background=[('active', BARRA_LATERAL_ACTIVA)])
    estilo.configure('HeroQuiet.TButton', background=SUPERFICIE_ALT,
                     foreground=TEXTO_SECUNDARIO, borderwidth=0, padding=(8, 6))
    estilo.map('HeroQuiet.TButton',
               background=[('active', '#313b52'), ('pressed', NOCHE)],
               foreground=[('disabled', '#8992a6')])

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
    estilo.map('TCheckbutton', foreground=[('active', PRIMARIO)])

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
    estilo.configure('Hero.Horizontal.TProgressbar', background=ACENTO_TEAL,
                     troughcolor=NOCHE_BORDE, thickness=10, borderwidth=0)

    return estilo


def instalar_color_personalizado(estilo: ttk.Style, colores=None):
    """Aplica las preferencias de color a los estilos compartidos de la app."""
    colores = colores or {}
    primario = colores.get('acento', PRIMARIO)
    lateral = colores.get('lateral', BARRA_LATERAL)
    fondo = colores.get('fondo', FONDO)
    superficie = colores.get('superficie', SUPERFICIE)
    boton = colores.get('boton', SUPERFICIE_ALT)
    def contraste(color):
        try:
            canales = [int(color[indice:indice + 2], 16) / 255 for indice in (1, 3, 5)]
            luminancia = sum(peso * (canal / 12.92 if canal <= .04045 else
                              ((canal + .055) / 1.055) ** 2.4)
                             for peso, canal in zip((.2126, .7152, .0722), canales))
            return TEXTO_INVERSO if luminancia < .42 else TEXTO
        except (TypeError, ValueError):
            return TEXTO
    texto_fondo = contraste(fondo)
    texto_superficie = contraste(superficie)
    for nombre in ('App.TFrame', 'Panel.TFrame', 'TFrame'):
        estilo.configure(nombre, background=fondo)
    estilo.configure('Tarjeta.TFrame', background=superficie)
    for nombre in ('TLabel', 'AppTitle.TLabel', 'PageTitle.TLabel',
                   'PageSubtitle.TLabel', 'Titulo.Panel.TLabel', 'Panel.TLabel'):
        estilo.configure(nombre, background=fondo, foreground=texto_fondo)
    for nombre in ('Tarjeta.TLabel', 'CardBody.TLabel', 'CardHint.TLabel',
                   'CardTitle.TLabel', 'CardMetric.TLabel', 'Field.TLabel',
                   'Nombre.TLabel', 'Numero.TLabel', 'Estado.TLabel',
                   'HeroTitle.TLabel', 'HeroHint.TLabel', 'TLabelframe.Label'):
        estilo.configure(nombre, background=superficie, foreground=texto_superficie)
    for nombre in ('HeroUser.TLabel', 'HeroMeta.TLabel', 'HeroRole.TLabel'):
        estilo.configure(nombre, background=lateral, foreground=contraste(lateral))
    for nombre in ('TEntry', 'TCombobox'):
        estilo.configure(nombre, fieldbackground=superficie, foreground=texto_superficie,
                         background=superficie)
    estilo.configure('TCheckbutton', background=fondo, foreground=texto_fondo)
    estilo.configure('TLabelframe', background=superficie)
    estilo.configure('TNotebook', background=fondo)
    estilo.configure('TNotebook.Tab', background=superficie, foreground=texto_superficie)
    estilo.map('TNotebook.Tab', background=[('selected', superficie), ('active', superficie)],
               foreground=[('selected', texto_superficie), ('active', texto_superficie)])
    estilo.configure('Revision.TNotebook', background=superficie)
    estilo.configure('Revision.TNotebook.Tab', background=superficie, foreground=texto_superficie)
    estilo.map('Revision.TNotebook.Tab',
               background=[('selected', superficie), ('active', superficie)],
               foreground=[('selected', primario), ('active', primario)])
    estilo.configure('TButton', background=boton, foreground=contraste(boton),
                     bordercolor=boton)
    estilo.map('TButton', background=[('active', primario), ('pressed', primario),
                                      ('disabled', boton)],
               foreground=[('active', contraste(primario)), ('pressed', contraste(primario)),
                           ('disabled', contraste(boton))])
    estilo.configure('Quiet.TButton', background=boton, foreground=contraste(boton))
    estilo.map('Quiet.TButton', background=[('active', primario), ('pressed', primario)],
               foreground=[('active', contraste(primario)), ('pressed', contraste(primario))])
    estilo.configure('HeroQuiet.TButton', background=boton, foreground=contraste(boton))
    estilo.map('HeroQuiet.TButton', background=[('active', primario), ('pressed', primario)],
               foreground=[('active', contraste(primario)), ('pressed', contraste(primario))])
    estilo.configure('Secondary.TButton', background=boton, foreground=contraste(boton),
                     bordercolor=boton)
    estilo.map('Secondary.TButton', background=[('active', primario), ('pressed', primario)],
               foreground=[('active', contraste(primario)), ('pressed', contraste(primario))])
    estilo.configure('RevisionAction.TButton', background=boton, foreground=contraste(boton))
    estilo.map('RevisionAction.TButton', background=[('active', primario), ('disabled', boton)],
               foreground=[('active', contraste(primario)), ('disabled', contraste(boton))])
    estilo.configure('Lotes.Treeview.Heading', background=superficie,
                     foreground=texto_superficie)
    estilo.configure('DemoNotice.TLabel', background=superficie, foreground=texto_superficie)
    estilo.configure('Lotes.Treeview', foreground=texto_superficie)
    estilo.configure('Tarjeta.TFrame', background=superficie)
    estilo.configure('App.TFrame', background=fondo)
    estilo.configure('TSeparator', background=superficie)
    estilo.configure('Horizontal.TProgressbar', troughcolor=superficie, background=primario)
    estilo.configure('Lotes.Horizontal.TProgressbar', troughcolor=superficie, background=primario)
    estilo.configure('Hero.Horizontal.TProgressbar', troughcolor=lateral, background=primario)
    estilo.configure('Primary.TButton', background=primario, foreground=contraste(primario),
                     bordercolor=primario)
    estilo.map('Primary.TButton', background=[('active', primario), ('pressed', primario)],
               foreground=[('active', contraste(primario)), ('pressed', contraste(primario))])
    estilo.configure('Secondary.TButton', foreground=contraste(boton))
    estilo.map('Secondary.TButton', foreground=[('active', contraste(primario)),
                                                 ('pressed', contraste(primario))])
    estilo.configure('CardMetric.TLabel', foreground=primario)
    estilo.configure('Numero.TLabel', foreground=primario)
    estilo.configure('Estado.TLabel', foreground=primario)
    estilo.configure('Horizontal.TProgressbar', background=primario)
    estilo.configure('Lotes.Horizontal.TProgressbar', background=primario)
    estilo.map('Lotes.Treeview',
               background=[('selected', primario)],
               foreground=[('selected', contraste(primario))])
    estilo.configure('Nav.TButton', background=lateral, foreground=contraste(lateral))
    estilo.configure('NavActive.TButton', background=lateral, foreground=contraste(lateral))


# ---------------------------------------------------------------------------
# Componentes de ayuda
# ---------------------------------------------------------------------------
def tarjeta(parent, padding=(ESPACIO_M, ESPACIO_M), **kwargs):
    """Devuelve un Frame con estilo de tarjeta."""
    frame = ttk.Frame(parent, style='Tarjeta.TFrame', padding=padding, **kwargs)
    return frame


def crear_icono(parent, nombre, color=TEXTO_SECUNDARIO, size=20, fondo=None):
    """Dibuja iconos vectoriales sencillos en un Canvas, sin recursos externos."""
    fondo = fondo or SUPERFICIE
    lienzo = tk.Canvas(
        parent, width=size, height=size, background=fondo,
        highlightthickness=0, borderwidth=0,
    )
    escala = size / 24
    grosor = max(1.4, size / 10)

    def puntos(coordenadas):
        return tuple(valor * escala for valor in coordenadas)

    def linea(coordenadas, cerrar=False):
        coords = puntos(coordenadas)
        if cerrar:
            lienzo.create_polygon(
                *coords, fill='', outline=color, width=grosor,
                joinstyle='round', tags=('icono', 'contorno'),
            )
        else:
            lienzo.create_line(
                *coords, fill=color, width=grosor,
                capstyle='round', joinstyle='round', tags=('icono', 'trazo'),
            )

    def oval(x1, y1, x2, y2, relleno=''):
        lienzo.create_oval(
            *puntos((x1, y1, x2, y2)), outline=color,
            fill=relleno, width=grosor,
            tags=('icono', 'contorno', 'fondo_icono')
            if relleno else ('icono', 'contorno'),
        )

    def rectangulo(x1, y1, x2, y2):
        lienzo.create_rectangle(
            *puntos((x1, y1, x2, y2)), outline=color,
            width=grosor, tags=('icono', 'contorno'),
        )

    iconos = {
        'home': lambda: (
            linea((3, 11, 12, 4, 21, 11)),
            linea((6, 10, 6, 20, 18, 20, 18, 10)),
            linea((10, 20, 10, 14, 14, 14, 14, 20)),
        ),
        'connect': lambda: (
            linea((8, 3, 8, 8, 16, 8, 16, 3)),
            linea((5, 8, 5, 13, 19, 13, 19, 8)),
            linea((12, 13, 12, 20)),
            linea((9, 20, 15, 20)),
        ),
        'database': lambda: (
            oval(4, 3, 20, 9),
            linea((4, 6, 4, 18)),
            linea((20, 6, 20, 18)),
            linea((4, 12, 6, 14, 12, 15, 18, 14, 20, 12)),
            linea((4, 18, 6, 20, 12, 21, 18, 20, 20, 18)),
        ),
        'settings': lambda: (
            linea((4, 6, 20, 6)), linea((4, 12, 20, 12)),
            linea((4, 18, 20, 18)), oval(8, 4, 12, 8, fondo),
            oval(14, 10, 18, 14, fondo), oval(6, 16, 10, 20, fondo),
        ),
        'play': lambda: linea((7, 4, 19, 12, 7, 20), cerrar=True),
        'check': lambda: linea((4, 12, 10, 18, 20, 6)),
        'activity': lambda: (
            linea((3, 19, 8, 13, 12, 16, 19, 6)),
            linea((15, 6, 19, 6, 19, 10)),
        ),
        'users': lambda: (
            oval(8, 3, 15, 10),
            linea((4, 20, 5, 16, 8, 13, 15, 13, 18, 16, 19, 20)),
            oval(2, 6, 7, 11),
            linea((2, 19, 3, 16, 6, 14)),
        ),
        'logout': lambda: (
            rectangulo(3, 4, 12, 20),
            linea((9, 12, 21, 12, 17, 8)),
            linea((21, 12, 17, 16)),
        ),
        'refresh': lambda: (
            linea((19, 8, 19, 4, 15, 4)),
            linea((19, 5, 15, 4, 12, 3, 8, 4, 5, 7, 4, 12, 5, 17, 9, 20, 14, 20, 18, 17)),
            linea((5, 16, 5, 20, 9, 20)),
        ),
        'download': lambda: (
            linea((12, 3, 12, 15, 7, 10)),
            linea((12, 15, 17, 10)),
            linea((4, 17, 4, 21, 20, 21, 20, 17)),
        ),
        'plus': lambda: (linea((12, 4, 12, 20)), linea((4, 12, 20, 12))),
        'chart': lambda: (
            linea((4, 20, 4, 4)), linea((4, 20, 21, 20)),
            rectangulo(7, 13, 10, 20), rectangulo(12, 9, 15, 20),
            rectangulo(17, 5, 20, 20),
        ),
        'search': lambda: (oval(3, 3, 15, 15), linea((14, 14, 21, 21))),
        'file': lambda: (
            rectangulo(5, 3, 16, 21), linea((8, 9, 13, 9)),
            linea((8, 13, 13, 13)), linea((8, 17, 13, 17)),
            linea((16, 3, 20, 7, 20, 17)),
        ),
    }
    if nombre not in iconos:
        raise ValueError(f'Icono no reconocido: {nombre}')
    iconos[nombre]()
    lienzo.icon_name = nombre
    return lienzo


def colorear_icono(lienzo, color, fondo=None):
    fondo = fondo or lienzo.cget('background')
    lienzo._color_icono_paleta = color
    lienzo.configure(background=fondo)
    lienzo.itemconfigure('trazo', fill=color)
    lienzo.itemconfigure('contorno', outline=color)
    lienzo.itemconfigure('fondo_icono', fill=fondo)


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


def encabezado_pagina(
    parent, titulo, descripcion, estilo_pagina='App.TFrame', icono='file',
):
    """Encabezado compacto con icono, titulo y una linea de contexto."""
    contenedor = ttk.Frame(parent, style=estilo_pagina)
    contenedor.pack(
        fill='x', padx=ESPACIO_L, pady=(ESPACIO_L, ESPACIO_M),
    )
    crear_icono(
        contenedor, icono, color=PRIMARIO, size=20, fondo=FONDO,
    ).pack(side='left', padx=(0, ESPACIO_S))
    texto = ttk.Frame(contenedor, style=estilo_pagina)
    texto.pack(side='left', fill='x', expand=True)
    ttk.Label(texto, text=titulo, style='PageTitle.TLabel').pack(anchor='w')
    ttk.Label(
        texto, text=descripcion, style='PageSubtitle.TLabel',
        wraplength=1100,
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


def preparar_ventana(ventana, titulo, geometria, minimo, padre, modal=False):
    """Aplica las dimensiones, el fondo y el centrado comunes a ventanas auxiliares."""
    ventana.title(titulo)
    ventana.geometry(geometria)
    ventana.minsize(*minimo)
    ventana.configure(background=FONDO)
    ventana.transient(padre)
    ventana.update_idletasks()
    ancho = ventana.winfo_width()
    alto = ventana.winfo_height()
    x = padre.winfo_rootx() + max(0, (padre.winfo_width() - ancho) // 2)
    y = padre.winfo_rooty() + max(0, (padre.winfo_height() - alto) // 2)
    ventana.geometry(f'{ancho}x{alto}+{x}+{y}')
    if modal:
        ventana.grab_set()
    return ventana


def animar_valor(widget, destino, duracion=180):
    """Interpola suavemente una barra de progreso sin bloquear la interfaz."""
    destino = max(0.0, min(float(widget.cget('maximum')), float(destino)))
    inicio = float(widget.cget('value'))
    anterior = getattr(widget, '_animacion_valor_id', None)
    if anterior is not None:
        try:
            widget.after_cancel(anterior)
        except tk.TclError:
            pass
    pasos = max(1, duracion // 16)

    def cancelar(_evento=None):
        identificador = getattr(widget, '_animacion_valor_id', None)
        if identificador is not None:
            try:
                widget.after_cancel(identificador)
            except tk.TclError:
                pass
            widget._animacion_valor_id = None

    if not getattr(widget, '_animacion_valor_destroy_bind', False):
        widget.bind('<Destroy>', cancelar, add='+')
        widget._animacion_valor_destroy_bind = True

    def avanzar(paso=1):
        if not widget.winfo_exists():
            return
        proporcion = min(1.0, paso / pasos)
        suave = 1 - (1 - proporcion) ** 3
        widget.configure(value=inicio + (destino - inicio) * suave)
        if proporcion < 1:
            widget._animacion_valor_id = widget.after(
                16, avanzar, paso + 1,
            )
        else:
            widget._animacion_valor_id = None

    avanzar()


# Colores de estado de lote (reutilizados en panel_lotes)
COLORES_ESTADO_LOTE = {
    'en_espera': {'texto': '#687287', 'fondo': '#e6eaf1'},
    'en_proceso': {'texto': PRIMARIO, 'fondo': PRIMARIO_SUAVE},
    'concluido': {'texto': EXITO, 'fondo': EXITO_SUAVE},
    'con_incidencias': {'texto': ADVERTENCIA, 'fondo': ADVERTENCIA_SUAVE},
    'detenido': {'texto': ERROR, 'fondo': ERROR_SUAVE},
}
