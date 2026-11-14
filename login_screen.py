"""Pantalla de inicio de sesion con diseno renovado (UI/UX)."""
import tkinter as tk
from tkinter import messagebox, ttk
from auth import AuthenticationService

from ui_kit import (
    FONDO, SUPERFICIE, TEXTO, TEXTO_SECUNDARIO, TEXTO_MUTADO, TEXTO_INVERSO,
    PRIMARIO, PRIMARIO_HOVER, PRIMARIO_SUAVE, BORDE, BORDE_ENFOQUE,
    FUENTE, TAM_CUERPO, ESPACIO_XS, ESPACIO_S, ESPACIO_M, ESPACIO_L, ESPACIO_XL,
    instalar_estilos, tarjeta, encabezado_pagina, separador,
)


class LoginScreen:
    def __init__(self, root: tk.Tk, auth_service: AuthenticationService, on_login_success):
        self.root = root
        self.auth_service = auth_service
        self.on_login_success = on_login_success

        self.root.title('NexoMARC | Iniciar sesión')
        self.root.geometry('960x640')
        self.root.minsize(800, 580)
        self.root.resizable(True, True)
        self.root.configure(background=FONDO)

        instalar_estilos(self.root)
        self._crear_interfaz()

    def _crear_interfaz(self):
        # Fondo de marca a la izquierda
        contenedor = tk.Frame(self.root, bg=FONDO)
        contenedor.pack(fill='both', expand=True)
        contenedor.grid_columnconfigure(0, weight=1, minsize=320)
        contenedor.grid_columnconfigure(1, weight=2, minsize=520)
        contenedor.grid_rowconfigure(0, weight=1)

        marca = tk.Frame(contenedor, bg=PRIMARIO, padx=48, pady=46)
        marca.grid(row=0, column=0, sticky='nsew')

        tk.Label(
            marca, text='NexoMARC', bg=PRIMARIO, fg=TEXTO_INVERSO,
            font=(FUENTE, 13, 'bold'),
        ).pack(anchor='w')

        tk.Frame(marca, bg=PRIMARIO_HOVER, height=2, width=48).pack(
            anchor='w', pady=(54, 28),
        )
        tk.Label(
            marca, text='Tu catálogo\nbibliográfico, listo.',
            bg=PRIMARIO, fg=TEXTO_INVERSO, justify='left', anchor='w',
            font=(FUENTE, 28, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            marca,
            text='Prepara tu información bibliográfica\npara trabajar con Koha.',
            bg=PRIMARIO, fg='#e8dce1', justify='left', anchor='w',
            font=(FUENTE, 11), pady=18,
        ).pack(anchor='w')

        # Panel de acceso a la derecha
        acceso = tk.Frame(contenedor, bg=SUPERFICIE)
        acceso.grid(row=0, column=1, sticky='nsew')
        acceso.grid_columnconfigure(0, weight=1)
        acceso.grid_rowconfigure(0, weight=1)

        formulario = tarjeta(acceso, padding=(ESPACIO_XL, ESPACIO_XL))
        formulario.place(relx=0.5, rely=0.5, anchor='center')

        # Cabecera del formulario
        encabezado = ttk.Frame(formulario, style='Tarjeta.TFrame')
        encabezado.pack(fill='x', pady=(0, ESPACIO_L))

        ttk.Label(
            encabezado, text='INICIO DE SESIÓN', style='Field.TLabel',
        ).pack(anchor='w', pady=(0, ESPACIO_S))
        ttk.Label(
            encabezado, text='¡Bienvenido de nuevo!',
            font=(FUENTE, 24, 'bold'), foreground=TEXTO, background=SUPERFICIE,
        ).pack(anchor='w', pady=(0, ESPACIO_S))
        ttk.Label(
            encabezado, text='Ingresa tus datos para continuar.',
            font=(FUENTE, TAM_CUERPO), foreground=TEXTO_SECUNDARIO,
            background=SUPERFICIE,
        ).pack(anchor='w', pady=(0, ESPACIO_M))

        separador(formulario, pady=ESPACIO_M)

        self.form_frame = ttk.Frame(formulario, style='Tarjeta.TFrame')
        self.form_frame.pack(fill='x', pady=(ESPACIO_S, 0))
        self.form_frame.columnconfigure(0, weight=1)

        self.entry_usuario = None
        self.entry_contrasena = None
        self._mostrar_login()

        # Pie de pagina
        pie = ttk.Frame(formulario, style='Tarjeta.TFrame')
        pie.pack(fill='x', pady=(ESPACIO_L, 0))
        ttk.Label(
            pie, text='Migración Access · MARC21 · Koha',
            font=(FUENTE, 9), foreground=TEXTO_MUTADO, background=SUPERFICIE,
        ).pack(anchor='center')

        self.root.bind('<Return>', lambda e: self._iniciar_sesion())

    def _crear_campo(self, texto, show=None):
        frame = ttk.Frame(self.form_frame, style='Tarjeta.TFrame')
        frame.pack(fill='x', pady=ESPACIO_S)
        frame.columnconfigure(0, weight=1)

        contenedor = ttk.Frame(frame, style='Tarjeta.TFrame')
        contenedor.pack(fill='x')
        contenedor.columnconfigure(0, weight=1)

        etiqueta = ttk.Label(
            contenedor, text=texto, style='Field.TLabel',
        )
        etiqueta.grid(row=0, column=0, sticky='w', pady=(0, ESPACIO_XS))

        entry = tk.Entry(
            contenedor,
            show=show,
            font=(FUENTE, 11),
            bg='#fbfaf9',
            fg=TEXTO,
            insertbackground=TEXTO,
            highlightthickness=1,
            highlightbackground=BORDE,
            highlightcolor=BORDE_ENFOQUE,
            relief='flat',
        )
        entry.grid(row=1, column=0, sticky='ew', ipady=ESPACIO_S)
        entry.bind('<FocusIn>', lambda evento: entry.config(highlightbackground=BORDE_ENFOQUE))
        entry.bind('<FocusOut>', lambda evento: entry.config(highlightbackground=BORDE))
        return entry

    def _limpiar_formulario(self):
        for widget in self.form_frame.winfo_children():
            widget.destroy()

    def _crear_boton_principal(self, texto, comando, estilo='Primary.TButton'):
        boton = tk.Button(
            self.form_frame,
            text=texto,
            command=comando,
            bg=PRIMARIO,
            fg=TEXTO_INVERSO,
            activebackground=PRIMARIO_HOVER,
            activeforeground=TEXTO_INVERSO,
            relief='flat',
            padx=24,
            pady=12,
            font=(FUENTE, 11, 'bold'),
            cursor='hand2',
            highlightthickness=0,
            bd=0,
        )
        boton.pack(fill='x', pady=(ESPACIO_M, ESPACIO_S))
        return boton

    def _mostrar_login(self):
        self.entry_usuario = self._crear_campo('Usuario:')
        self.entry_contrasena = self._crear_campo('Contraseña:', show='*')
        self._crear_boton_principal('Iniciar sesión', self._iniciar_sesion)
        self.entry_usuario.focus()

    def _iniciar_sesion(self):
        usuario = self.entry_usuario.get().strip()
        contrasena = self.entry_contrasena.get()

        if not usuario or not contrasena:
            messagebox.showwarning(
                'Faltan datos',
                'Ingresa tu usuario y contrasena.'
            )
            return

        token = self.auth_service.authenticate(usuario, contrasena)
        if token is None:
            messagebox.showerror('Acceso denegado', 'El usuario o la contrasena no son correctos.')
            self.entry_contrasena.delete(0, tk.END)
            self.entry_contrasena.focus()
            return

        self.on_login_success(token)
