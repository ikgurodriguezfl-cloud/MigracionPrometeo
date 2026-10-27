"""Punto de entrada de la aplicacion Prometeo Migrator."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from login_screen import LoginScreen
from gui_app import MigracionApp


def main():
    root = tk.Tk()

    def ir_a_principal():
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
        app = MigracionApp(root)
        root.protocol('WM_DELETE_WINDOW', app.cerrar)

    # Mostrar pantalla de inicio de sesion
    login = LoginScreen(root, on_login_success=ir_a_principal)

    root.mainloop()


if __name__ == '__main__':
    main()
