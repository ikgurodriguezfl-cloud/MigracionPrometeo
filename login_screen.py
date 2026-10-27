"""Pantalla de inicio de sesion (sin funcionalidad real de autenticacion)."""
import tkinter as tk
from tkinter import ttk, messagebox


class LoginScreen:
    def __init__(self, root: tk.Tk, on_login_success):
        self.root = root
        self.on_login_success = on_login_success

        self.root.title('Prometeo Migrator - Inicio de sesion')
        self.root.geometry('400x300')
        self.root.resizable(False, False)

        self._crear_interfaz()

    def _crear_interfaz(self):
        # Contenedor centrado
        container = ttk.Frame(self.root, padding='40 40 40 40')
        container.pack(expand=True, fill='both')

        # Título
        lbl_titulo = ttk.Label(
            container,
            text='Prometeo Migrator',
            font=('Segoe UI', 16, 'bold')
        )
        lbl_titulo.pack(pady=(0, 10))

        lbl_sub = ttk.Label(
            container,
            text='Sistema de migracion Access a MARC21 (Koha)'
        )
        lbl_sub.pack(pady=(0, 30))

        # Campo Usuario
        frame_user = ttk.Frame(container)
        frame_user.pack(fill='x', pady=5)
        ttk.Label(frame_user, text='Usuario:').pack(side='left')
        self.entry_usuario = ttk.Entry(frame_user, width=30)
        self.entry_usuario.pack(side='right', fill='x', expand=True, padx=(10, 0))
        self.entry_usuario.insert(0, 'admin')  # valor por defecto visual

        # Campo Contrasena
        frame_pass = ttk.Frame(container)
        frame_pass.pack(fill='x', pady=5)
        ttk.Label(frame_pass, text='Contrasena:').pack(side='left')
        self.entry_contrasena = ttk.Entry(frame_pass, width=30, show='*')
        self.entry_contrasena.pack(side='right', fill='x', expand=True, padx=(10, 0))
        self.entry_contrasena.insert(0, '1234')  # valor por defecto visual

        # Boton Iniciar sesion
        btn_login = ttk.Button(
            container,
            text='Iniciar sesion',
            command=self._iniciar_sesion
        )
        btn_login.pack(pady=(25, 10), ipadx=20, ipady=5)

        # Vincular tecla Enter
        self.root.bind('<Return>', lambda e: self._iniciar_sesion())

        # Enfoque inicial
        self.entry_usuario.focus()

    def _iniciar_sesion(self):
        # Sin validacion real: cualquier usuario pasa directamente
        usuario = self.entry_usuario.get().strip()
        contrasena = self.entry_contrasena.get()

        if not usuario or not contrasena:
            messagebox.showwarning(
                'Atencion',
                'Ingrese usuario y contrasena.'
            )
            return

        # Llamar al callback para cambiar a la pantalla principal
        self.on_login_success()
