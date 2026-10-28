"""Pantalla de inicio de sesion."""
import sqlite3
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
        self.root.geometry('430x560')
        self.root.minsize(430, 560)
        self.root.resizable(False, False)
        self.root.configure(background=FONDO_PANEL)
        self.modo = 'login'

        self._crear_interfaz()

    def _crear_interfaz(self):
        # Fondo de pantalla uniforme (gris panel del sistema).
        contenedor = tk.Frame(self.root, bg=FONDO_PANEL)
        contenedor.pack(expand=True, fill='both')

        # Caja blanca que encierra todo el formulario.
        self.tarjeta = tk.Frame(contenedor, bg=BLANCO)
        self.tarjeta.pack(expand=True, fill='both', padx=70, pady=70)

        # Contenido centrado dentro de la caja blanca, con respiro respecto a los bordes.
        interior = tk.Frame(self.tarjeta, bg=BLANCO)
        interior.pack(expand=True, fill='both', padx=30, pady=30)

        self.lbl_titulo = tk.Label(
            interior,
            text='Prometeo Migrator',
            font=('Segoe UI', 22, 'bold'),
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
        self.form_frame.pack(fill='x', pady=22)

        self.entry_usuario = None
        self.entry_contrasena = None
        self.entry_confirmacion = None
        self.btn_principal = None
        self.btn_secundario = None
        self._mostrar_login()
        self.root.bind('<Return>', lambda e: self._accion_enter())

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

    def _crear_botones(self, texto_principal, comando_principal,
                       texto_secundario, comando_secundario):
        self.btn_principal = tk.Button(
            self.form_frame,
            text=texto_principal,
            command=lambda: comando_principal(),
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
        self.btn_principal.pack(fill='x', pady=(16, 6))

        self.btn_secundario = tk.Button(
            self.form_frame,
            text=texto_secundario,
            command=lambda: comando_secundario(),
            bg=BLANCO,
            fg=GUINDA,
            activebackground=FRIO,
            activeforeground=GUINDA_CLARO,
            relief='flat',
            padx=24,
            pady=6,
            font=('Segoe UI', 10),
            cursor='hand2',
        )
        self.btn_secundario.pack(fill='x', pady=(0, 4))

    def _mostrar_login(self):
        self.modo = 'login'
        self.lbl_titulo.config(text='Iniciar sesion')
        self._limpiar_formulario()
        self.entry_usuario = self._crear_campo('Usuario:')
        self.entry_contrasena = self._crear_campo('Contrasena:', show='*')
        self._crear_botones(
            'Iniciar sesion', self._iniciar_sesion,
            'Crear cuenta', self._mostrar_registro,
        )
        self.entry_usuario.focus()

    def _mostrar_registro(self):
        self.modo = 'registro'
        self.lbl_titulo.config(text='Crear cuenta')
        self._limpiar_formulario()
        self.entry_usuario = self._crear_campo('Usuario:')
        self.entry_contrasena = self._crear_campo('Contrasena:', show='*')
        self.entry_confirmacion = self._crear_campo('Repetir contrasena:', show='*')
        self._crear_botones(
            'Registrar cuenta', self._registrar_cuenta,
            'Volver a iniciar sesion', self._mostrar_login,
        )
        self.entry_usuario.focus()

    def _registrar_cuenta(self):
        usuario = self.entry_usuario.get().strip()
        contrasena = self.entry_contrasena.get()
        confirmacion = self.entry_confirmacion.get()

        if not usuario or not contrasena or not confirmacion:
            messagebox.showwarning('Atencion', 'Complete todos los campos.')
            return
        if contrasena != confirmacion:
            messagebox.showerror('Registro rechazado', 'Las contrasenas no coinciden.')
            return

        try:
            self.auth_service.create_user(usuario, contrasena)
        except sqlite3.IntegrityError:
            messagebox.showerror('Registro rechazado', 'Ese usuario ya existe.')
            return
        except ValueError as error:
            messagebox.showerror('Registro rechazado', str(error))
            return

        messagebox.showinfo('Cuenta creada', 'La cuenta se creo correctamente.')
        self._mostrar_login()

    def _accion_enter(self):
        if self.modo == 'registro':
            self._registrar_cuenta()
        else:
            self._iniciar_sesion()

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
