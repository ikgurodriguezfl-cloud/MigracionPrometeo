"""Pantalla de inicio de sesion."""
import tkinter as tk
from tkinter import messagebox
from auth import AuthenticationService

FONDO_PANEL = '#f7f5f2'
BLANCO = '#ffffff'
TEXTO_TITULO = '#302a31'
TEXTO_MUTED = '#777078'
TEXTO_CARD = '#686168'
GUINDA = '#6d0c2e'
GUINDA_CLARO = '#8e2a50'
BORDE_CAMPO = '#e2ddd8'
CAMPO = '#fbfaf9'


class LoginScreen:
    def __init__(self, root: tk.Tk, auth_service: AuthenticationService, on_login_success):
        self.root = root
        self.auth_service = auth_service
        self.on_login_success = on_login_success

        self.root.title('NexoMARC | Iniciar sesión')
        self.root.geometry('940x620')
        self.root.minsize(780, 560)
        self.root.resizable(True, True)
        self.root.configure(background=FONDO_PANEL)
        self._crear_interfaz()

    def _crear_interfaz(self):
        contenedor = tk.Frame(self.root, bg=BLANCO)
        contenedor.pack(fill='both', expand=True)
        contenedor.grid_columnconfigure(0, weight=4, minsize=300)
        contenedor.grid_columnconfigure(1, weight=6, minsize=440)
        contenedor.grid_rowconfigure(0, weight=1)

        marca = tk.Frame(contenedor, bg=GUINDA, padx=48, pady=46)
        marca.grid(row=0, column=0, sticky='nsew')
        tk.Label(
            marca, text='NexoMARC', bg=GUINDA, fg=BLANCO,
            font=('Segoe UI', 12, 'bold'),
        ).pack(anchor='w')

        tk.Frame(marca, bg='#a75a75', height=2, width=48).pack(
            anchor='w', pady=(54, 28),
        )
        tk.Label(
            marca, text='Tu catálogo\nbibliográfico, listo.',
            bg=GUINDA, fg=BLANCO, justify='left', anchor='w',
            font=('Segoe UI', 28, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            marca,
            text='Prepara tu información bibliográfica\npara trabajar con Koha.',
            bg=GUINDA, fg='#e8dce1', justify='left', anchor='w',
            font=('Segoe UI', 11), pady=18,
        ).pack(anchor='w')
        tk.Label(
            marca, text='GESTIÓN BIBLIOGRÁFICA     ·     KOHA',
            bg=GUINDA, fg='#e4cbd4', font=('Segoe UI', 8, 'bold'),
        ).pack(side='bottom', anchor='w')

        acceso = tk.Frame(contenedor, bg=BLANCO)
        acceso.grid(row=0, column=1, sticky='nsew')
        formulario = tk.Frame(acceso, bg=BLANCO, width=390)
        formulario.place(relx=0.5, rely=0.48, anchor='center', width=390)

        tk.Label(
            formulario, text='INICIO DE SESIÓN', bg=BLANCO, fg=GUINDA,
            font=('Segoe UI', 9, 'bold'),
        ).pack(anchor='w', pady=(0, 12))
        self.lbl_titulo = tk.Label(
            formulario, text='Qué gusto tenerte aquí',
            font=('Segoe UI', 24, 'bold'), fg=TEXTO_TITULO, bg=BLANCO,
        )
        self.lbl_titulo.pack(anchor='w', pady=(0, 8))
        self.lbl_sub = tk.Label(
            formulario, text='Ingresa tus datos para continuar.',
            font=('Segoe UI', 10), fg=TEXTO_MUTED, bg=BLANCO,
        )
        self.lbl_sub.pack(anchor='w', pady=(0, 28))

        self.form_frame = tk.Frame(formulario, bg=BLANCO)
        self.form_frame.pack(fill='x')
        tk.Label(
            acceso, text='Migración Access · MARC21 · Koha',
            bg=BLANCO, fg=TEXTO_MUTED, font=('Segoe UI', 9),
        ).place(relx=0.5, rely=0.94, anchor='center')

        self.entry_usuario = None
        self.entry_contrasena = None
        self._mostrar_login()
        self.root.bind('<Return>', lambda e: self._iniciar_sesion())

    def _crear_campo(self, texto, show=None):
        frame = tk.Frame(self.form_frame, bg=BLANCO)
        frame.pack(fill='x', pady=8)
        etiqueta = tk.Label(
            frame,
            text=texto,
            font=('Segoe UI', 10, 'bold'),
            fg=TEXTO_CARD,
            bg=BLANCO,
            anchor='w',
        )
        etiqueta.pack(fill='x', pady=(0, 7))
        entry = tk.Entry(
            frame,
            show=show,
            font=('Segoe UI', 11),
            bg=CAMPO,
            fg=TEXTO_TITULO,
            insertbackground=TEXTO_TITULO,
            highlightthickness=1,
            highlightbackground=BORDE_CAMPO,
            highlightcolor=GUINDA,
            relief='flat',
        )
        entry.pack(fill='x', ipady=8)
        entry.bind('<FocusIn>', lambda evento: entry.config(highlightbackground=GUINDA))
        entry.bind('<FocusOut>', lambda evento: entry.config(highlightbackground=BORDE_CAMPO))
        return entry

    def _limpiar_formulario(self):
        for widget in self.form_frame.winfo_children():
            widget.destroy()

    def _crear_boton_principal(self, texto, comando):
        boton = tk.Button(
            self.form_frame,
            text=texto,
            command=comando,
            bg=GUINDA,
            fg=BLANCO,
            activebackground=GUINDA_CLARO,
            activeforeground=BLANCO,
            relief='flat',
            padx=24,
            pady=11,
            font=('Segoe UI', 11, 'bold'),
            cursor='hand2',
        )
        boton.pack(fill='x', pady=(16, 6))

    def _mostrar_login(self):
        self.lbl_titulo.config(text='¡Bienvenido!')
        self._limpiar_formulario()
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
                'Ingresa tu usuario y contraseña.'
            )
            return

        token = self.auth_service.authenticate(usuario, contrasena)
        if token is None:
            messagebox.showerror('Acceso denegado', 'El usuario o la contraseña no son correctos.')
            self.entry_contrasena.delete(0, tk.END)
            return

        self.on_login_success(token)
