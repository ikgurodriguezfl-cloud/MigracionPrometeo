"""Interfaz grafica de la migracion Prometeo Access -> MySQL MARC21 -> Koha."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import sqlite3
import threading
from queue import Empty, Queue
from time import monotonic
from typing import Optional, Dict, Any, List

from auth import AuthenticationService
from access_reader import AccessReader
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter
from lotes import HistorialLotes, acciones_lote
from panel_lotes import PanelLotes
from permissions import requerir_permiso, AccesoDenegado


class _DetencionSolicitada(Exception):
    """Señal interna para terminar entre operaciones, sin cortar una ficha."""


class MigracionApp:
    COLORES = {
        'fondo': '#f7f5f2',
        'superficie': '#ffffff',
        'texto': '#302a31',
        'texto_secundario': '#777078',
        'borde': '#e8e2de',
        'guinda': '#6d0c2e',
        'guinda_hover': '#8e2a50',
        'guinda_suave': '#f3e8ec',
        'barra_lateral': '#39232f',
        'barra_lateral_hover': '#503443',
        'barra_lateral_activa': '#654052',
        'barra_lateral_muted': '#c5b7bf',
        'verde': '#367963',
        'verde_suave': '#e8f2ed',
        'tierra': '#b48157',
    }

    def __init__(self, root: tk.Tk, historial_lotes=None,
                 auth_service: Optional[AuthenticationService] = None,
                 session_token: Optional[str] = None, on_logout=None):
        self.root = root
        self.auth_service = auth_service
        self.session_token = session_token
        self.on_logout = on_logout
        
        # Obtención del perfil para la matriz de permisos
        self.perfil_usuario = self.auth_service.get_profile(self.session_token) if self.auth_service else "Ejecucion"
        
        self.root.title(f'Prometeo Migrator - Access a MARC21 (Koha) | Perfil: {self.perfil_usuario}')
        ancho = min(1260, self.root.winfo_screenwidth() - 80)
        alto = min(820, self.root.winfo_screenheight() - 100)
        self.root.geometry(f'{ancho}x{alto}')
        self.root.minsize(min(1080, ancho), min(700, alto))
        self.root.configure(background=self.COLORES['fondo'])

        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        self.config = self.cargar_config()

        self.access_reader: Optional[AccessReader] = None
        self.mysql_writer: Optional[MySQLWriter] = None

        self.marc_converter = MarcConverter()

        # Valores por defecto para Koha (942 y 952)
        self.var_item_type_bib = tk.StringVar(value=self.config.get(
            'item_type_bib', self.marc_converter.item_type_bib))
        self.var_item_type_item = tk.StringVar(value=self.config.get(
            'item_type_item', self.marc_converter.item_type_item))
        self.var_homebranch = tk.StringVar(value=self.config.get(
            'homebranch', self.marc_converter.homebranch))
        self.var_holdingbranch = tk.StringVar(value=self.config.get(
            'holdingbranch', self.marc_converter.holdingbranch))

        self.marc_converter = MarcConverter(
            item_type_bib=self.var_item_type_bib.get(),
            item_type_item=self.var_item_type_item.get(),
            homebranch=self.var_homebranch.get(),
            holdingbranch=self.var_holdingbranch.get(),
        )
        self.migracion_en_curso = False
        self._mysql_validado = False
        self._configuracion_confirmada = False
        self._detencion_solicitada = threading.Event()
        self.historial_lotes = historial_lotes if historial_lotes is not None else HistorialLotes()
        self._lote_actual_id = None
        self._validacion_access = None
        self._eventos_ui = Queue()
        self._cerrando = False

        self._crear_interfaz()
        self._cargar_config_en_ui()
        self._actualizar_panel()
        self._procesar_eventos_ui()
        if self.historial_lotes.error_carga:
            self.log('[AVISO] ' + self.historial_lotes.error_carga)
            self.root.after(0, messagebox.showwarning, 'Historial no disponible',
                            self.historial_lotes.error_carga + '\nSe conservó el archivo anterior. No se iniciarán nuevas migraciones hasta resolverlo.')

    def _crear_interfaz(self):
        self._estilos_interfaz()

        distribucion = ttk.Frame(self.root, style='App.TFrame')
        distribucion.pack(fill='both', expand=True)

        sidebar = tk.Frame(
            distribucion, bg=self.COLORES['barra_lateral'], width=224,
            highlightthickness=0,
        )
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)

        marca = tk.Frame(sidebar, bg=self.COLORES['barra_lateral'])
        marca.pack(fill='x', padx=18, pady=(24, 34))
        tk.Label(
            marca, text='P', width=2, height=1, bg='#ffffff',
            fg=self.COLORES['guinda'], font=('Segoe UI', 17, 'bold'),
        ).pack(side='left', padx=(0, 10), ipady=3)
        identidad = tk.Frame(marca, bg=self.COLORES['barra_lateral'])
        identidad.pack(side='left')
        tk.Label(
            identidad, text='PROMETEO', bg=self.COLORES['barra_lateral'],
            fg='#ffffff', font=('Segoe UI', 11, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            identidad, text='MIGRATOR', bg=self.COLORES['barra_lateral'],
            fg=self.COLORES['barra_lateral_muted'], font=('Segoe UI', 8, 'bold'),
        ).pack(anchor='w', pady=(2, 0))

        tk.Label(
            sidebar, text='MIGRACIÓN', bg=self.COLORES['barra_lateral'],
            fg=self.COLORES['barra_lateral_muted'], font=('Segoe UI', 8, 'bold'),
        ).pack(anchor='w', padx=20, pady=(0, 8))

        area = ttk.Frame(distribucion, style='App.TFrame')
        area.pack(side='left', fill='both', expand=True)
        self.page_container = ttk.Frame(area, style='App.TFrame')
        self.page_container.pack(fill='both', expand=True)
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)

        self.frame_conexion = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_config = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_migracion = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_log = ttk.Frame(self.page_container, style='App.TFrame')

        self.panel_lotes = PanelLotes(
            self.page_container, listar=self.historial_lotes.listar, politica=self._politica_lote,
            iniciar=self._iniciar_desde_panel, exportar=self._exportar_marcxml,
            conexiones=lambda: self._navegar(self.frame_conexion),
            detener=self._solicitar_detencion,
        )
        self.paginas = (
            self.panel_lotes,
            self.frame_conexion,
            self.frame_config,
            self.frame_migracion,
            self.frame_log,
        )
        for pagina in self.paginas:
            pagina.grid(row=0, column=0, sticky='nsew')

        self._nav_items = {}
        self._crear_boton_navegacion(sidebar, 'Inicio', self.panel_lotes)
        ttk.Separator(sidebar, orient='horizontal').pack(fill='x', padx=18, pady=14)
        self._crear_boton_navegacion(sidebar, '1   Conexión', self.frame_conexion)
        self._crear_boton_navegacion(sidebar, '2   Configuración', self.frame_config)
        self._crear_boton_navegacion(sidebar, '3   Migración', self.frame_migracion)

        tk.Label(
            sidebar, text='SISTEMA', bg=self.COLORES['barra_lateral'],
            fg=self.COLORES['barra_lateral_muted'], font=('Segoe UI', 8, 'bold'),
        ).pack(anchor='w', padx=20, pady=(26, 8))
        self._crear_boton_navegacion(sidebar, 'Actividad', self.frame_log)

        pie = tk.Frame(sidebar, bg=self.COLORES['barra_lateral'])
        pie.pack(side='bottom', fill='x', padx=20, pady=20)
        tk.Frame(pie, bg=self.COLORES['barra_lateral_hover'], height=1).pack(fill='x', pady=(0, 14))
        tk.Label(
            pie, text='Sesión activa', bg=self.COLORES['barra_lateral'],
            fg=self.COLORES['barra_lateral_muted'], font=('Segoe UI', 8),
        ).pack(anchor='w')
        tk.Label(
            pie, text=self.perfil_usuario, bg=self.COLORES['barra_lateral'],
            fg='#ffffff', font=('Segoe UI', 10, 'bold'),
        ).pack(anchor='w', pady=(3, 0))
        if self.auth_service is not None and self.auth_service.is_admin(self.session_token):
            tk.Button(
                pie, text='Crear usuario', command=self._abrir_registro_usuario,
                anchor='w', padx=0, pady=8, bd=0, relief='flat',
                cursor='hand2', font=('Segoe UI', 9),
                bg=self.COLORES['barra_lateral'],
                fg=self.COLORES['barra_lateral_muted'],
                activebackground=self.COLORES['barra_lateral_hover'],
                activeforeground='#ffffff', highlightthickness=0,
            ).pack(anchor='w', pady=(8, 0))
        tk.Button(
            pie, text='Cerrar sesión', command=self._cerrar_sesion,
            anchor='w', padx=0, pady=8, bd=0, relief='flat',
            cursor='hand2', font=('Segoe UI', 9),
            bg=self.COLORES['barra_lateral'],
            fg=self.COLORES['barra_lateral_muted'],
            activebackground=self.COLORES['barra_lateral_hover'],
            activeforeground='#ffffff', highlightthickness=0,
        ).pack(anchor='w', pady=(8, 0))

        self._crear_pestana_conexion()
        self._crear_pestana_migracion()
        self._crear_pestana_config()
        self._crear_pestana_log()
        for variable in (self.entry_host, self.entry_port, self.entry_user, self.entry_pass, self.entry_db):
            variable.trace_add('write', self._cambio_configuracion_mysql)
        self.pagina_actual = self.panel_lotes
        self.panel_lotes.tkraise()
        self._actualizar_navegacion_secuencial()

    def _crear_boton_navegacion(self, parent, texto, pantalla):
        boton = tk.Button(
            parent,
            text=texto,
            command=lambda destino=pantalla: self._navegar(destino),
            anchor='w',
            padx=18,
            pady=11,
            bd=0,
            relief='flat',
            cursor='hand2',
            font=('Segoe UI', 10),
            bg=self.COLORES['barra_lateral'],
            fg='#f7f2f4',
            activebackground=self.COLORES['barra_lateral_hover'],
            activeforeground='#ffffff',
            disabledforeground='#988b92',
            highlightthickness=0,
        )
        boton.pack(fill='x', padx=10, pady=2)
        self._nav_items[pantalla] = boton

    def _estilos_interfaz(self):
        estilo = ttk.Style(self.root)
        estilo.theme_use('clam')
        colores = self.COLORES
        estilo.configure('.', font=('Segoe UI', 10), foreground=colores['texto'])
        estilo.configure('App.TFrame', background=colores['fondo'])
        estilo.configure('TFrame', background=colores['fondo'])
        estilo.configure('TLabel', background=colores['fondo'], foreground=colores['texto'])
        estilo.configure('AppTitle.TLabel', background=colores['fondo'],
                         foreground=colores['texto'], font=('Segoe UI', 17, 'bold'))
        estilo.configure('PageTitle.TLabel', background=colores['fondo'],
                         foreground=colores['texto'], font=('Segoe UI', 18, 'bold'))
        estilo.configure('PageSubtitle.TLabel', background=colores['fondo'],
                         foreground=colores['texto_secundario'], font=('Segoe UI', 10))
        estilo.configure('Card.TFrame', background=colores['superficie'])
        estilo.configure('CardHint.TLabel', background=colores['superficie'],
                         foreground=colores['texto_secundario'], font=('Segoe UI', 9))
        estilo.configure('CardBody.TLabel', background=colores['superficie'],
                         foreground=colores['texto'], font=('Segoe UI', 10))
        estilo.configure('CardMetric.TLabel', background=colores['superficie'],
                         foreground=colores['guinda'], font=('Segoe UI', 11, 'bold'))
        estilo.configure('CardTitle.TLabel', background=colores['superficie'],
                         foreground=colores['texto'], font=('Segoe UI', 12, 'bold'))
        estilo.configure('Field.TLabel', background=colores['superficie'],
                         foreground=colores['texto_secundario'], font=('Segoe UI', 9, 'bold'))
        estilo.configure('TLabelframe', background=colores['superficie'],
                         bordercolor=colores['borde'], relief='solid', borderwidth=1)
        estilo.configure('TLabelframe.Label', background=colores['superficie'],
                         foreground=colores['texto'], font=('Segoe UI', 10, 'bold'))
        estilo.configure('TEntry', fieldbackground=colores['superficie'],
                         foreground=colores['texto'], padding=(8, 7))
        estilo.configure('TButton', padding=(12, 8), font=('Segoe UI', 9, 'bold'))
        estilo.configure('Primary.TButton', background=colores['guinda'],
                         foreground='#ffffff', bordercolor=colores['guinda'])
        estilo.map('Primary.TButton',
                   background=[('active', colores['guinda_hover']), ('disabled', '#c8b7bd')],
                   foreground=[('disabled', '#ffffff')])
        estilo.configure('Secondary.TButton', background=colores['superficie'],
                         foreground=colores['guinda'], bordercolor=colores['borde'])
        estilo.map('Secondary.TButton', background=[('active', colores['guinda_suave'])])
        estilo.configure('Quiet.TButton', background=colores['fondo'],
                         foreground=colores['texto_secundario'], borderwidth=0)
        estilo.map('Quiet.TButton', foreground=[('active', colores['guinda'])])
        estilo.configure('Horizontal.TProgressbar', troughcolor=colores['borde'],
                         background=colores['guinda'], thickness=8, borderwidth=0)
        estilo.configure('TCheckbutton', background=colores['superficie'],
                         foreground=colores['texto'])
    def _navegar(self, pantalla):
        self.pagina_actual = pantalla
        pantalla.tkraise()
        self._actualizar_navegacion_secuencial()

    def _cambio_configuracion_mysql(self, *_):
        self._mysql_validado = False
        self._actualizar_panel()

    def _actualizar_navegacion_secuencial(self):
        if not hasattr(self, 'page_container') or not hasattr(self, 'frame_conexion'):
            return
        access_validado = bool(
            getattr(self, '_validacion_access', None)
            and self._validacion_access == self._firma_access(self.var_access_path.get().strip())
        )
        conexiones_listas = access_validado and getattr(self, '_mysql_validado', False)
        configuracion_lista = getattr(self, '_configuracion_confirmada', False)
        actual = self.pagina_actual
        disponible = {
            self.panel_lotes: True,
            self.frame_conexion: not self.migracion_en_curso,
            self.frame_config: conexiones_listas and not self.migracion_en_curso,
            self.frame_migracion: conexiones_listas and configuracion_lista,
            self.frame_log: True,
        }
        if not disponible.get(actual, False):
            actual = (
                self.frame_config if conexiones_listas and not configuracion_lista
                else self.frame_conexion if not conexiones_listas
                else self.panel_lotes
            )
            self.pagina_actual = actual
            actual.tkraise()

        for pantalla, boton in self._nav_items.items():
            seleccionada = pantalla == actual
            habilitado = disponible.get(pantalla, False)
            boton.configure(
                state='normal' if habilitado else 'disabled',
                bg=(self.COLORES['barra_lateral_activa'] if seleccionada
                    else self.COLORES['barra_lateral']),
                fg=('#ffffff' if seleccionada else '#f7f2f4' if habilitado
                    else self.COLORES['barra_lateral_muted']),
                font=('Segoe UI', 10, 'bold' if seleccionada else 'normal'),
            )
        if hasattr(self, 'btn_siguiente_config'):
            self.btn_siguiente_config.configure(
                state='normal' if conexiones_listas and not self.migracion_en_curso else 'disabled',
            )
        if hasattr(self, 'btn_siguiente_migracion'):
            self.btn_siguiente_migracion.configure(
                state='normal' if conexiones_listas and not self.migracion_en_curso else 'disabled',
            )

    def _continuar_a_configuracion(self):
        if not self._validacion_access or not self._mysql_validado:
            messagebox.showwarning(
                'Completa la conexión',
                'Valida primero el archivo Access y la conexión MySQL para continuar.',
            )
            return
        self._navegar(self.frame_config)

    def _continuar_a_migracion(self):
        try:
            branch_mapping = self._parsear_json_texto(self.txt_mapeo.get('1.0', tk.END), {})
            status_mapping = self._parsear_json_texto(
                self.txt_status.get('1.0', tk.END), self.marc_converter.mapping_defaults(),
            )
            self._validar_mapeo_runtime(branch_mapping, 'sucursales')
            self._validar_mapeo_runtime(status_mapping, 'estados')
        except ValueError as exc:
            messagebox.showerror('Configuración no válida', str(exc))
            return
        self._configuracion_confirmada = True
        self._actualizar_navegacion_secuencial()
        self._navegar(self.frame_migracion)

    def _configuracion_modificada(self, *_):
        self._configuracion_confirmada = False
        self._actualizar_navegacion_secuencial()

    def _texto_mapeo_modificado(self, evento):
        widget = evento.widget
        if widget.edit_modified():
            widget.edit_modified(False)
            self._configuracion_modificada()

    def _campo(self, parent, fila, col, texto, valor, ancho=30, show=None):
        ttk.Label(parent, text=texto, style='Field.TLabel').grid(
            row=fila, column=col*2, sticky='w', padx=(4, 8), pady=7,
        )
        var = tk.StringVar(value=valor)
        entry = ttk.Entry(parent, textvariable=var, width=ancho, show=show)
        entry.grid(row=fila, column=col*2+1, sticky='ew', padx=(0, 14), pady=7)
        return var

    @staticmethod
    def _encabezado_pagina(parent, titulo, descripcion):
        ttk.Label(parent, text=titulo, style='PageTitle.TLabel').pack(anchor='w')
        ttk.Label(
            parent, text=descripcion, style='PageSubtitle.TLabel',
            wraplength=950,
        ).pack(anchor='w', pady=(4, 18))

    def _crear_pestana_conexion(self):
        f = self.frame_conexion
        f.configure(padding=(22, 18, 22, 20))
        self._encabezado_pagina(
            f, 'Conecta tus datos',
            'Selecciona el respaldo de Access y valida el destino MySQL antes de continuar.',
        )
        tarjetas = ttk.Frame(f, style='App.TFrame')
        tarjetas.pack(fill='both', expand=True)
        tarjetas.columnconfigure(0, weight=1, uniform='conexion')
        tarjetas.columnconfigure(1, weight=1, uniform='conexion')
        lbl_access = ttk.LabelFrame(
            tarjetas, text='  01 · ORIGEN ACCESS  ', padding=(18, 14),
        )
        lbl_access.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        self.var_access_path = tk.StringVar(value=self.config.get('access', {}).get('path', ''))
        self.var_access_path.trace_add('write', lambda *_: self._actualizar_info_access())
        fila_archivo = ttk.Frame(lbl_access)
        fila_archivo.pack(fill='x', pady=(2, 12))
        fila_archivo.columnconfigure(0, weight=1)
        ttk.Entry(fila_archivo, textvariable=self.var_access_path).grid(
            row=0, column=0, sticky='ew', padx=(0, 8)
        )
        ttk.Button(
            fila_archivo, text='Examinar…', style='Secondary.TButton',
            command=self._seleccionar_access,
        ).grid(
            row=0, column=1,
        )
        ttk.Label(
            lbl_access, text='El archivo se abrirá en modo de solo lectura.',
            style='CardHint.TLabel',
        ).pack(anchor='w', pady=(0, 14))
        self.lbl_info_access = ttk.Label(
            lbl_access, text='Archivo seleccionado: --', anchor='w',
            style='CardBody.TLabel', wraplength=430,
        )
        self.lbl_info_access.pack(fill='x', pady=(0, 12))
        self.lbl_conteo_access = ttk.Label(
            lbl_access, text='Registros FICHAS: pendientes de validar',
            style='CardMetric.TLabel',
        )
        self.lbl_conteo_access.pack(anchor='w', pady=(0, 14))
        ttk.Button(
            lbl_access, text='Validar conexión Access', style='Primary.TButton',
            command=self._probar_access,
        ).pack(anchor='w')
        self._actualizar_info_access()

        lbl_mysql = ttk.LabelFrame(
            tarjetas, text='  02 · DESTINO MYSQL  ', padding=(18, 14),
        )
        lbl_mysql.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        lbl_mysql.columnconfigure(1, weight=1)
        lbl_mysql.columnconfigure(3, weight=1)

        self.entry_host = self._campo(lbl_mysql, 0, 0, 'Servidor', self.config.get('mysql', {}).get('host', 'localhost'))
        self.entry_port = self._campo(lbl_mysql, 0, 1, 'Puerto', str(self.config.get('mysql', {}).get('port', 3306)), ancho=8)
        self.entry_user = self._campo(lbl_mysql, 1, 0, 'Usuario', self.config.get('mysql', {}).get('user', 'root'))
        self.entry_pass = self._campo(lbl_mysql, 1, 1, 'Contraseña', self.config.get('mysql', {}).get('password', ''), show='*')
        self.entry_db = self._campo(lbl_mysql, 2, 0, 'Base de datos', self.config.get('mysql', {}).get('database', 'prometeo_marc'))
        ttk.Label(
            lbl_mysql, text='Aquí se guardarán los registros MARC21 y los ejemplares.',
            style='CardHint.TLabel',
        ).grid(row=3, column=0, columnspan=4, sticky='w', padx=4, pady=(4, 14))
        ttk.Button(
            lbl_mysql, text='Validar conexión MySQL', style='Secondary.TButton',
            command=self._probar_mysql,
        ).grid(row=4, column=0, sticky='w', padx=4)
        self.lbl_conteo_mysql = ttk.Label(
            lbl_mysql, text='Destino pendiente de validar', style='CardMetric.TLabel',
        )
        self.lbl_conteo_mysql.grid(row=4, column=1, columnspan=3, sticky='w', padx=10)

        self.btn_siguiente_config = ttk.Button(
            f, text='Siguiente: configuración  →', style='Primary.TButton',
            command=self._continuar_a_configuracion, state='disabled',
        )
        self.btn_siguiente_config.pack(anchor='e', pady=(16, 0))

    def _crear_pestana_migracion(self):
        f = self.frame_migracion
        f.configure(padding=(22, 18, 22, 20))
        self._encabezado_pagina(
            f, 'Ejecuta la migración',
            'El proceso conserva avances por lote. Los valores no contemplados se registran como incidencias; no se infieren correspondencias.',
        )

        lbl_opts = ttk.LabelFrame(
            f, text='  ALCANCE DEL PROCESO  ', padding=(18, 12),
        )
        lbl_opts.pack(fill='x', pady=(0, 14))

        self.var_limite = tk.StringVar(value='0')
        ttk.Label(
            lbl_opts, text='Cantidad de fichas', style='Field.TLabel',
        ).pack(side='left', padx=(2, 8))
        ttk.Entry(lbl_opts, textvariable=self.var_limite, width=12).pack(side='left', padx=(0, 8))
        ttk.Label(
            lbl_opts, text='0 = procesar todas las fichas del respaldo',
            style='CardHint.TLabel',
        ).pack(side='left', padx=(0, 24))

        self.var_saltar_existentes = tk.BooleanVar(value=True)
        ttk.Checkbutton(lbl_opts, text='Saltar registros ya migrados',
                        variable=self.var_saltar_existentes).pack(side='left')

        lbl_prog = ttk.LabelFrame(
            f, text='  ESTADO DE LA EJECUCIÓN  ', padding=(20, 18),
        )
        lbl_prog.pack(fill='both', expand=True)
        lbl_prog.columnconfigure(0, weight=1)
        ttk.Label(
            lbl_prog, text='Conversión Access → MARC21 → MySQL',
            style='CardTitle.TLabel',
        ).grid(row=0, column=0, sticky='w', pady=(0, 5))
        ttk.Label(
            lbl_prog, text='Puedes detener el proceso de forma segura; se conservarán las fichas ya guardadas.',
            style='CardHint.TLabel',
        ).grid(row=1, column=0, sticky='w', pady=(0, 20))

        self.progress = ttk.Progressbar(lbl_prog, orient='horizontal', mode='determinate')
        self.progress.grid(row=2, column=0, sticky='ew', pady=(0, 10))

        self.lbl_estado = ttk.Label(lbl_prog, text='Listo para iniciar.', style='CardMetric.TLabel')
        self.lbl_estado.grid(row=3, column=0, sticky='w', pady=(0, 6))

        self.lbl_stats = ttk.Label(lbl_prog, text='Correctos: 0  ·  Omitidos: 0  ·  Errores: 0')
        self.lbl_stats.grid(row=4, column=0, sticky='w')
        btn_frame = ttk.Frame(lbl_prog, style='App.TFrame')
        btn_frame.grid(row=5, column=0, sticky='ew', pady=(24, 0))
        self.btn_ejecutar = ttk.Button(
            btn_frame, text='Iniciar migración', style='Primary.TButton',
            command=self._iniciar_migracion,
        )
        self.btn_ejecutar.pack(side='left', padx=(0, 8))
        self.btn_detener = ttk.Button(
            btn_frame, text='Detener con seguridad', style='Secondary.TButton',
            command=self._solicitar_detencion, state='disabled',
        )
        self.btn_detener.pack(side='left', padx=(0, 8))
        self.btn_exportar = ttk.Button(
            btn_frame, text='Exportar MARCXML', style='Secondary.TButton',
            command=self._exportar_marcxml,
        )
        self.btn_exportar.pack(side='left')

    def _crear_pestana_config(self):
        f = self.frame_config
        f.configure(padding=(22, 18, 22, 20))
        self._encabezado_pagina(
            f, 'Revisa la configuración',
            'Define equivalencias explícitas para Koha. Si un valor no tiene regla autorizada, se omitirá y quedará señalado en las incidencias.',
        )
        tarjetas = ttk.Frame(f, style='App.TFrame')
        tarjetas.pack(fill='both', expand=True)
        tarjetas.columnconfigure(0, weight=1, uniform='mapeos')
        tarjetas.columnconfigure(1, weight=1, uniform='mapeos')

        lbl_map = ttk.LabelFrame(
            tarjetas, text='  SUCURSALES · ACCESS → KOHA  ', padding=(14, 12),
        )
        lbl_map.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        ttk.Label(
            lbl_map, text='Código de biblioteca a código de sucursal.',
            style='CardHint.TLabel',
        ).pack(anchor='w', pady=(0, 8))
        txt_frame = ttk.Frame(lbl_map, style='Card.TFrame')
        txt_frame.pack(fill='both', expand=True)
        self.txt_mapeo = tk.Text(
            txt_frame, width=42, height=8, wrap='none',
            font=('Consolas', 10), bg='#fbfaf9', fg=self.COLORES['texto'],
            insertbackground=self.COLORES['guinda'], relief='flat',
            padx=10, pady=8, highlightthickness=1,
            highlightbackground=self.COLORES['borde'],
        )
        self.txt_mapeo.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(txt_frame, command=self.txt_mapeo.yview)
        scroll.pack(side='right', fill='y')
        self.txt_mapeo.configure(yscrollcommand=scroll.set)

        ejemplo = json.dumps(self.config.get('koha_branch_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_mapeo.insert('1.0', ejemplo)
        self.txt_mapeo.edit_modified(False)
        self.txt_mapeo.bind('<<Modified>>', self._texto_mapeo_modificado)

        lbl_status = ttk.LabelFrame(
            tarjetas, text='  ESTADO · ACCESS → KOHA  ', padding=(14, 12),
        )
        lbl_status.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        ttk.Label(
            lbl_status, text='Valores del campo Accesible a estado de ejemplar.',
            style='CardHint.TLabel',
        ).pack(anchor='w', pady=(0, 8))
        status_frame = ttk.Frame(lbl_status, style='Card.TFrame')
        status_frame.pack(fill='both', expand=True)
        self.txt_status = tk.Text(
            status_frame, width=42, height=8, wrap='none',
            font=('Consolas', 10), bg='#fbfaf9', fg=self.COLORES['texto'],
            insertbackground=self.COLORES['guinda'], relief='flat',
            padx=10, pady=8, highlightthickness=1,
            highlightbackground=self.COLORES['borde'],
        )
        self.txt_status.pack(side='left', fill='both', expand=True)
        scroll_status = ttk.Scrollbar(status_frame, command=self.txt_status.yview)
        scroll_status.pack(side='right', fill='y')
        self.txt_status.configure(yscrollcommand=scroll_status.set)
        ejemplo_status = json.dumps(self.config.get('item_status_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_status.insert('1.0', ejemplo_status)
        self.txt_status.edit_modified(False)
        self.txt_status.bind('<<Modified>>', self._texto_mapeo_modificado)

        lbl_tipos = ttk.LabelFrame(
            f, text='  VALORES PREDETERMINADOS DE KOHA  ', padding=(14, 10),
        )
        lbl_tipos.pack(fill='x', pady=(14, 10))

        grid_tipos = ttk.Frame(lbl_tipos)
        grid_tipos.pack(fill='x')
        for columna in (1, 3, 5, 7):
            grid_tipos.columnconfigure(columna, weight=1)

        self.entry_item_type_bib = self._campo(grid_tipos, 0, 0, '942$c · Tipo bibliográfico', self.var_item_type_bib.get(), ancho=12)
        self.entry_item_type_item = self._campo(grid_tipos, 0, 2, '952$y · Tipo de ejemplar', self.var_item_type_item.get(), ancho=12)
        self.entry_homebranch = self._campo(grid_tipos, 1, 0, '952$a · Homebranch', self.var_homebranch.get(), ancho=12)
        self.entry_holdingbranch = self._campo(grid_tipos, 1, 2, '952$b · Holdingbranch', self.var_holdingbranch.get(), ancho=12)
        for variable in (
            self.entry_item_type_bib, self.entry_item_type_item,
            self.entry_homebranch, self.entry_holdingbranch,
        ):
            variable.trace_add('write', self._configuracion_modificada)

        acciones = ttk.Frame(f, style='App.TFrame')
        acciones.pack(fill='x')
        ttk.Button(
            acciones, text='← Volver a conexiones', style='Quiet.TButton',
            command=lambda: self._navegar(self.frame_conexion),
        ).pack(side='left')
        ttk.Button(
            acciones, text='Guardar configuración', style='Secondary.TButton',
            command=self._guardar_config,
        ).pack(side='right', padx=(8, 0))
        self.btn_siguiente_migracion = ttk.Button(
            acciones, text='Continuar a migración  →', style='Primary.TButton',
            command=self._continuar_a_migracion, state='disabled',
        )
        self.btn_siguiente_migracion.pack(side='right')

    def _crear_pestana_log(self):
        f = self.frame_log
        f.configure(padding=(22, 18, 22, 20))
        self._encabezado_pagina(
            f, 'Actividad del sistema',
            'Mensajes de validación, avance e incidencias registrados durante la sesión.',
        )
        contenedor = ttk.Frame(f, style='Card.TFrame', padding=10)
        contenedor.pack(fill='both', expand=True)
        self.txt_log = tk.Text(
            contenedor, wrap='word', width=100, height=25,
            font=('Consolas', 9), bg='#fbfaf9', fg=self.COLORES['texto'],
            insertbackground=self.COLORES['guinda'], relief='flat',
            padx=12, pady=10,
        )
        self.txt_log.pack(fill='both', expand=True)
        ttk.Button(
            f, text='Limpiar actividad', style='Quiet.TButton',
            command=lambda: self.txt_log.delete('1.0', tk.END),
        ).pack(anchor='e', pady=(8, 0))

    def cargar_config(self) -> Dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _cargar_config_en_ui(self):
        self.var_access_path.set(self.config.get('access', {}).get('path', ''))
        self.entry_host.set(self.config.get('mysql', {}).get('host', 'localhost'))
        self.entry_port.set(str(self.config.get('mysql', {}).get('port', 3306)))
        self.entry_user.set(self.config.get('mysql', {}).get('user', 'root'))
        self.entry_pass.set(self.config.get('mysql', {}).get('password', ''))
        self.entry_db.set(self.config.get('mysql', {}).get('database', 'prometeo_marc'))

        self.var_item_type_bib.set(self.config.get(
            'item_type_bib', self.marc_converter.item_type_bib))
        self.var_item_type_item.set(self.config.get(
            'item_type_item', self.marc_converter.item_type_item))
        self.var_homebranch.set(self.config.get(
            'homebranch', self.marc_converter.homebranch))
        self.var_holdingbranch.set(self.config.get(
            'holdingbranch', self.marc_converter.holdingbranch))

        branch_map = self.config.get('koha_branch_mapping', {})
        status_map = self.config.get('item_status_mapping')

        if not branch_map:
            branch_map = {}
        if status_map is None:
            status_map = self.marc_converter.mapping_defaults()

        self.txt_mapeo.delete('1.0', tk.END)
        self.txt_mapeo.insert('1.0', json.dumps(branch_map, indent=2, ensure_ascii=False))

        self.txt_status.delete('1.0', tk.END)
        self.txt_status.insert('1.0', json.dumps(status_map, indent=2, ensure_ascii=False))

    def _guardar_config(self):
        if not self._sesion_valida():
            return
        try:
            branch_mapping = self._parsear_json_texto(self.txt_mapeo.get('1.0', tk.END), {})
            status_mapping = self._parsear_json_texto(
                self.txt_status.get('1.0', tk.END), self.marc_converter.mapping_defaults())
            self._validar_mapeo_runtime(branch_mapping, 'sucursales')
            self._validar_mapeo_runtime(status_mapping, 'estados')
        except ValueError as exc:
            messagebox.showerror('Mapeo no válido', str(exc))
            return
        # Recopila los valores visibles y los persiste como JSON.
        config = {
            'access': {
                'path': self.var_access_path.get(),
                'driver': '{Microsoft Access Driver (*.mdb, *.accdb)}',
            },
            'mysql': {
                'host': self.entry_host.get(),
                'port': int(self.entry_port.get() or 3306),
                'user': self.entry_user.get(),
                'password': self.entry_pass.get(),
                'database': self.entry_db.get(),
                'charset': 'utf8mb4',
            },
            'koha_branch_mapping': branch_mapping,
            'item_status_mapping': status_mapping,
            'item_type_bib': self.entry_item_type_bib.get(),
            'item_type_item': self.entry_item_type_item.get(),
            'homebranch': self.entry_homebranch.get(),
            'holdingbranch': self.entry_holdingbranch.get(),
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self.config = config
            self._configuracion_confirmada = True
            messagebox.showinfo('Exito', 'Configuracion guardada.')
            self.log('Configuracion guardada.')
            self._actualizar_panel()
        except Exception as e:
            messagebox.showerror('Error', 'No se pudo guardar la configuracion:\n' + str(e))

    def _parsear_json_texto(self, texto: str, default: Any) -> Any:
        texto = texto.strip()
        if not texto:
            return default
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ValueError(f'JSON no válido en el mapeo: {exc.msg} (línea {exc.lineno}).') from exc

    @staticmethod
    def _validar_mapeo_runtime(mapeo, nombre):
        if (not isinstance(mapeo, dict)
                or any(not isinstance(origen, str) or not origen.strip()
                       or not isinstance(destino, str) or not destino.strip()
                       for origen, destino in mapeo.items())):
            raise ValueError(
                f'El mapeo de {nombre} debe ser un objeto JSON con claves y valores de texto no vacíos.'
            )

    def log(self, mensaje: str):
        if threading.current_thread() is not threading.main_thread():
            self._eventos_ui.put((self.log, (mensaje,)))
            return
        self.txt_log.insert(tk.END, mensaje + '\n')
        self.txt_log.see(tk.END)

    def _publicar_ui(self, funcion, *args):
        self._eventos_ui.put((funcion, args))

    def _procesar_eventos_ui(self):
        if self._cerrando:
            return
        for _ in range(100):
            try:
                funcion, args = self._eventos_ui.get_nowait()
            except Empty:
                break
            try:
                funcion(*args)
            except Exception as exc:
                self.log('[ERROR] No se pudo actualizar la vista del lote: ' + str(exc))
        self._after_ui = self.root.after(100, self._procesar_eventos_ui)

    @staticmethod
    def _firma_access(path):
        try:
            datos = os.stat(path)
            return (os.path.normcase(os.path.abspath(path)), datos.st_size, datos.st_mtime_ns)
        except OSError:
            return None

    def _destino_actual(self):
        try:
            return {'host': self.entry_host.get().strip(), 'port': int(self.entry_port.get() or 3306),
                    'database': self.entry_db.get().strip()}
        except ValueError:
            return {}

    def _politica_lote(self, lote, demostracion=False):
        firma = self._firma_access(self.var_access_path.get().strip()) if hasattr(self, 'var_access_path') else None
        validado = bool(lote and firma and self._validacion_access == firma
                        and os.path.normcase(os.path.abspath(lote.fuente)) == firma[0])
        destino = self._destino_actual() if hasattr(self, 'entry_host') else {}
        politica = acciones_lote(lote, ocupado=self.migracion_en_curso, fuente_validada=validado,
                                 destino_coincide=bool(lote and lote.destino == destino), demostracion=demostracion,
                                 lote_activo_id=self._lote_actual_id, detencion_solicitada=self._detencion_solicitada.is_set())
        if self.historial_lotes.solo_lectura:
            politica['iniciar'] = False
        return politica

    def _actualizar_panel(self):
        if not hasattr(self, 'panel_lotes') or not hasattr(self, 'btn_exportar'):
            return
        self.panel_lotes.actualizar()
        lote = self.historial_lotes.obtener(self._lote_actual_id)
        self.btn_exportar.configure(state='normal' if self._politica_lote(lote)['exportar'] else 'disabled')
        self.btn_ejecutar.configure(state='disabled' if self.migracion_en_curso or self.historial_lotes.solo_lectura else 'normal')
        politica = self._politica_lote(lote)
        self.btn_detener.configure(state='normal' if politica['detener'] else 'disabled',
                                  text='Deteniendo…' if politica['detencion_solicitada'] else 'Detener migración')
        self._actualizar_navegacion_secuencial()

    def _solicitar_detencion(self, identificador=None):
        identificador = identificador or self._lote_actual_id
        lote = self.historial_lotes.obtener(identificador)
        if not self._politica_lote(lote)['detener']:
            return
        self._detencion_solicitada.set()
        self.log(f'Lote {identificador}: detención solicitada por el usuario.')
        self.lbl_estado.configure(text='Detención solicitada. Terminando la ficha u operación en curso…')
        self._actualizar_panel()

    def _iniciar_desde_panel(self, identificador):
        lote = self.historial_lotes.obtener(identificador)
        if not self._politica_lote(lote)['iniciar']:
            messagebox.showwarning('Acción no disponible', 'Valida el respaldo seleccionado antes de iniciar ese lote.')
            return
        self._lote_actual_id = identificador
        self._iniciar_migracion()

    def cerrar(self):
        if self.migracion_en_curso:
            messagebox.showwarning('Migración en curso', 'Pulsa Detener migración y espera a que termine la operación en curso antes de cerrar.')
            return
        self._cerrando = True
        self.root.after_cancel(self._after_ui)
        if self.mysql_writer:
            self.mysql_writer.close()
        self.root.destroy()

    def _sesion_valida(self) -> bool:
        if not hasattr(self, 'auth_service') or self.auth_service is None:
            return True
        try:
            self.auth_service.require_authenticated(self.session_token)
            return True
        except PermissionError as error:
            messagebox.showerror('Sesion cerrada', str(error))
            return False

    def _cerrar_sesion(self):
        if self.auth_service is not None:
            self.auth_service.logout(self.session_token)
        if self.on_logout is not None:
            self.on_logout()
        else:
            self.cerrar()

    def _abrir_registro_usuario(self):
        try:
            self.auth_service.require_admin(self.session_token)
        except PermissionError as error:
            messagebox.showerror('Acceso denegado', str(error))
            return

        ventana = tk.Toplevel(self.root)
        ventana.title('Crear usuario')
        ventana.resizable(False, False)
        ventana.transient(self.root)
        ventana.grab_set()

        formulario = ttk.Frame(ventana, padding=20)
        formulario.pack(fill='both', expand=True)
        ttk.Label(formulario, text='Nuevo usuario').grid(row=0, column=0, columnspan=2, pady=(0, 12))
        
        ttk.Label(formulario, text='Usuario:').grid(row=1, column=0, sticky='e', padx=5, pady=5)
        entrada_usuario = ttk.Entry(formulario, width=30)
        entrada_usuario.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(formulario, text='Contrasena:').grid(row=2, column=0, sticky='e', padx=5, pady=5)
        entrada_contrasena = ttk.Entry(formulario, width=30, show='*')
        entrada_contrasena.grid(row=2, column=1, padx=5, pady=5)
        
        ttk.Label(formulario, text='Repetir contrasena:').grid(row=3, column=0, sticky='e', padx=5, pady=5)
        entrada_confirmacion = ttk.Entry(formulario, width=30, show='*')
        entrada_confirmacion.grid(row=3, column=1, padx=5, pady=5)

        ttk.Label(formulario, text='Perfil/Rol:').grid(row=4, column=0, sticky='e', padx=5, pady=5)
        combo_perfil = ttk.Combobox(formulario, values=["Ejecucion", "Revision", "Aprobacion", "Administracion"], state='readonly', width=27)
        combo_perfil.current(0)
        combo_perfil.grid(row=4, column=1, padx=5, pady=5)

        def registrar():
            try:
                self.auth_service.require_admin(self.session_token)
                usuario = entrada_usuario.get().strip()
                contrasena = entrada_contrasena.get()
                confirmacion = entrada_confirmacion.get()
                perfil = combo_perfil.get()
                if not usuario or not contrasena or not confirmacion:
                    raise ValueError('Complete todos los campos.')
                if contrasena != confirmacion:
                    raise ValueError('Las contrasenas no coinciden.')
                self.auth_service.create_user(usuario, contrasena, perfil)
            except sqlite3.IntegrityError:
                messagebox.showerror('Registro rechazado', 'Ese usuario ya existe.', parent=ventana)
                return
            except (PermissionError, ValueError) as error:
                messagebox.showerror('Registro rechazado', str(error), parent=ventana)
                return
            messagebox.showinfo('Cuenta creada', f'El usuario fue creado con perfil {perfil}.', parent=ventana)
            ventana.destroy()

        ttk.Button(formulario, text='Crear usuario', command=registrar).grid(
            row=5, column=0, columnspan=2, pady=(14, 0)
        )
        entrada_usuario.focus()

    def _seleccionar_access(self):
        path = filedialog.askopenfilename(
            title='Seleccionar base de datos Access aprobada',
            filetypes=[('Bases de datos Access', '*.mdb *.accdb'), ('Todos los archivos', '*.*')],
        )
        if path:
            self.var_access_path.set(path)

    def _actualizar_info_access(self):
        path = self.var_access_path.get().strip()
        self._validacion_access = None
        self._actualizar_panel()
        if not path:
            self.lbl_info_access.config(text='Archivo seleccionado: --')
            return

        nombre = os.path.basename(path)
        if os.path.isfile(path):
            try:
                tamano = os.path.getsize(path)
            except OSError:
                detalle_tamano = 'no disponible'
            else:
                unidades = ('B', 'KB', 'MB', 'GB', 'TB')
                valor = float(tamano)
                unidad = unidades[0]
                for unidad in unidades:
                    if valor < 1024 or unidad == unidades[-1]:
                        break
                    valor /= 1024
                detalle_tamano = f'{valor:.2f} {unidad}'
        else:
            detalle_tamano = 'no disponible'

        self.lbl_info_access.config(
            text=f'Archivo: {nombre} | Tamaño: {detalle_tamano}\nEl archivo se usa en modo solo lectura.'
        )

    def _validar_archivo_access(self, path: str) -> List[str]:
        reader = AccessReader(path)
        try:
            return reader.validar_archivo()
        finally:
            reader.close()

    def _probar_access(self):
        if not self._sesion_valida():
            return
            
        try:
            requerir_permiso(self.perfil_usuario, "validar_access")
        except AccesoDenegado as e:
            messagebox.showerror('Acceso Restringido', str(e))
            self.log(f'[BLOQUEO SEGURIDAD] {e}')
            return
            
        path = self.var_access_path.get().strip()
        if self.migracion_en_curso:
            messagebox.showwarning('Migración en curso', 'Espera a que termine el lote activo.')
            return
        if not path:
            messagebox.showwarning('Atencion', 'Seleccione primero un archivo .mdb o .accdb')
            return
        try:
            errores = self._validar_archivo_access(path)
            if errores:
                raise ValueError('\n'.join(errores))

            reader = AccessReader(path)
            if reader.test_connection():
                total = reader.contar_fichas()
                reader.close()
                lote = self.historial_lotes.recibir(path, total)
                self._lote_actual_id = lote.id
                self._validacion_access = self._firma_access(path)
                self.panel_lotes.seleccionar_real(lote.id)
                self._actualizar_panel()
                self.lbl_conteo_access.config(text='Registros FICHAS: ' + str(total))
                self.log('[OK] Conexion Access exitosa. ' + str(total) + ' fichas encontradas.')
                messagebox.showinfo('Exito', 'Conexion Access exitosa.\n' + str(total) + ' registros en FICHAS.')
            else:
                raise Exception('No se pudo conectar.')
        except Exception as e:
            self.log('[ERROR] Access: ' + str(e))
            messagebox.showerror('Error', 'No se pudo conectar a Access:\n' + str(e))

    def _probar_mysql(self):
        if not self._sesion_valida():
            return
        self._mysql_validado = False
        self._configuracion_confirmada = False
        config = {
            'host': self.entry_host.get(),
            'port': int(self.entry_port.get() or 3306),
            'user': self.entry_user.get(),
            'password': self.entry_pass.get(),
            'database': self.entry_db.get(),
            'charset': 'utf8mb4',
        }
        try:
            writer = MySQLWriter(config)
            if writer.test_connection():
                writer.crear_tablas()
                self.mysql_writer = writer
                self._mysql_validado = True
                stats = self._obtener_stats_mysql(config)
                self.lbl_conteo_mysql.config(text='Registros migrados: ' + str(stats['total_registros']))
                self.log('[OK] Conexion MySQL exitosa. Tablas verificadas.')
                messagebox.showinfo('Exito', 'Conexion MySQL exitosa y tablas creadas/verificadas.')
            else:
                raise Exception('No se pudo conectar.')
        except Exception as e:
            msg = str(e)
            if 'Unknown database' in msg or 'unknown database' in msg:
                crear = messagebox.askyesno(
                    'Base de datos no existe',
                    f'La base de datos "{config["database"]}" no existe.\n\n'
                    '¿Quieres crearla automáticamente?'
                )
                if crear:
                    try:
                        writer = MySQLWriter(config)
                        writer.ensure_database()
                        writer.crear_tablas()
                        self.mysql_writer = writer
                        self._mysql_validado = True
                        stats = self._obtener_stats_mysql(config)
                        self.lbl_conteo_mysql.config(text='Registros migrados: ' + str(stats['total_registros']))
                        self.log('[OK] Base de datos creada y tablas verificadas.')
                        messagebox.showinfo('Exito', 'Base de datos creada y tablas verificadas.')
                    except Exception as e2:
                        self.log('[ERROR] MySQL: ' + str(e2))
                        messagebox.showerror('Error', 'No se pudo crear la base de datos:\n' + str(e2))
                else:
                    self.log('[INFO] Usuario canceló la creación de la base de datos.')
            else:
                self.log('[ERROR] MySQL: ' + msg)
                messagebox.showerror('Error', 'No se pudo conectar a MySQL:\n' + msg)
        finally:
            self._actualizar_panel()

    def _obtener_stats_mysql(self, config: Dict) -> Dict:
        try:
            writer = MySQLWriter(config)
            stats = writer.obtener_estadisticas()
            writer.close()
            return stats
        except Exception:
            return {'total_registros': 0, 'total_ejemplares': 0, 'por_estado': {}}

    def _iniciar_migracion(self):
        if not self._sesion_valida():
            return
            
        try:
            requerir_permiso(self.perfil_usuario, "iniciar_conversion")
        except AccesoDenegado as e:
            messagebox.showerror('Acceso Restringido', str(e))
            self.log(f'[BLOQUEO SEGURIDAD] {e}')
            return
            
        if self.migracion_en_curso:
            messagebox.showwarning('Atencion', 'Ya hay una migracion en curso.')
            return
        if self.historial_lotes.solo_lectura:
            messagebox.showerror('Historial no disponible', 'Resuelve el problema del historial antes de iniciar otra migración.')
            return

        path_access = self.var_access_path.get().strip()
        if not path_access or not os.path.exists(path_access):
            messagebox.showerror('Error', 'Seleccione un archivo .mdb o .accdb valido.')
            return

        try:
            errores_validacion = self._validar_archivo_access(path_access)
        except Exception as e:
            errores_validacion = [f'No se pudo validar el archivo Access: {e}']
        if errores_validacion:
            mensaje = '\n'.join(errores_validacion)
            self.log('[ERROR] Validacion Access: ' + mensaje.replace('\n', ' | '))
            messagebox.showerror(
                'Archivo Access no valido',
                'No se iniciara la migracion porque el archivo no cumple los requisitos:\n\n'
                + mensaje,
            )
            return

        config_mysql = {
            'host': self.entry_host.get(),
            'port': self.entry_port.get() or '3306',
            'user': self.entry_user.get(),
            'password': self.entry_pass.get(),
            'database': self.entry_db.get(),
            'charset': 'utf8mb4',
        }

        limite_str = self.var_limite.get().strip()
        try:
            if not limite_str.isdigit():
                raise ValueError('El límite debe ser un entero no negativo; 0 significa todos.')
            limite = int(limite_str)
            config_mysql['port'] = int(config_mysql['port'])
            if not 1 <= config_mysql['port'] <= 65535:
                raise ValueError('El puerto MySQL debe estar entre 1 y 65535.')
            reader = AccessReader(path_access)
            try:
                total = reader.contar_fichas()
            finally:
                reader.close()
            lote = self.historial_lotes.recibir(path_access, total)
            self._lote_actual_id = lote.id
            self._validacion_access = self._firma_access(path_access)
            self.panel_lotes.seleccionar_real(lote.id)
            if not total:
                self.historial_lotes.actualizar(lote.id, estado='con_incidencias',
                    incidencias=[{'referencia': 'Origen', 'mensaje': 'El respaldo no contiene fichas para migrar.'}],
                    evento='Ejecución detenida: el respaldo no contiene fichas.')
                self._actualizar_panel()
                messagebox.showwarning('Sin registros', 'El respaldo no contiene fichas para migrar.')
                return
        except Exception as exc:
            messagebox.showerror('No se pudo preparar el lote', str(exc))
            return
        saltar = self.var_saltar_existentes.get()

        try:
            branch_mapping = self._parsear_json_texto(
                self.txt_mapeo.get('1.0', tk.END), {})
            status_mapping = self._parsear_json_texto(
                self.txt_status.get('1.0', tk.END),
                MarcConverter.mapping_defaults(),
            )
            self._validar_mapeo_runtime(branch_mapping, 'sucursales')
            self._validar_mapeo_runtime(status_mapping, 'estados')
            self._configuracion_confirmada = True
            conversor = MarcConverter(
                item_type_bib=self.entry_item_type_bib.get(),
                item_type_item=self.entry_item_type_item.get(),
                homebranch=self.entry_homebranch.get(),
                holdingbranch=self.entry_holdingbranch.get(),
            )
            huella_mapeo = conversor.mapping_fingerprint(branch_mapping, status_mapping)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Mapeo no válido', str(exc))
            return
        self.marc_converter = conversor

        try:
            self.historial_lotes.actualizar(lote.id, estado='en_proceso', etapa='conexion',
                total_objetivo=min(total, limite) if limite else total, destino=self._destino_actual(),
                version_mapeo=self.marc_converter.mapping_version,
                huella_mapeo=huella_mapeo,
                evento=(f'Migración iniciada con mapeo MARC21 versión '
                        f'{self.marc_converter.mapping_version} '
                        f'(SHA-256 {huella_mapeo}). Conectando al destino MySQL.'))
        except (OSError, ValueError) as exc:
            messagebox.showerror('No se pudo registrar el lote', str(exc))
            return
        self.migracion_en_curso = True
        self._detencion_solicitada.clear()
        self.btn_ejecutar.config(state='disabled')
        self.progress['value'] = 0
        self.lbl_estado.config(text='Iniciando...')
        self.btn_exportar.configure(state='disabled')
        self._actualizar_panel()
        self._navegar(self.frame_migracion)

        hilo = threading.Thread(
            target=self._ejecutar_migracion,
            args=(path_access, config_mysql, limite, saltar, branch_mapping, status_mapping, lote.id),
            daemon=True,
        )
        try:
            hilo.start()
        except RuntimeError as exc:
            self.historial_lotes.actualizar(lote.id, estado='con_incidencias',
                incidencias=[{'referencia': 'Ejecución', 'mensaje': str(exc)}],
                evento='No se pudo iniciar el hilo de migración.')
            self._finalizar_migracion()
            messagebox.showerror('No se pudo iniciar', str(exc))

    def _ejecutar_migracion(self, path_access, config_mysql, limite, saltar,
                            branch_mapping, status_mapping, lote_id):
        reader = writer = None
        cont_ok = cont_err = cont_omitidos = cont_ejemplares = 0
        fichas_correctas = []
        incidencias = []
        ultimo_avance = monotonic()

        def mensaje_seguro(exc):
            mensaje = str(exc)
            clave = config_mysql.get('password')
            return mensaje.replace(clave, '***') if clave else mensaje

        def guardar_avance(**extra):
            self.historial_lotes.actualizar(lote_id, correctos=cont_ok, errores=cont_err,
                omitidos=cont_omitidos, ejemplares=cont_ejemplares,
                fichas_correctas=fichas_correctas, incidencias=incidencias[-100:], **extra)
            self._publicar_ui(self._mostrar_avance_lote, lote_id)

        def comprobar_detencion():
            if self._detencion_solicitada.is_set():
                raise _DetencionSolicitada()

        try:
            comprobar_detencion()
            reader = AccessReader(path_access)
            writer = MySQLWriter(config_mysql)
            comprobar_detencion()
            writer.connect()
            comprobar_detencion()
            writer.crear_tablas()
            comprobar_detencion()
            guardar_avance(etapa='lectura', evento='Destino conectado. Leyendo fichas del respaldo.')
            lote = self.historial_lotes.obtener(lote_id)
            total_origen = reader.contar_fichas()
            comprobar_detencion()
            if total_origen != lote.total_recibidos:
                raise ValueError('El respaldo cambió después de validarlo. Revisa la copia y vuelve a validarla.')
            total_fichas = lote.total_objetivo
            self.log(f'Lote {lote_id}: {total_fichas} fichas a procesar de {lote.total_recibidos} recibidas.')
            fichas = reader.leer_fichas(limite=limite if limite > 0 else None)
            comprobar_detencion()
            if len(fichas) != total_fichas:
                raise ValueError('El número de fichas leídas no coincide con el alcance del lote.')
            guardar_avance(etapa='conversion', evento='Convirtiendo fichas a MARC21 y guardando ejemplares.')
            for idx, ficha in enumerate(fichas, start=1):
                comprobar_detencion()
                id_ficha = None
                try:
                    id_ficha = int(ficha['Ficha_No'])
                    if saltar and writer.registrar_existe(id_ficha):
                        cont_omitidos += 1
                    else:
                        ejemplares = reader.leer_ejemplares_por_ficha([id_ficha]).get(id_ficha, [])
                        incidencias_conversion = []
                        record = self.marc_converter.ficha_a_record(ficha, ejemplares,
                            branch_mapping=branch_mapping, status_mapping=status_mapping,
                            incidencias=incidencias_conversion)
                        referencia = f'Ficha {id_ficha}'
                        for incidencia in incidencias_conversion:
                            incidencias.append({
                                'referencia': referencia + ' · ' + incidencia['referencia'],
                                'mensaje': incidencia['mensaje'],
                            })
                            self.log(
                                f"[AVISO] Lote {lote_id}, {referencia}, "
                                f"{incidencia['referencia']}: {incidencia['mensaje']}"
                            )
                        marcxml = self.marc_converter.record_a_marcxml(record)
                        iso2709 = self.marc_converter.record_a_iso2709(record)
                        id_registro = writer.insertar_registro_marc(id_ficha, str(id_ficha), marcxml, iso2709)
                        for ej in ejemplares:
                            biblioteca = ej.get('Biblioteca')
                            bc = str(biblioteca).strip() if biblioteca is not None else ''
                            branch_code = branch_mapping.get(bc) if bc else None
                            if not bc:
                                mensaje = 'Faltante: Biblioteca no tiene valor; no se asignó una sucursal Koha.'
                            elif branch_code is None:
                                mensaje = (
                                    f'No contemplado: Biblioteca={bc!r} no tiene correspondencia '
                                    'autorizada; no se asignó una sucursal Koha.'
                                )
                            else:
                                mensaje = None
                            if mensaje:
                                incidencias.append({
                                    'referencia': referencia + ' · Biblioteca',
                                    'mensaje': mensaje,
                                })
                                self.log(f'[AVISO] Lote {lote_id}, {referencia}: {mensaje}')
                            writer.insertar_ejemplar(id_registro, id_ficha, ej, branch_code,
                                                    signatura=ficha.get('Clasificacion'))
                            cont_ejemplares += 1
                        cont_ok += 1
                        fichas_correctas.append(id_ficha)
                except Exception as exc:
                    cont_err += 1
                    mensaje = mensaje_seguro(exc)
                    incidencias.append({'referencia': f'Ficha {id_ficha}' if id_ficha is not None else f'Fila {idx}', 'mensaje': mensaje})
                    self.log(f'[ERROR] Lote {lote_id}, ficha {id_ficha}: {mensaje}')
                    try:
                        writer.insertar_log('ERROR', mensaje, id_ficha=id_ficha)
                    except Exception:
                        pass
                if idx % 25 == 0 or idx == total_fichas or monotonic() - ultimo_avance >= 0.5:
                    guardar_avance()
                    ultimo_avance = monotonic()
            tiene_incidencias = bool(cont_err or incidencias)
            estado = 'con_incidencias' if tiene_incidencias else 'concluido'
            guardar_avance(estado=estado, etapa='revision' if tiene_incidencias else 'finalizado',
                           evento=f'Ejecución terminada. Correctos: {cont_ok}; omitidos: {cont_omitidos}; errores: {cont_err}.')
            self.log(f'Lote {lote_id} finalizado. OK: {cont_ok}, omitidos: {cont_omitidos}, errores: {cont_err}.')
            self._publicar_ui(self._finalizar_migracion)
            self._publicar_ui(messagebox.showwarning if tiene_incidencias else messagebox.showinfo,
                'Lote con incidencias' if tiene_incidencias else 'Lote concluido',
                f'Correctos: {cont_ok}\nOmitidos: {cont_omitidos}\nErrores: {cont_err}'
                f'\nIncidencias: {len(incidencias)}\nEjemplares: {cont_ejemplares}')
        except _DetencionSolicitada:
            try:
                lote = self.historial_lotes.obtener(lote_id)
                pendientes = lote.total_objetivo - cont_ok - cont_omitidos - cont_err
                guardar_avance(estado='detenido', evento=(f'Detenido por el usuario. Correctos: {cont_ok}; '
                    f'omitidos: {cont_omitidos}; errores: {cont_err}; pendientes: {pendientes}.'))
                self.log(f'Lote {lote_id} detenido. Se conservaron los avances; pendientes: {pendientes}.')
                self._publicar_ui(self._finalizar_migracion)
                self._publicar_ui(messagebox.showinfo, 'Migración detenida',
                    f'Se conservaron los avances guardados.\nCorrectos: {cont_ok}\nOmitidos: {cont_omitidos}'
                    f'\nErrores: {cont_err}\nPendientes: {pendientes}\nLa exportación de este lote queda bloqueada.')
            except (OSError, ValueError) as exc:
                self.log('[ERROR] No se pudo guardar la detención del lote: ' + mensaje_seguro(exc))
                self._publicar_ui(self._finalizar_migracion)
                self._publicar_ui(messagebox.showerror, 'No se pudo guardar la detención', mensaje_seguro(exc))
        except Exception as exc:
            mensaje = mensaje_seguro(exc)
            incidencias.append({'referencia': 'Ejecución', 'mensaje': mensaje})
            try:
                guardar_avance(estado='con_incidencias', evento='Ejecución interrumpida. Revisa el detalle de incidencias.')
            except (OSError, ValueError) as error_historial:
                self.log('[ERROR] No se pudo guardar el último avance del lote: ' + str(error_historial))
            self.log(f'[ERROR FATAL] Lote {lote_id}: {mensaje}')
            self._publicar_ui(self._finalizar_migracion)
            self._publicar_ui(messagebox.showerror, 'Lote con incidencias', mensaje)
        finally:
            for recurso in (reader, writer):
                if recurso:
                    try:
                        recurso.close()
                    except Exception:
                        pass

    def _mostrar_avance_lote(self, identificador):
        lote = self.historial_lotes.obtener(identificador)
        if lote is None:
            return
        self.progress['value'] = lote.progreso
        estado = {'con_incidencias': 'Con incidencias', 'concluido': 'Concluido', 'detenido': 'Detenido'}.get(lote.estado, 'En proceso')
        if lote.estado == 'en_proceso' and self._detencion_solicitada.is_set():
            estado = 'Deteniendo al terminar la ficha u operación en curso…'
        self.lbl_estado.config(text=f'{lote.id}: {lote.procesados}/{lote.total_objetivo} · {estado}')
        self.lbl_stats.config(text=f'Correctos: {lote.correctos} | Omitidos: {lote.omitidos} | Errores: {lote.errores} | Incidencias: {len(lote.incidencias)} | Ejemplares: {lote.ejemplares}')
        self._actualizar_panel()

    def _finalizar_migracion(self):
        self.migracion_en_curso = False
        self._actualizar_panel()

    def _exportar_marcxml(self, lote_id=None):
        if not self._sesion_valida():
            return
            
        try:
            requerir_permiso(self.perfil_usuario, "aprobar_exportacion")
        except AccesoDenegado as e:
            messagebox.showerror('Acceso Restringido', str(e))
            self.log(f'[BLOQUEO SEGURIDAD] {e}')
            return
            
        lote = self.historial_lotes.obtener(lote_id or self._lote_actual_id)
        if not self._politica_lote(lote)['exportar']:
            messagebox.showwarning('Exportación no disponible',
                'Selecciona un lote concluido, sin incidencias y con nuevos registros correctos. '
                'El destino MySQL debe coincidir con el usado por ese lote.')
            return

        path = filedialog.asksaveasfilename(
            title='Exportar registros MARCXML',
            initialfile=lote.id + '.xml',
            defaultextension='.xml',
            filetypes=[('MARCXML', '*.xml'), ('Todos', '*.*')],
        )
        if not path:
            return
        writer = None
        try:
            config = {**self._destino_actual(), 'user': self.entry_user.get(),
                      'password': self.entry_pass.get(), 'charset': 'utf8mb4'}
            writer = MySQLWriter(config)
            writer.connect()
            filas = []
            for inicio in range(0, len(lote.fichas_correctas), 500):
                fichas = lote.fichas_correctas[inicio:inicio + 500]
                parametros = ','.join(['%s'] * len(fichas))
                with writer.conn.cursor() as cur:
                    cur.execute('SELECT marca_marcxml FROM registros_marc '
                                f'WHERE id_ficha_acceso IN ({parametros}) ORDER BY id_ficha_acceso', tuple(fichas))
                    filas.extend(cur.fetchall())
            if len(filas) != lote.correctos:
                raise ValueError('El destino ya no contiene todos los registros correctos de este lote. No se exportó el archivo.')

            registros = []
            for fila in filas:
                xml = fila['marca_marcxml']
                start = xml.find('<record>')
                end = xml.find('</record>')
                if start == -1 or end == -1:
                    raise ValueError('Un registro no contiene el MARCXML esperado. Revisa el destino antes de exportar.')
                registros.append(xml[start:end + len('</record>')])

            with open(path, 'w', encoding='utf-8') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<collection xmlns="http://www.loc.gov/MARC21/slim">\n')
                for record_xml in registros:
                    f.write(record_xml + '\n')
                f.write('</collection>\n')

            self.historial_lotes.actualizar(lote.id, evento=f'Se exportaron {len(filas)} registros correctos a MARCXML.')
            self._actualizar_panel()
            messagebox.showinfo('Exito', f'Exportados {len(filas)} registros del lote {lote.id} a {path}')
        except Exception as e:
            clave = self.entry_pass.get()
            mensaje = str(e).replace(clave, '***') if clave else str(e)
            messagebox.showerror('Error', mensaje)
        finally:
            if writer:
                writer.close()