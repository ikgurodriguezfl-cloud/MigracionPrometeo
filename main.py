"""Punto de entrada de la aplicacion Prometeo Migrator."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from gui_app import MigracionApp


def main():
    root = tk.Tk()
    app = MigracionApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
