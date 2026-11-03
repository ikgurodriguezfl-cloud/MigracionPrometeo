"""Identidad institucional y geometría de las ventanas de Prometeo."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font, ttk

RECURSOS = Path(__file__).with_name('recursos')
GUINDA = '#721737'
FONDO = '#f5f4f1'
TINTA = '#302c31'


def aplicar_estilo(root):
    if sys.platform == 'win32' and not getattr(root, '_noto_cargada', False):
        import ctypes
        for peso in ('Regular', 'Bold'):
            ctypes.windll.gdi32.AddFontResourceExW(str(RECURSOS / f'NotoSans-{peso}.ttf'), 0x10, None)
        root._noto_cargada = True
    familia = 'Noto Sans' if 'Noto Sans' in font.families(root) else 'Segoe UI'
    for nombre in ('TkDefaultFont', 'TkTextFont', 'TkHeadingFont', 'TkMenuFont'):
        font.nametofont(nombre, root=root).configure(family=familia)
    estilo = ttk.Style(root)
    estilo.theme_use('clam')
    estilo.configure('.', font=(familia, 9), background=FONDO, foreground=TINTA)
    estilo.configure('TNotebook.Tab', padding=(8, 3))
    estilo.configure('Marca.TFrame', background='white')
    estilo.configure('Cifra.TLabel', background='white', foreground=GUINDA, font=(familia, 13, 'bold'))
    estilo.configure('Leyenda.TLabel', background='white', foreground='#504952', font=(familia, 8))
    estilo.configure('Titulo.TLabel', font=(familia, 15, 'bold'))
    estilo.configure('Principal.TButton', background=GUINDA, foreground='white', padding=(9, 4))
    estilo.map('Principal.TButton', background=[('disabled', '#dcd7d9'), ('active', '#59122b')],
               foreground=[('disabled', '#625b5d')])
    estilo.configure('TProgressbar', background=GUINDA, troughcolor='#e6e1e2')
    estilo.configure('Treeview', background='white', fieldbackground='white', rowheight=24)
    return familia


def logo(parent, nombre):
    imagen = tk.PhotoImage(master=parent, file=str(RECURSOS / nombre))
    etiqueta = tk.Label(parent, image=imagen, bg='white', borderwidth=0)
    etiqueta.image = imagen
    return etiqueta


def centrar(root, acceso=False):
    pantalla_x, pantalla_y = root.winfo_screenwidth(), root.winfo_screenheight()
    ancho = min(480 if acceso else max(460, pantalla_x // 2), pantalla_x - 24)
    alto = min(530 if acceso else int(pantalla_y * 0.84), pantalla_y - 80)
    root.minsize(min(ancho, 420), min(alto, 400))
    root.geometry(f'{ancho}x{alto}+{max(0,(pantalla_x-ancho)//2)}+{max(0,(pantalla_y-alto)//2-12)}')
    root.resizable(True, True)
