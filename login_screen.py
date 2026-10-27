"""Pantalla de inicio de sesion."""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from auth import AuthenticationService


class LoginScreen:
    def __init__(self, root: tk.Tk, auth_service: AuthenticationService, on_login_success):
        self.root = root
        self.auth_service = auth_service
        self.on_login_success = on_login_success

        self.root.title('Prometeo Migrator - Inicio de sesion')
        self.root.geometry('430x360')
        self.root.resizable(False, False)
        self.modo = 'login'

        self._crear_interfaz()

    def _crear_interfaz(self):
        container = ttk.Frame(self.root, padding='40 40 40 40')
        container.pack(expand=True, fill='both')

        self.lbl_titulo = ttk.Label(
            container,
            text='Prometeo Migrator',
            font=('Segoe UI', 16, 'bold')
        )
        self.lbl_titulo.pack(pady=(0, 10))

        self.lbl_sub = ttk.Label(
            container,
            text='Sistema de migracion Access a MARC21 (Koha)'
        )
        self.lbl_sub.pack(pady=(0, 20))

        self.form_frame = ttk.Frame(container)
        self.form_frame.pack(fill='x')

        self.entry_usuario = None
        self.entry_contrasena = None
        self.entry_confirmacion = None
        self.btn_principal = None
        self.btn_secundario = None
        self._mostrar_login()
        self.root.bind('<Return>', lambda e: self._accion_enter())

    def _crear_campo(self, texto, show=None):
        frame = ttk.Frame(self.form_frame)
        frame.pack(fill='x', pady=5)
        ttk.Label(frame, text=texto).pack(side='left')
        entry = ttk.Entry(frame, width=30, show=show)
        entry.pack(side='right', fill='x', expand=True, padx=(10, 0))
        return entry

    def _limpiar_formulario(self):
        for widget in self.form_frame.winfo_children():
            widget.destroy()

    def _crear_botones(self, texto_principal, comando_principal,
                       texto_secundario, comando_secundario):
        self.btn_principal = ttk.Button(
            self.form_frame, text=texto_principal, command=comando_principal
        )
        self.btn_principal.pack(pady=(20, 8), ipadx=20, ipady=5)
        self.btn_secundario = ttk.Button(
            self.form_frame, text=texto_secundario, command=comando_secundario
        )
        self.btn_secundario.pack()

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
