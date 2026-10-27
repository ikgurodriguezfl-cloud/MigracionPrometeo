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
        LoginScreen(root, auth_service=auth_service, on_login_success=ir_a_principal)

    def ir_a_principal(session_token):
        # Limpiar todos los widgets de la ventana actual
        for widget in root.winfo_children():
            widget.destroy()

        # Ajustar titulo y tamanio para la pantalla principal
        root.title('Prometeo Migrator - Access a MARC21 (Koha)')
        root.geometry('900x650')
        root.minsize(800, 600)

        # Cargar la aplicacion principal
        MigracionApp(
            root,
            auth_service=auth_service,
            session_token=session_token,
            on_logout=mostrar_login,
        )

    # Mostrar pantalla de inicio de sesion
    mostrar_login()

    root.mainloop()


if __name__ == '__main__':
    main()
