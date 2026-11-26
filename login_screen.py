"""Acceso principal de NexoMARC."""
import os
import tkinter as tk
from tkinter import ttk
from auth import AuthenticationService

from ui_kit import (
    FONDO, SUPERFICIE, TEXTO, TEXTO_SECUNDARIO, TEXTO_INVERSO,
    BORDE, PRIMARIO, ERROR, ADVERTENCIA, NOCHE,
    FUENTE, TAM_CUERPO, ESPACIO_XS, ESPACIO_S, ESPACIO_M, ESPACIO_L, ESPACIO_XL,
    instalar_estilos, crear_icono,
)

LOGIN_FONDO = FONDO
LOGIN_TARJETA = SUPERFICIE
LOGIN_TEXTO = TEXTO
LOGIN_SECUNDARIO = TEXTO_SECUNDARIO
LOGIN_OSCURO = NOCHE


class LoginScreen:
    def __init__(self, root: tk.Tk, auth_service: AuthenticationService, on_login_success):
        self.root = root
        self.auth_service = auth_service
        self.on_login_success = on_login_success

        self.root.title('NexoMARC | Iniciar sesión')
        ancho = min(960, self.root.winfo_screenwidth() - 48)
        alto = min(680, self.root.winfo_screenheight() - 72)
        self.root.geometry(f'{ancho}x{alto}')
        self.root.minsize(min(800, ancho), min(620, alto))
        self.root.state('zoomed')
        self.root.resizable(True, True)
        self.root.configure(background=LOGIN_FONDO)

        instalar_estilos(self.root)
        self._estilos_login()
        self._crear_interfaz()

    def _estilos_login(self):
        estilo = ttk.Style(self.root)
        estilo.configure('LoginSurface.TFrame', background=LOGIN_FONDO)
        estilo.configure('LoginCard.TFrame', background=LOGIN_TARJETA)
        estilo.configure(
            'LoginEyebrow.TLabel', background=LOGIN_TARJETA, foreground=PRIMARIO,
            font=(FUENTE, 9, 'bold'),
        )
        estilo.configure(
            'LoginTitle.TLabel', background=LOGIN_TARJETA, foreground=LOGIN_TEXTO,
            font=(FUENTE, 24, 'bold'),
        )
        estilo.configure(
            'LoginCopy.TLabel', background=LOGIN_TARJETA, foreground=LOGIN_SECUNDARIO,
            font=(FUENTE, TAM_CUERPO),
        )
        estilo.configure(
            'LoginField.TLabel', background=LOGIN_TARJETA, foreground=LOGIN_TEXTO,
            font=(FUENTE, 10, 'bold'),
        )
        estilo.configure(
            'LoginHint.TLabel', background=LOGIN_TARJETA, foreground=LOGIN_SECUNDARIO,
            font=(FUENTE, 9),
        )
        estilo.configure(
            'Login.TEntry', fieldbackground='#ffffff', foreground=LOGIN_TEXTO,
            bordercolor=BORDE, focuscolor=PRIMARIO, padding=(9, 7),
        )
        estilo.configure(
            'Login.TCheckbutton', background=LOGIN_TARJETA, foreground=LOGIN_SECUNDARIO,
            font=(FUENTE, 9),
        )
        estilo.map(
            'Login.TCheckbutton',
            background=[('active', LOGIN_TARJETA)],
            foreground=[('active', LOGIN_TEXTO)],
        )

    def _crear_interfaz(self):
        contenedor = tk.Frame(self.root, bg=LOGIN_FONDO)
        contenedor.pack(fill='both', expand=True)
        contenedor.grid_columnconfigure(0, weight=1, minsize=320)
        contenedor.grid_columnconfigure(1, weight=2, minsize=520)
        contenedor.grid_rowconfigure(0, weight=1)

        marca = tk.Frame(contenedor, bg=LOGIN_OSCURO, padx=48, pady=46)
        marca.grid(row=0, column=0, sticky='nsew')
        marca.grid_columnconfigure(0, weight=1)

        identidad = tk.Frame(marca, bg=LOGIN_OSCURO)
        identidad.pack(anchor='w')
        crear_icono(
            identidad, 'database', color=TEXTO_INVERSO, size=34, fondo=PRIMARIO,
        ).pack(side='left', padx=(0, ESPACIO_M))
        tk.Label(
            identidad, text='NexoMARC', bg=LOGIN_OSCURO, fg=TEXTO_INVERSO,
            font=(FUENTE, 14, 'bold'),
        ).pack(side='left')

        tk.Frame(marca, bg=PRIMARIO, height=2, width=48).pack(
            anchor='w', pady=(54, 28),
        )
        tk.Label(
            marca, text='Tu catálogo\nbibliográfico, listo.',
            bg=LOGIN_OSCURO, fg=TEXTO_INVERSO, justify='left', anchor='w',
            font=(FUENTE, 28, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            marca,
            text='Prepara tu información bibliográfica\npara trabajar con Koha.',
            bg=LOGIN_OSCURO, fg='#c2c9d8', justify='left', anchor='w',
            font=(FUENTE, 11), pady=18,
        ).pack(anchor='w')

        ttk.Label(
            marca, text='Conecta   ·   Configura   ·   Migra',
            style='HeroHint.TLabel',
        ).pack(side='bottom', anchor='w')

        acceso = tk.Frame(contenedor, bg=SUPERFICIE, padx=30, pady=24)
        acceso.grid(row=0, column=1, sticky='nsew')
        acceso.grid_columnconfigure(0, weight=1)
        acceso.grid_rowconfigure(1, weight=1)

        logos = tk.Frame(acceso, bg=SUPERFICIE)
        logos.grid(row=0, column=0, sticky='ew', pady=(ESPACIO_M, ESPACIO_XL))
        fila_logos = tk.Frame(logos, bg=SUPERFICIE)
        fila_logos.pack(anchor='center')
        carpeta_logos = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'assets',
        )
        self.logo_tecnologico = tk.PhotoImage(
            master=self.root,
            file=os.path.join(carpeta_logos, 'logo_tecnologico.png'),
        ).subsample(7, 7)
        self.logo_tepic = tk.PhotoImage(
            master=self.root,
            file=os.path.join(carpeta_logos, 'logo_tepic.png'),
        ).subsample(7, 7)
        tk.Label(
            fila_logos, image=self.logo_tecnologico, bg=SUPERFICIE,
            borderwidth=0,
        ).pack(side='left')
        tk.Frame(fila_logos, bg=BORDE, width=1, height=48).pack(
            side='left', padx=ESPACIO_L,
        )
        tk.Label(
            fila_logos, image=self.logo_tepic, bg=SUPERFICIE,
            borderwidth=0,
        ).pack(side='left')

        area_formulario = ttk.Frame(acceso, style='LoginSurface.TFrame')
        area_formulario.grid(row=1, column=0, sticky='nsew')

        formulario = ttk.Frame(
            acceso, style='LoginCard.TFrame', padding=(ESPACIO_XL, ESPACIO_XL),
        )
        formulario.place(
            in_=area_formulario, relx=0.5, rely=0.5, anchor='center',
        )
        formulario.columnconfigure(0, weight=1)

        encabezado = ttk.Frame(formulario, style='LoginCard.TFrame')
        encabezado.pack(fill='x', pady=(0, ESPACIO_L))

        ttk.Label(
            encabezado, text='INICIO DE SESIÓN', style='LoginEyebrow.TLabel',
        ).pack(anchor='w', pady=(0, ESPACIO_S))
        ttk.Label(
            encabezado, text='¡Bienvenido de nuevo!', style='LoginTitle.TLabel',
        ).pack(anchor='w', pady=(0, ESPACIO_XS))
        ttk.Label(
            encabezado, text='Ingresa tus datos para continuar.',
            style='LoginCopy.TLabel',
        ).pack(anchor='w')

        self.form_frame = ttk.Frame(formulario, style='LoginCard.TFrame')
        self.form_frame.pack(fill='x', pady=(ESPACIO_M, 0))
        self.form_frame.columnconfigure(0, weight=1)

        self.entry_usuario = None
        self.entry_contrasena = None
        self.mostrar_contrasena = tk.BooleanVar(value=False)
        self._mostrar_login()

        pie = ttk.Frame(acceso, style='LoginSurface.TFrame')
        pie.grid(row=2, column=0, sticky='ew', pady=(ESPACIO_M, 0))
        ttk.Label(
            pie, text='Migración Access  ·  MARC21  ·  Koha',
            style='LoginHint.TLabel',
        ).pack(anchor='center')

        self.root.bind('<Return>', lambda _evento: self._iniciar_sesion())

    def _crear_campo(self, texto, show=None):
        frame = ttk.Frame(self.form_frame, style='LoginCard.TFrame')
        frame.pack(fill='x', pady=ESPACIO_S)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text=texto, style='LoginField.TLabel').pack(
            anchor='w', pady=(0, ESPACIO_XS),
        )
        entry = ttk.Entry(frame, show=show, style='Login.TEntry')
        entry.pack(fill='x', ipady=3)
        return entry

    def _limpiar_formulario(self):
        for widget in self.form_frame.winfo_children():
            widget.destroy()

    def _crear_boton_principal(self, texto, comando, estilo='Primary.TButton'):
        boton = ttk.Button(
            self.form_frame, text=texto, command=comando, style=estilo,
        )
        boton.pack(fill='x', pady=(ESPACIO_M, ESPACIO_S))
        return boton

    def _mostrar_login(self):
        self.entry_usuario = self._crear_campo('Usuario:')
        self.entry_contrasena = self._crear_campo('Contraseña:', show='*')
        ttk.Checkbutton(
            self.form_frame, text='Mostrar contraseña',
            variable=self.mostrar_contrasena, command=self._alternar_contrasena,
            style='Login.TCheckbutton',
        ).pack(anchor='w', pady=(ESPACIO_XS, ESPACIO_S))
        self.lbl_mensaje = ttk.Label(
            self.form_frame, text='', style='LoginHint.TLabel', wraplength=380,
        )
        self.lbl_mensaje.pack(fill='x', pady=(0, ESPACIO_XS))
        self._crear_boton_principal('Iniciar sesión', self._iniciar_sesion)
        self.entry_usuario.focus_set()

    def _alternar_contrasena(self):
        self.entry_contrasena.configure(
            show='' if self.mostrar_contrasena.get() else '*',
        )

    def _iniciar_sesion(self):
        usuario = self.entry_usuario.get().strip()
        contrasena = self.entry_contrasena.get()

        if not usuario or not contrasena:
            self.lbl_mensaje.configure(
                text='Escribe tu usuario y contraseña para continuar.',
                foreground=ADVERTENCIA,
            )
            (self.entry_usuario if not usuario else self.entry_contrasena).focus_set()
            return

        token = self.auth_service.authenticate(usuario, contrasena)
        if token is None:
            self.lbl_mensaje.configure(
                text='El usuario o la contraseña no son correctos. Inténtalo de nuevo.',
                foreground=ERROR,
            )
            self.entry_contrasena.delete(0, tk.END)
            self.entry_contrasena.focus_set()
            return

        self.on_login_success(token)
