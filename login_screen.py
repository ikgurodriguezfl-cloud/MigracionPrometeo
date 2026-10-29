"""Pantalla de inicio de sesion."""
import tkinter as tk
from tkinter import ttk, messagebox
from auth import AuthenticationService

# Tokens de diseno alineados con el panel principal (panel_lotes.py).
FONDO_PANEL = '#f5f6fa'
BLANCO = '#ffffff'
TEXTO_TITULO = '#29283e'
TEXTO_MUTED = '#777d91'
TEXTO_CARD = '#6f7589'
GUINDA = '#6d0c2e'      # color principal (guinda)
GUINDA_CLARO = '#8e2a50'  # hover / active del boton principal
FRIO = '#ece8f6'
BORDE_CAMPO = '#d9d7ea'


class LoginScreen:
    def __init__(self, root: tk.Tk, auth_service: AuthenticationService, on_login_success):
        self.root = root
        self.auth_service = auth_service
        self.on_login_success = on_login_success

        self.root.title('Prometeo Migrator - Inicio de sesion')
        self.root.geometry('480x520')
        self.root.minsize(480, 520)
        self.root.resizable(False, False)
        self.root.configure(background=FONDO_PANEL)
        self._crear_interfaz()

    def _crear_interfaz(self):
        # Fondo de pantalla uniforme (gris panel del sistema).
        contenedor = tk.Frame(self.root, bg=FONDO_PANEL)
        contenedor.pack(expand=True, fill='both')

        # Caja blanca que encierra todo el formulario.
        self.tarjeta = tk.Frame(contenedor, bg=BLANCO)
        self.tarjeta.pack(expand=True, fill='both', padx=46, pady=46)

        # Contenido centrado dentro de la caja blanca, con respiro respecto a los bordes.
        interior = tk.Frame(self.tarjeta, bg=BLANCO)
        interior.pack(expand=True, fill='both', padx=36, pady=34)

        self.lbl_titulo = tk.Label(
            interior,
            text='Prometeo Migrator',
            font=('Segoe UI', 21, 'bold'),
            fg=TEXTO_TITULO,
            bg=BLANCO,
        )
        self.lbl_titulo.pack(pady=(0, 8))

        self.lbl_sub = tk.Label(
            interior,
            text='Sistema de migracion a MARC21',
            font=('Segoe UI', 10),
            fg=TEXTO_MUTED,
            bg=BLANCO,
        )
        self.lbl_sub.pack(pady=(0, 22))

        self.form_frame = tk.Frame(interior, bg=BLANCO)
        self.form_frame.pack(fill='x', pady=14)

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
            font=('Segoe UI', 9),
            fg=TEXTO_CARD,
            bg=BLANCO,
            anchor='w',
        )
        etiqueta.pack(fill='x', pady=(0, 4))
        entry = tk.Entry(
            frame,
            show=show,
            font=('Segoe UI', 10),
            bg=BLANCO,
            fg=TEXTO_TITULO,
            insertbackground=TEXTO_TITULO,
            highlightthickness=1,
            highlightbackground=BORDE_CAMPO,
            relief='flat',
        )
        entry.pack(fill='x')
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
            pady=8,
            font=('Segoe UI', 10, 'bold'),
            cursor='hand2',
        )
        boton.pack(fill='x', pady=(16, 6))

    def _mostrar_login(self):
        self.lbl_titulo.config(text='Iniciar sesion')
        self._limpiar_formulario()
        self.entry_usuario = self._crear_campo('Usuario:')
        self.entry_contrasena = self._crear_campo('Contrasena:', show='*')
        self._crear_boton_principal('Iniciar sesion', self._iniciar_sesion)
        self.entry_usuario.focus()

    def _iniciar_sesion(self):
        usuario = self.entry_usuario.get().strip()
        contrasena = self.entry_contrasena.get()

        if not usuario or not contrasena:
            messagebox.showwarning(
                'Atencion',
                'Ingrese usuario y contrasena.'
            )
            return

        token = self.auth_service.authenticate(usuario, contrasena)
        if token is None:
            messagebox.showerror('Acceso denegado', 'Usuario o contrasena incorrectos.')
            self.entry_contrasena.delete(0, tk.END)
            return

        self.on_login_success(token)
