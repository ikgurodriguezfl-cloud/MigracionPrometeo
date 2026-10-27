"""Punto de entrada de la aplicacion Prometeo Migrator."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from auth import AuthenticationService
from login_screen import LoginScreen
from gui_app import MigracionApp


def main():
    root = tk.Tk()
    auth_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth.db')
    auth_service = AuthenticationService(auth_path)

    def mostrar_login():
        # Limpiar todos los widgets de la ventana actual
        for widget in root.winfo_children():
            widget.destroy()

        root.title('Prometeo Migrator - Inicio de sesion')
        try:
            LoginScreen(root, auth_service=auth_service, on_login_success=ir_a_principal)
        except TypeError as error:
            if 'auth_service' not in str(error):
                raise
            LoginScreen(root, on_login_success=ir_a_principal)

    def ir_a_principal(session_token=None):
        # El atajo del login no debe reiniciar la aplicación al usar el panel.
        root.unbind('<Return>')
        # Limpiar todos los widgets de la ventana actual
        for widget in root.winfo_children():
            widget.destroy()

        # Ajustar titulo y tamanio para la pantalla principal
        root.title('Prometeo Migrator - Access a MARC21 (Koha)')
        root.geometry('900x650')
        root.minsize(800, 600)
        root.resizable(True, True)

        # Cargar la aplicacion principal
        try:
            app = MigracionApp(
                root,
                auth_service=auth_service,
                session_token=session_token,
                on_logout=mostrar_login,
            )
        except TypeError as error:
            if 'auth_service' not in str(error):
                raise
            app = MigracionApp(root)
        root.protocol('WM_DELETE_WINDOW', app.cerrar)

    # Mostrar pantalla de inicio de sesion
    mostrar_login()

    root.mainloop()


if __name__ == '__main__':
    main()
