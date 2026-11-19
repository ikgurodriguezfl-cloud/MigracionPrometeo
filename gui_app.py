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
from lotes import ETAPAS, HistorialLotes, acciones_lote, ahora
from panel_lotes import PanelLotes
from permissions import (
    requerir_permiso, AccesoDenegado, tiene_permiso,
)
from ui_kit import (
    FONDO, SUPERFICIE, SUPERFICIE_ALT, TEXTO, TEXTO_SECUNDARIO,
    TEXTO_MUTADO, TEXTO_INVERSO,
    PRIMARIO, PRIMARIO_HOVER, PRIMARIO_ACTIVO, PRIMARIO_SUAVE,
    BARRA_LATERAL, BARRA_LATERAL_HOVER, BARRA_LATERAL_ACTIVA, BARRA_LATERAL_MUTADO,
    NOCHE, NOCHE_ALT, NOCHE_BORDE,
    BORDE, BORDE_ENFOQUE, EXITO, EXITO_SUAVE, ADVERTENCIA, ADVERTENCIA_SUAVE,
    ERROR, ERROR_SUAVE, INFO, INFO_SUAVE,
    FUENTE, FUENTE_MONO,
    TAM_TITULO_PAGINA, TAM_SUBTITULO_PAGINA, TAM_TARJETA_TITULO,
    TAM_CAMPO_ETIQUETA, TAM_CAMPO_ENTRADA, TAM_CUERPO, TAM_BOTON,
    TAM_TABLA_ENCABEZADO, TAM_TABLA_CUERPO, TAM_METRICA_VALOR, TAM_METRICA_ETIQUETA,
    ESPACIO_XS, ESPACIO_S, ESPACIO_M, ESPACIO_L, ESPACIO_XL,
    instalar_estilos, tarjeta, seccion_tarjeta, campo_formulario,
    encabezado_pagina, boton_accion, badge_estado, mensaje_estado, separador,
    animar_valor, crear_icono, colorear_icono,
    COLORES_ESTADO_LOTE,
)


class _DetencionSolicitada(Exception):
    """Señal interna para terminar entre operaciones, sin cortar una ficha."""


class MigracionApp:
    COLORES = {
        'fondo': FONDO,
        'superficie': SUPERFICIE,
        'texto': TEXTO,
        'texto_secundario': TEXTO_SECUNDARIO,
        'borde': BORDE,
        'guinda': PRIMARIO,
        'guinda_hover': PRIMARIO_HOVER,
        'guinda_suave': PRIMARIO_SUAVE,
        'barra_lateral': BARRA_LATERAL,
        'barra_lateral_hover': BARRA_LATERAL_HOVER,
        'barra_lateral_activa': BARRA_LATERAL_ACTIVA,
        'barra_lateral_muted': BARRA_LATERAL_MUTADO,
        'verde': EXITO,
        'verde_suave': EXITO_SUAVE,
        'tierra': ADVERTENCIA,
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
        self.usuario_nombre = (
            self.auth_service.get_username(self.session_token)
            if self.auth_service else "Usuario"
        )
        
        self.root.title(
            f'NexoMARC | Migración Access a MARC21 (Koha) · '
            f'Perfil: {self.perfil_usuario}'
        )
        ancho = min(1480, self.root.winfo_screenwidth() - 48)
        alto = min(940, self.root.winfo_screenheight() - 72)
        self.root.geometry(f'{ancho}x{alto}')
        self.root.minsize(min(1040, ancho), min(680, alto))
        self.root.configure(background=self.COLORES['fondo'])

        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        self.config = self.cargar_config()

        self.access_reader: Optional[AccessReader] = None

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
        self._preparando_lote = False
        self._validando_access = False
        self._validando_mysql = False
        self._mysql_validado = False
        self._configuracion_confirmada = False
        self._detencion_solicitada = threading.Event()
        self.historial_lotes = historial_lotes if historial_lotes is not None else HistorialLotes()
        self._lote_actual_id = None
        self._lote_reprocesar_id = None
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

        encabezado = tk.Frame(
            distribucion, bg=NOCHE, padx=ESPACIO_L, pady=ESPACIO_S,
            highlightthickness=1, highlightbackground=NOCHE_BORDE,
        )
        encabezado.pack(fill='x')
        marca = tk.Frame(encabezado, bg=NOCHE)
        marca.pack(side='left')
        crear_icono(
            marca, 'database', color=TEXTO_INVERSO, size=22, fondo=NOCHE,
        ).pack(side='left', padx=(0, ESPACIO_S))
        identidad = tk.Frame(marca, bg=NOCHE)
        identidad.pack(side='left')
        tk.Label(
            identidad, text='NexoMARC', bg=NOCHE,
            fg=TEXTO_INVERSO, font=(FUENTE, 12, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            identidad, text='Migración de catálogos', bg=NOCHE,
            fg='#c2c9d8', font=(FUENTE, 8),
        ).pack(anchor='w', pady=(2, 0))

        cuenta = tk.Frame(encabezado, bg=NOCHE)
        cuenta.pack(side='right')
        ttk.Label(
            cuenta, text=self.usuario_nombre, style='HeroUser.TLabel',
        ).pack(side='left', padx=(0, ESPACIO_S))
        ttk.Label(
            cuenta, text=self.perfil_usuario, style='HeroRole.TLabel',
        ).pack(side='left', padx=(0, ESPACIO_M))
        ttk.Button(
            cuenta, text='↪  Salir', command=self._cerrar_sesion,
            style='Quiet.TButton',
        ).pack(side='left')

        self.nav_container = tk.Frame(
            distribucion, bg=NOCHE, padx=ESPACIO_L,
        )
        self.nav_container.pack(fill='x')

        self.page_container = ttk.Frame(distribucion, style='App.TFrame')
        self.page_container.pack(fill='both', expand=True)
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)

        self.frame_conexion = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_config = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_migracion = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_log = ttk.Frame(self.page_container, style='App.TFrame')
        self.frame_usuarios = ttk.Frame(self.page_container, style='App.TFrame')

        self.panel_lotes = PanelLotes(
            self.page_container, listar=lambda: self.historial_lotes.listar(resumen=True),
            obtener=self.historial_lotes.obtener, publicar=self._publicar_ui, politica=self._politica_lote,
            iniciar=self._iniciar_desde_panel, exportar=self._exportar_marcxml,
            revisar=self._obtener_registros_revision,
            proponer=self._proponer_correccion,
            listar_propuestas=self._listar_correcciones_pendientes,
            resolver_propuesta=self._resolver_correccion,
            listar_observaciones=self._listar_observaciones_revision,
            registrar_observacion=self._registrar_observacion_revision,
            conexiones=self._preparar_nueva_migracion,
            detener=self._solicitar_detencion,
            reprocesar=self._reprocesar_desde_panel,
        )
        self.paginas = (
            self.panel_lotes,
            self.frame_conexion,
            self.frame_config,
            self.frame_migracion,
            self.frame_log,
            self.frame_usuarios,
        )
        for pagina in self.paginas:
            pagina.grid(row=0, column=0, sticky='nsew')

        self._nav_items = {}
        self._nav_indicadores = {}
        self._nav_iconos = {}
        self._crear_boton_navegacion(self.nav_container, 'Inicio', self.panel_lotes)
        self._crear_boton_navegacion(self.nav_container, 'Conexión', self.frame_conexion)
        self._crear_boton_navegacion(self.nav_container, 'Configuración', self.frame_config)
        self._crear_boton_navegacion(self.nav_container, 'Migración', self.frame_migracion)
        self._crear_boton_navegacion(self.nav_container, 'Actividad', self.frame_log)
        if tiene_permiso(self.perfil_usuario, 'gestionar_usuarios'):
            self._crear_boton_navegacion(self.nav_container, 'Usuarios', self.frame_usuarios)

        self._crear_pestana_conexion()
        self._crear_pestana_migracion()
        self._crear_pestana_config()
        self._crear_pestana_log()
        self._crear_pestana_usuarios()
        for variable in (self.entry_host, self.entry_port, self.entry_user, self.entry_pass, self.entry_db):
            variable.trace_add('write', self._cambio_configuracion_mysql)
        self.pagina_actual = self.panel_lotes
        self.panel_lotes.tkraise()
        self._actualizar_navegacion_secuencial()

    def _crear_boton_navegacion(
        self, parent, texto, pantalla, icono=None, comando=None,
    ):
        elemento = tk.Frame(parent, bg=NOCHE)
        elemento.pack(side='left', padx=(0, ESPACIO_S))
        indicador = tk.Frame(elemento, height=2, bg=NOCHE)
        indicador.pack(side='bottom', fill='x')
        icono = icono or {
            'Inicio': 'home',
            'Conexión': 'connect',
            'Configuración': 'settings',
            'Migración': 'play',
            'Actividad': 'activity',
            'Usuarios': 'users',
        }.get(texto, 'file')
        simbolo = crear_icono(
            elemento, icono, color='#a8b0c2',
            size=16, fondo=NOCHE,
        )
        simbolo.pack(side='left', padx=(ESPACIO_S, 4), pady=ESPACIO_XS)
        boton = tk.Button(
            elemento, text=texto,
            command=comando or (lambda destino=pantalla: self._navegar(destino)),
            anchor='w', padx=5, pady=7, bd=0, relief='flat',
            cursor='hand2', font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'),
            bg=NOCHE, fg='#d2d7e2',
            activebackground=NOCHE_ALT,
            activeforeground=TEXTO_INVERSO, disabledforeground='#687287',
            highlightthickness=0,
        )
        boton.pack(side='left', padx=(0, ESPACIO_S))
        boton.bind(
            '<Enter>',
            lambda _evento: boton.configure(
                bg=NOCHE_ALT,
            ) if boton['state'] == 'normal' else None,
        )
        simbolo.bind(
            '<Enter>',
            lambda _evento: boton.configure(
                bg=NOCHE_ALT,
            ) if boton['state'] == 'normal' else None,
        )
        boton.bind(
            '<Leave>',
            lambda _evento, destino=pantalla: self._actualizar_navegacion_secuencial()
            if destino is not None and destino in self._nav_items else None,
        )
        simbolo.bind(
            '<Button-1>',
            lambda _evento: comando() if comando else boton.invoke(),
        )
        boton.bind(
            '<FocusIn>',
            lambda _evento: boton.configure(
                highlightthickness=1, highlightbackground=PRIMARIO,
            ),
        )
        boton.bind(
            '<FocusOut>',
            lambda _evento: boton.configure(highlightthickness=0),
        )
        if pantalla is not None:
            self._nav_indicadores[pantalla] = indicador
            self._nav_items[pantalla] = boton
            self._nav_iconos[pantalla] = simbolo

    def _estilos_interfaz(self):
        # Instala el sistema de diseno centralizado y devuelve el estilo para
        # referencias rapidas si fuera necesario.
        instalar_estilos(self.root)
        # Sobrescrituras puntuales de la app principal (mantienen compatibilidad
        # con nombres de estilo ya usados en el resto del codigo).
        estilo = ttk.Style(self.root)
        colores = self.COLORES
        estilo.configure('App.TFrame', background=FONDO)
        estilo.configure('Panel.TFrame', background=FONDO)
        estilo.configure('Tarjeta.TFrame', background=SUPERFICIE)
        estilo.configure('TLabel', background=FONDO, foreground=TEXTO)
        estilo.configure('Tarjeta.TLabel', background=SUPERFICIE, foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('CardBody.TLabel', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, TAM_CUERPO))
        estilo.configure('CardHint.TLabel', background=SUPERFICIE, foreground=TEXTO_MUTADO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('CardTitle.TLabel', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, TAM_TARJETA_TITULO, 'bold'))
        estilo.configure('CardMetric.TLabel', background=SUPERFICIE, foreground=PRIMARIO,
                         font=(FUENTE, 11, 'bold'))
        estilo.configure('Hero.TFrame', background=NOCHE)
        estilo.configure('HeroHint.TLabel', background=NOCHE, foreground='#c2c9d8',
                         font=(FUENTE, TAM_CAMPO_ETIQUETA))
        estilo.configure('HeroTitle.TLabel', background=NOCHE, foreground=TEXTO_INVERSO,
                         font=(FUENTE, 12, 'bold'))
        estilo.configure('HeroUser.TLabel', background=NOCHE, foreground=TEXTO_INVERSO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'))
        estilo.configure('HeroRole.TLabel', background=PRIMARIO_SUAVE, foreground=PRIMARIO,
                         padding=(8, 4), font=(FUENTE, 8, 'bold'))
        estilo.configure('HeroQuiet.TButton', background=NOCHE_ALT,
                         foreground=TEXTO_INVERSO, borderwidth=0, padding=(8, 6))
        estilo.map('HeroQuiet.TButton',
                   background=[('active', NOCHE_BORDE), ('pressed', NOCHE)])
        estilo.configure('Field.TLabel', background=SUPERFICIE, foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'))
        estilo.configure('AppTitle.TLabel', background=FONDO, foreground=TEXTO,
                         font=(FUENTE, TAM_TITULO_PAGINA, 'bold'))
        estilo.configure('PageTitle.TLabel', background=FONDO, foreground=TEXTO,
                         font=(FUENTE, TAM_TITULO_PAGINA, 'bold'))
        estilo.configure('PageSubtitle.TLabel', background=FONDO, foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_SUBTITULO_PAGINA))
        estilo.configure('TEntry', fieldbackground=SUPERFICIE, foreground=TEXTO,
                         bordercolor=BORDE, lightcolor=BORDE_ENFOQUE, darkcolor=BORDE_ENFOQUE,
                         padding=(9, 7), font=(FUENTE, TAM_CAMPO_ENTRADA))
        estilo.map('TEntry', bordercolor=[('focus', BORDE_ENFOQUE), ('!focus', BORDE)])
        estilo.configure('TButton', font=(FUENTE, TAM_BOTON, 'bold'), padding=(10, 7),
                         background=SUPERFICIE_ALT, foreground=TEXTO, borderwidth=0)
        estilo.map('TButton',
                   background=[('active', SUPERFICIE), ('disabled', '#f1eeec')],
                   foreground=[('disabled', TEXTO_MUTADO)])
        estilo.configure('Primary.TButton', background=PRIMARIO, foreground=TEXTO_INVERSO,
                         borderwidth=0)
        estilo.map('Primary.TButton',
                   background=[('active', PRIMARIO_HOVER), ('pressed', PRIMARIO_ACTIVO),
                               ('disabled', PRIMARIO_SUAVE)],
                   foreground=[('disabled', TEXTO_MUTADO)])
        estilo.configure('Secondary.TButton', background=PRIMARIO_SUAVE, foreground=PRIMARIO,
                         borderwidth=0)
        estilo.map('Secondary.TButton',
                   background=[('active', SUPERFICIE_ALT), ('pressed', PRIMARIO_SUAVE)],
                   foreground=[('active', PRIMARIO), ('pressed', PRIMARIO)])
        estilo.configure('Quiet.TButton', background=FONDO, foreground=TEXTO_SECUNDARIO,
                         borderwidth=0, padding=(8, 6))
        estilo.map('Quiet.TButton', foreground=[('active', PRIMARIO)])
        estilo.configure('Peligro.TButton', background=ERROR, foreground=TEXTO_INVERSO,
                         bordercolor=ERROR)
        estilo.map('Peligro.TButton',
                   background=[('active', '#b55a3c'), ('pressed', '#8c5338')],
                   foreground=[('disabled', TEXTO_MUTADO)])
        estilo.configure('TSeparator', background=BORDE)
        estilo.configure('Horizontal.TProgressbar', troughcolor=BORDE, background=PRIMARIO,
                         thickness=10, borderwidth=0)
        estilo.configure('TCheckbutton', background=FONDO, foreground=TEXTO,
                         font=(FUENTE, TAM_CUERPO))
        estilo.configure('TLabelframe', background=SUPERFICIE, bordercolor=BORDE,
                         relief='flat', borderwidth=0)
        estilo.configure('TLabelframe.Label', background=SUPERFICIE, foreground=TEXTO,
                         font=(FUENTE, TAM_CAMPO_ETIQUETA, 'bold'))
        estilo.configure('TNotebook', background=FONDO, borderwidth=0)
        estilo.configure('TNotebook.Tab', background=SUPERFICIE_ALT, foreground=TEXTO_SECUNDARIO,
                         font=(FUENTE, TAM_BOTON, 'bold'), padding=(12, 7), borderwidth=0)
        estilo.map('TNotebook.Tab',
                   background=[('selected', SUPERFICIE), ('active', SUPERFICIE)],
                   foreground=[('selected', TEXTO), ('active', TEXTO)])
        estilo.configure('Lotes.Treeview', background=SUPERFICIE, fieldbackground=SUPERFICIE,
                         foreground=TEXTO, rowheight=32, font=(FUENTE, TAM_TABLA_CUERPO),
                         bordercolor=BORDE, lightcolor=BORDE, darkcolor=BORDE)
        estilo.configure('Lotes.Treeview.Heading', background=SUPERFICIE_ALT,
                         foreground=TEXTO_SECUNDARIO, font=(FUENTE, TAM_TABLA_ENCABEZADO, 'bold'),
                         padding=(10, 7), borderwidth=0)
        estilo.map('Lotes.Treeview',
                   background=[('selected', PRIMARIO_SUAVE)],
                   foreground=[('selected', PRIMARIO)])
        estilo.configure('Lotes.Horizontal.TProgressbar', background=PRIMARIO,
                         troughcolor=BORDE, thickness=8)
        estilo.configure('Estado.TLabel', background=SUPERFICIE, foreground=PRIMARIO,
                         font=(FUENTE, 9, 'bold'))
        # COLORES se conserva por compatibilidad con el resto de la clase.
        self.COLORES = {
            'fondo': FONDO,
            'superficie': SUPERFICIE,
            'texto': TEXTO,
            'texto_secundario': TEXTO_SECUNDARIO,
            'borde': BORDE,
            'guinda': PRIMARIO,
            'guinda_hover': PRIMARIO_HOVER,
            'guinda_suave': PRIMARIO_SUAVE,
            'barra_lateral': BARRA_LATERAL,
            'barra_lateral_hover': BARRA_LATERAL_HOVER,
            'barra_lateral_activa': BARRA_LATERAL_ACTIVA,
            'barra_lateral_muted': BARRA_LATERAL_MUTADO,
            'verde': EXITO,
            'verde_suave': EXITO_SUAVE,
            'tierra': ADVERTENCIA,
        }
    def _navegar(self, pantalla):
        if not self._pagina_autorizada(pantalla):
            messagebox.showerror(
                'Acceso restringido',
                'Tu perfil no tiene permiso para abrir esta sección.',
            )
            return
        self.pagina_actual = pantalla
        pantalla.tkraise()
        self._actualizar_navegacion_secuencial()

    def _pagina_autorizada(self, pantalla):
        if pantalla is self.panel_lotes:
            return self.perfil_usuario in (
                'Ejecucion', 'Revision', 'Aprobacion', 'Administracion',
            )
        permiso_por_pagina = {
            self.frame_conexion: 'validar_access',
            self.frame_config: 'editar_configuracion',
            self.frame_migracion: 'iniciar_conversion',
            self.frame_log: 'ver_actividad',
            self.frame_usuarios: 'gestionar_usuarios',
        }
        permiso = permiso_por_pagina.get(pantalla)
        return permiso is not None and tiene_permiso(self.perfil_usuario, permiso)

    def _requiere_permiso(self, operacion):
        if not self._sesion_valida():
            return False
        try:
            requerir_permiso(self.perfil_usuario, operacion)
            return True
        except AccesoDenegado as error:
            messagebox.showerror('Acceso restringido', str(error))
            self.log(f'[BLOQUEO SEGURIDAD] {error}')
            return False

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
            self.panel_lotes: self._pagina_autorizada(self.panel_lotes),
            self.frame_conexion: (
                self._pagina_autorizada(self.frame_conexion)
                and not self.migracion_en_curso
            ),
            self.frame_config: (
                self._pagina_autorizada(self.frame_config)
                and conexiones_listas and not self.migracion_en_curso
            ),
            self.frame_migracion: (
                self._pagina_autorizada(self.frame_migracion)
                and conexiones_listas and configuracion_lista
            ),
            self.frame_log: self._pagina_autorizada(self.frame_log),
            self.frame_usuarios: self._pagina_autorizada(self.frame_usuarios),
        }
        if not disponible.get(actual, False):
            actual = self.panel_lotes
            if self._pagina_autorizada(self.frame_conexion):
                actual = (
                    self.frame_config
                    if conexiones_listas and not configuracion_lista
                    else self.frame_conexion
                )
            self.pagina_actual = actual
            actual.tkraise()

        for pantalla, boton in self._nav_items.items():
            seleccionada = pantalla == actual
            habilitado = disponible.get(pantalla, False)
            fondo = NOCHE
            color = (
                TEXTO_INVERSO if seleccionada else
                '#d2d7e2' if habilitado else '#687287'
            )
            boton.configure(
                state='normal' if habilitado else 'disabled',
                bg=fondo,
                fg=color,
                font=(FUENTE, TAM_CUERPO, 'bold' if seleccionada else 'normal'),
            )
            boton.master.configure(background=fondo)
            self._nav_indicadores[pantalla].configure(
                bg=PRIMARIO_HOVER if seleccionada else NOCHE,
            )
            colorear_icono(self._nav_iconos[pantalla], color, fondo)
        if hasattr(self, 'btn_siguiente_config'):
            self.btn_siguiente_config.configure(
                state='normal' if conexiones_listas and not self.migracion_en_curso else 'disabled',
            )
        if hasattr(self, 'btn_siguiente_migracion'):
            self.btn_siguiente_migracion.configure(
                state='normal' if conexiones_listas and not self.migracion_en_curso else 'disabled',
            )

    def _continuar_a_configuracion(self):
        if not self._requiere_permiso('editar_configuracion'):
            return
        if not self._validacion_access or not self._mysql_validado:
            messagebox.showwarning(
                'Completa la conexión',
                'Valida primero el archivo Access y la conexión MySQL para continuar.',
            )
            return
        self._navegar(self.frame_config)

    def _continuar_a_migracion(self):
        if not self._requiere_permiso('iniciar_conversion'):
            return
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

    def _encabezado_pagina(self, parent, titulo, descripcion, icono='file'):
        return encabezado_pagina(
            parent, titulo, descripcion, icono=icono,
        )

    def _crear_pestana_conexion(self):
        f = self.frame_conexion
        f.configure(padding=(ESPACIO_L, ESPACIO_M, ESPACIO_L, ESPACIO_XL))
        self._encabezado_pagina(
            f, 'Conecta tus datos',
            'Selecciona el respaldo de Access y valida el destino MySQL antes de continuar.',
            icono='connect',
        )
        tarjetas = ttk.Frame(f, style='App.TFrame')
        tarjetas.pack(fill='both', expand=True)
        tarjetas.columnconfigure(0, weight=1, uniform='conexion')
        tarjetas.columnconfigure(1, weight=1, uniform='conexion')

        lbl_access = seccion_tarjeta(tarjetas, '01 · ORIGEN ACCESS')
        lbl_access.grid(row=0, column=0, sticky='nsew', padx=(0, ESPACIO_S))
        lbl_access.columnconfigure(0, weight=1)

        self.var_access_path = tk.StringVar(value=self.config.get('access', {}).get('path', ''))
        self.var_access_path.trace_add('write', lambda *_: self._actualizar_info_access())
        fila_archivo = ttk.Frame(lbl_access, style='Tarjeta.TFrame')
        fila_archivo.pack(fill='x', pady=(ESPACIO_S, ESPACIO_M))
        fila_archivo.columnconfigure(0, weight=1)
        ttk.Entry(fila_archivo, textvariable=self.var_access_path).grid(
            row=0, column=0, sticky='ew', padx=(0, ESPACIO_S)
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
        ).pack(anchor='w', pady=(0, ESPACIO_M))
        self.lbl_info_access = ttk.Label(
            lbl_access, text='Archivo seleccionado: --', anchor='w',
            style='CardBody.TLabel', wraplength=430,
        )
        self.lbl_info_access.pack(fill='x', pady=(0, ESPACIO_M))
        self.lbl_conteo_access = ttk.Label(
            lbl_access, text='Registros FICHAS: pendientes de validar',
            style='CardMetric.TLabel',
        )
        self.lbl_conteo_access.pack(anchor='w', pady=(0, ESPACIO_M))
        ttk.Button(
            lbl_access, text='Validar conexión Access', style='Primary.TButton',
            command=self._probar_access,
        ).pack(anchor='w', pady=(0, ESPACIO_S))
        self._actualizar_info_access()

        lbl_mysql = seccion_tarjeta(tarjetas, '02 · DESTINO MYSQL')
        lbl_mysql.grid(row=0, column=1, sticky='nsew', padx=(ESPACIO_S, 0))
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
        ).grid(row=3, column=0, columnspan=4, sticky='w', padx=4, pady=(ESPACIO_S, ESPACIO_M))
        ttk.Button(
            lbl_mysql, text='Validar conexión MySQL', style='Secondary.TButton',
            command=self._probar_mysql,
        ).grid(row=4, column=0, sticky='w', padx=4)
        self.lbl_conteo_mysql = ttk.Label(
            lbl_mysql, text='Destino pendiente de validar', style='CardMetric.TLabel',
        )
        self.lbl_conteo_mysql.grid(row=4, column=1, columnspan=3, sticky='w', padx=10)

        acciones = ttk.Frame(f, style='App.TFrame')
        acciones.pack(fill='x', pady=(ESPACIO_M, 0))
        self.btn_siguiente_config = ttk.Button(
            acciones, text='Siguiente: configuración  →', style='Primary.TButton',
            command=self._continuar_a_configuracion, state='disabled',
        )
        self.btn_siguiente_config.pack(anchor='e')

    def _crear_pestana_migracion(self):
        f = self.frame_migracion
        f.configure(padding=(ESPACIO_L, ESPACIO_M, ESPACIO_L, ESPACIO_XL))
        self._encabezado_pagina(
            f, 'Ejecuta la migración',
            'El proceso conserva avances por lote. Los valores no contemplados se registran como incidencias; no se infieren correspondencias.',
            icono='play',
        )

        lbl_opts = seccion_tarjeta(f, 'ALCANCE DEL PROCESO')
        lbl_opts.pack(fill='x', pady=(0, ESPACIO_M))

        self.var_limite = tk.StringVar(value='0')
        ttk.Label(
            lbl_opts, text='Cantidad de fichas', style='Field.TLabel',
        ).pack(side='left', padx=(ESPACIO_XS, ESPACIO_S))
        ttk.Entry(lbl_opts, textvariable=self.var_limite, width=12).pack(side='left', padx=(0, ESPACIO_S))
        ttk.Label(
            lbl_opts, text='0 = procesar todas las fichas del respaldo',
            style='CardHint.TLabel',
        ).pack(side='left', padx=(0, ESPACIO_L))

        self.var_saltar_existentes = tk.BooleanVar(value=True)
        ttk.Checkbutton(lbl_opts, text='Saltar registros ya migrados',
                        variable=self.var_saltar_existentes).pack(side='left')

        lbl_prog = seccion_tarjeta(f, 'ESTADO DE LA EJECUCIÓN')
        lbl_prog.pack(fill='both', expand=True)
        lbl_prog.columnconfigure(0, weight=1)
        ttk.Label(
            lbl_prog, text='Conversión Access → MARC21 → MySQL',
            style='CardTitle.TLabel',
        ).grid(row=0, column=0, sticky='w', pady=(0, ESPACIO_XS))
        ttk.Label(
            lbl_prog, text='Puedes detener el proceso de forma segura; se conservarán las fichas ya guardadas.',
            style='CardHint.TLabel',
        ).grid(row=1, column=0, sticky='w', pady=(0, ESPACIO_M))

        self.progress = ttk.Progressbar(lbl_prog, orient='horizontal', mode='determinate')
        self.progress.grid(row=2, column=0, sticky='ew', pady=(0, ESPACIO_M))

        self.lbl_estado = ttk.Label(lbl_prog, text='Listo para iniciar.', style='CardMetric.TLabel')
        self.lbl_estado.grid(row=3, column=0, sticky='w', pady=(0, ESPACIO_S))

        self.lbl_stats = ttk.Label(lbl_prog, text='Correctos: 0  ·  Omitidos: 0  ·  Errores: 0')
        self.lbl_stats.grid(row=4, column=0, sticky='w')
        btn_frame = ttk.Frame(lbl_prog, style='App.TFrame')
        btn_frame.grid(row=5, column=0, sticky='ew', pady=(ESPACIO_L, 0))
        self.btn_ejecutar = ttk.Button(
            btn_frame, text='Iniciar migración', style='Primary.TButton',
            command=self._iniciar_migracion,
        )
        self.btn_ejecutar.pack(side='left', padx=(0, ESPACIO_S))
        self.btn_detener = ttk.Button(
            btn_frame, text='Detener con seguridad', style='Secondary.TButton',
            command=self._solicitar_detencion, state='disabled',
        )
        self.btn_detener.pack(side='left', padx=(0, ESPACIO_S))
        self.btn_exportar = ttk.Button(
            btn_frame, text='Exportar MARCXML', style='Secondary.TButton',
            command=self._exportar_marcxml,
        )
        self.btn_exportar.pack(side='left')

    def _crear_pestana_config(self):
        f = self.frame_config
        f.configure(padding=(ESPACIO_L, ESPACIO_M, ESPACIO_L, ESPACIO_XL))
        self._encabezado_pagina(
            f, 'Revisa la configuración',
            'Define equivalencias explícitas para Koha. Si un valor no tiene regla autorizada, se omitirá y quedará señalado en las incidencias.',
            icono='settings',
        )
        tarjetas = ttk.Frame(f, style='App.TFrame')
        tarjetas.pack(fill='both', expand=True)
        tarjetas.columnconfigure(0, weight=1, uniform='mapeos')
        tarjetas.columnconfigure(1, weight=1, uniform='mapeos')

        lbl_map = seccion_tarjeta(tarjetas, 'SUCURSALES · ACCESS → KOHA')
        lbl_map.grid(row=0, column=0, sticky='nsew', padx=(0, ESPACIO_S))
        lbl_map.columnconfigure(0, weight=1)
        ttk.Label(
            lbl_map, text='Código de biblioteca a código de sucursal.',
            style='CardHint.TLabel',
        ).pack(anchor='w', pady=(0, ESPACIO_M))
        txt_frame = ttk.Frame(lbl_map, style='Tarjeta.TFrame')
        txt_frame.pack(fill='both', expand=True)
        self.txt_mapeo = tk.Text(
            txt_frame, width=42, height=8, wrap='none',
            font=(FUENTE_MONO, 10), bg='#fbfaf9', fg=TEXTO,
            insertbackground=PRIMARIO, relief='flat',
            padx=10, pady=ESPACIO_M, highlightthickness=1,
            highlightbackground=BORDE,
        )
        self.txt_mapeo.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(txt_frame, command=self.txt_mapeo.yview)
        scroll.pack(side='right', fill='y')
        self.txt_mapeo.configure(yscrollcommand=scroll.set)

        ejemplo = json.dumps(self.config.get('koha_branch_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_mapeo.insert('1.0', ejemplo)
        self.txt_mapeo.edit_modified(False)
        self.txt_mapeo.bind('<<Modified>>', self._texto_mapeo_modificado)

        lbl_status = seccion_tarjeta(tarjetas, 'ESTADO · ACCESS → KOHA')
        lbl_status.grid(row=0, column=1, sticky='nsew', padx=(ESPACIO_S, 0))
        lbl_status.columnconfigure(0, weight=1)
        ttk.Label(
            lbl_status, text='Valores del campo Accesible a estado de ejemplar.',
            style='CardHint.TLabel',
        ).pack(anchor='w', pady=(0, ESPACIO_M))
        status_frame = ttk.Frame(lbl_status, style='Tarjeta.TFrame')
        status_frame.pack(fill='both', expand=True)
        self.txt_status = tk.Text(
            status_frame, width=42, height=8, wrap='none',
            font=(FUENTE_MONO, 10), bg='#fbfaf9', fg=TEXTO,
            insertbackground=PRIMARIO, relief='flat',
            padx=10, pady=ESPACIO_M, highlightthickness=1,
            highlightbackground=BORDE,
        )
        self.txt_status.pack(side='left', fill='both', expand=True)
        scroll_status = ttk.Scrollbar(status_frame, command=self.txt_status.yview)
        scroll_status.pack(side='right', fill='y')
        self.txt_status.configure(yscrollcommand=scroll_status.set)
        ejemplo_status = json.dumps(self.config.get('item_status_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_status.insert('1.0', ejemplo_status)
        self.txt_status.edit_modified(False)
        self.txt_status.bind('<<Modified>>', self._texto_mapeo_modificado)

        lbl_tipos = seccion_tarjeta(f, 'VALORES PREDETERMINADOS DE KOHA')
        lbl_tipos.pack(fill='x', pady=(ESPACIO_L, ESPACIO_M))

        grid_tipos = ttk.Frame(lbl_tipos, style='Tarjeta.TFrame')
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
        acciones.pack(fill='x', pady=(ESPACIO_M, 0))
        ttk.Button(
            acciones, text='← Volver a conexiones', style='Quiet.TButton',
            command=lambda: self._navegar(self.frame_conexion),
        ).pack(side='left')
        ttk.Button(
            acciones, text='Guardar configuración', style='Secondary.TButton',
            command=self._guardar_config,
        ).pack(side='right', padx=(ESPACIO_S, 0))
        self.btn_siguiente_migracion = ttk.Button(
            acciones, text='Continuar a migración  →', style='Primary.TButton',
            command=self._continuar_a_migracion, state='disabled',
        )
        self.btn_siguiente_migracion.pack(side='right')

    def _crear_pestana_log(self):
        f = self.frame_log
        f.configure(padding=(ESPACIO_L, ESPACIO_M, ESPACIO_L, ESPACIO_XL))
        self._encabezado_pagina(
            f, 'Actividad del sistema',
            'Mensajes de validación, avance e incidencias registrados durante la sesión.',
            icono='activity',
        )
        contenedor = tarjeta(f, padding=(ESPACIO_M, ESPACIO_M))
        contenedor.pack(fill='both', expand=True)
        contenedor.columnconfigure(0, weight=1)
        contenedor.rowconfigure(0, weight=1)
        self.txt_log = tk.Text(
            contenedor, wrap='word', width=100, height=25,
            font=(FUENTE_MONO, 9), bg='#fbfaf9', fg=TEXTO,
            insertbackground=PRIMARIO, relief='flat',
            padx=12, pady=ESPACIO_M,
        )
        self.txt_log.grid(row=0, column=0, sticky='nsew')
        scroll_log = ttk.Scrollbar(contenedor, command=self.txt_log.yview)
        scroll_log.grid(row=0, column=1, sticky='ns')
        self.txt_log.configure(yscrollcommand=scroll_log.set)
        ttk.Button(
            f, text='Limpiar actividad', style='Quiet.TButton',
            command=lambda: self.txt_log.delete('1.0', tk.END),
        ).pack(anchor='e', pady=(ESPACIO_M, 0))

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
        if not self._requiere_permiso('editar_configuracion'):
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
        politica['revision'] = bool(
            politica['revision']
            and tiene_permiso(self.perfil_usuario, 'revision_muestra')
        )
        politica['nueva_migracion'] = not self.migracion_en_curso and tiene_permiso(
            self.perfil_usuario, 'iniciar_nueva_migracion',
        )
        politica['incidencias'] = bool(
            politica['incidencias']
            and tiene_permiso(self.perfil_usuario, 'ver_incidencias')
        )
        politica['proponer_correccion'] = bool(
            politica['revision']
            and tiene_permiso(self.perfil_usuario, 'proponer_correccion')
        )
        politica['aprobar_correccion'] = bool(
            politica['revision']
            and tiene_permiso(self.perfil_usuario, 'aprobar_correccion')
        )
        politica['registrar_observacion'] = bool(
            politica['revision']
            and tiene_permiso(self.perfil_usuario, 'registrar_observacion')
        )
        politica['reprocesar'] = bool(
            politica.get('reprocesar')
            and tiene_permiso(self.perfil_usuario, 'reprocesar_lote')
        )
        politica['exportar'] = bool(
            politica['exportar']
            and tiene_permiso(self.perfil_usuario, 'aprobar_exportacion')
        )
        politica['exportar_historial'] = tiene_permiso(
            self.perfil_usuario, 'exportar_historial',
        )
        politica['iniciar'] = bool(
            politica['iniciar']
            and tiene_permiso(self.perfil_usuario, 'iniciar_conversion')
        )
        politica['detener'] = bool(
            politica['detener']
            and tiene_permiso(self.perfil_usuario, 'detener_conversion')
        )
        if self.historial_lotes.solo_lectura:
            politica['iniciar'] = False
        return politica

    def _actualizar_panel(self):
        if not hasattr(self, 'panel_lotes') or not hasattr(self, 'btn_exportar'):
            return
        self.panel_lotes.actualizar()
        lote = self.historial_lotes.obtener(self._lote_actual_id, resumen=True)
        self.btn_exportar.configure(state='normal' if self._politica_lote(lote)['exportar'] else 'disabled')
        self.btn_ejecutar.configure(
            state='normal' if (
                tiene_permiso(self.perfil_usuario, 'iniciar_conversion')
                and not self.migracion_en_curso
                and not self.historial_lotes.solo_lectura
            ) else 'disabled',
        )
        politica = self._politica_lote(lote)
        preparando = self._preparando_lote and tiene_permiso(self.perfil_usuario, 'detener_conversion')
        deteniendo = preparando and self._detencion_solicitada.is_set()
        self.btn_detener.configure(
            state='normal' if politica['detener'] or (preparando and not deteniendo) else 'disabled',
            text='Deteniendo…' if politica['detencion_solicitada'] or deteniendo else 'Detener migración',
        )
        self._actualizar_navegacion_secuencial()

    def _solicitar_detencion(self, identificador=None):
        if not self._requiere_permiso('detener_conversion'):
            return
        if self._preparando_lote and identificador is None:
            self._detencion_solicitada.set()
            self.lbl_estado.configure(text='Deteniendo la preparación…')
            self._actualizar_panel()
            return
        identificador = identificador or self._lote_actual_id
        lote = self.historial_lotes.obtener(identificador, resumen=True)
        if not self._politica_lote(lote)['detener']:
            return
        self._detencion_solicitada.set()
        self.log(f'Lote {identificador}: detención solicitada por el usuario.')
        self.lbl_estado.configure(text='Detención solicitada. Terminando la ficha u operación en curso…')
        self._actualizar_panel()

    def _iniciar_desde_panel(self, identificador):
        lote = self.historial_lotes.obtener(identificador, resumen=True)
        if not self._politica_lote(lote)['iniciar']:
            messagebox.showwarning('Acción no disponible', 'Valida el respaldo seleccionado antes de iniciar ese lote.')
            return
        self._lote_actual_id = identificador
        self._iniciar_migracion()

    def _preparar_nueva_migracion(self):
        self._lote_reprocesar_id = None
        self._navegar(self.frame_conexion)

    def _reprocesar_desde_panel(self, identificador):
        if not self._requiere_permiso('reprocesar_lote'):
            return
        lote = self.historial_lotes.obtener(identificador, resumen=True)
        if not self._politica_lote(lote).get('reprocesar'):
            messagebox.showwarning(
                'Reprocesamiento no disponible',
                'Solo se pueden reprocesar lotes finalizados, detenidos o con incidencias.',
            )
            return
        if not lote.destino:
            messagebox.showerror(
                'Destino no registrado',
                'El lote no tiene un destino MySQL guardado y no se puede reprocesar con seguridad.',
            )
            return
        if not os.path.isfile(lote.fuente):
            messagebox.showerror(
                'Respaldo no disponible',
                'No se encontró el archivo Access usado por este lote. Selecciona o restaura el respaldo original.',
            )
            return
        if not messagebox.askyesno(
            'Reprocesar lote',
            f'Se creará un nuevo intento a partir de {identificador}. '
            'Los registros MARC existentes no se reemplazarán; se volverán '
            'a revisar las fichas y se completarán los registros o ejemplares faltantes. '
            'Deberás validar Access y MySQL antes de iniciar. ¿Continuar?',
        ):
            return

        self._lote_reprocesar_id = lote.id
        self.var_access_path.set(lote.fuente)
        self.var_limite.set(
            str(lote.total_objetivo)
            if lote.total_objetivo < lote.total_recibidos else '0'
        )
        self.var_saltar_existentes.set(True)
        self.entry_host.set(lote.destino['host'])
        self.entry_port.set(str(lote.destino['port']))
        self.entry_db.set(lote.destino['database'])
        self._validacion_access = None
        self._mysql_validado = False
        self._configuracion_confirmada = False
        self._actualizar_info_access()
        self._navegar(self.frame_conexion)

    def cerrar(self):
        if self.migracion_en_curso:
            messagebox.showwarning('Migración en curso', 'Pulsa Detener migración y espera a que termine la operación en curso antes de cerrar.')
            return
        self._cerrando = True
        self.root.after_cancel(self._after_ui)
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
        if self.migracion_en_curso:
            self.cerrar()
            return
        if self.auth_service is not None:
            self.auth_service.logout(self.session_token)
        if self.on_logout is not None:
            self.on_logout()
        else:
            self.cerrar()

    def _crear_pestana_usuarios(self):
        f = self.frame_usuarios
        f.configure(padding=(ESPACIO_L, ESPACIO_M, ESPACIO_L, ESPACIO_XL))
        self._encabezado_pagina(
            f, 'Gestión de usuarios',
            'Crea cuentas y asigna el perfil necesario para cada tarea.',
            icono='users',
        )
        tarjeta_formulario = tarjeta(f, padding=(ESPACIO_L, ESPACIO_L))
        tarjeta_formulario.pack(fill='x', anchor='n')
        formulario = ttk.Frame(
            tarjeta_formulario, style='Tarjeta.TFrame',
        )
        formulario.pack(fill='x')
        formulario.columnconfigure(0, weight=1)
        ttk.Label(
            formulario, text='Nueva cuenta', style='CardTitle.TLabel',
        ).grid(row=0, column=0, sticky='w', pady=(0, ESPACIO_M))

        ttk.Label(
            formulario, text='Nombre de usuario', style='Field.TLabel',
        ).grid(
            row=1, column=0, sticky='w', pady=(0, ESPACIO_XS),
        )
        entrada_usuario = ttk.Entry(formulario)
        entrada_usuario.grid(row=2, column=0, sticky='ew', pady=(0, ESPACIO_M))

        ttk.Label(
            formulario, text='Contraseña', style='Field.TLabel',
        ).grid(
            row=3, column=0, sticky='w', pady=(0, ESPACIO_XS),
        )
        entrada_contrasena = ttk.Entry(formulario, show='*')
        entrada_contrasena.grid(row=4, column=0, sticky='ew', pady=(0, ESPACIO_M))

        ttk.Label(
            formulario, text='Confirmar contraseña', style='Field.TLabel',
        ).grid(
            row=5, column=0, sticky='w', pady=(0, ESPACIO_XS),
        )
        entrada_confirmacion = ttk.Entry(formulario, show='*')
        entrada_confirmacion.grid(row=6, column=0, sticky='ew', pady=(0, ESPACIO_M))

        mostrar_contrasena = tk.BooleanVar(value=False)

        def alternar_visibilidad():
            mascara = '' if mostrar_contrasena.get() else '*'
            entrada_contrasena.configure(show=mascara)
            entrada_confirmacion.configure(show=mascara)

        ttk.Checkbutton(
            formulario, text='Mostrar contraseñas',
            variable=mostrar_contrasena, command=alternar_visibilidad,
        ).grid(row=7, column=0, sticky='w', pady=(0, ESPACIO_M))

        ttk.Separator(formulario).grid(row=8, column=0, sticky='ew', pady=(0, ESPACIO_M))
        ttk.Label(
            formulario, text='Perfil de acceso', style='Field.TLabel',
        ).grid(row=9, column=0, sticky='w', pady=(0, ESPACIO_XS))
        combo_perfil = ttk.Combobox(
            formulario,
            values=('Ejecucion', 'Revision', 'Aprobacion', 'Administracion'),
            state='readonly',
        )
        combo_perfil.current(0)
        combo_perfil.grid(row=10, column=0, sticky='ew')
        descripcion_perfil = ttk.Label(
            formulario, style='CardHint.TLabel', wraplength=450,
        )
        descripcion_perfil.grid(row=11, column=0, sticky='w', pady=(7, 0))
        self.lbl_usuario_estado = ttk.Label(
            formulario, text='', style='CardHint.TLabel',
        )
        self.lbl_usuario_estado.grid(row=12, column=0, sticky='w', pady=(ESPACIO_M, 0))
        descripciones = {
            'Ejecucion': 'Puede validar los orígenes, ejecutar y reprocesar migraciones, '
                         'consultar incidencias y descargar reportes.',
            'Revision': 'Puede consultar registros, registrar observaciones y proponer '
                        'correcciones. No puede ejecutar ni reprocesar migraciones.',
            'Aprobacion': 'Puede ejecutar, revisar, aprobar correcciones, exportar '
                          'registros y gestionar el flujo completo de migración.',
            'Administracion': 'Tiene los mismos permisos operativos que Aprobación y, '
                              'además, puede crear usuarios.',
        }

        def mostrar_descripcion_perfil(_evento=None):
            perfil = combo_perfil.get()
            descripcion_perfil.config(text=descripciones.get(perfil, ''))

        combo_perfil.bind('<<ComboboxSelected>>', mostrar_descripcion_perfil)
        mostrar_descripcion_perfil()

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
                messagebox.showerror('Registro rechazado', 'Ese usuario ya existe.', parent=self.root)
                entrada_usuario.focus_set()
                return
            except (PermissionError, ValueError) as error:
                messagebox.showerror('Registro rechazado', str(error), parent=self.root)
                return
            entrada_usuario.delete(0, tk.END)
            entrada_contrasena.delete(0, tk.END)
            entrada_confirmacion.delete(0, tk.END)
            mostrar_contrasena.set(False)
            alternar_visibilidad()
            self.lbl_usuario_estado.configure(
                text=f'Cuenta creada: {usuario} · perfil {perfil}.',
                foreground=EXITO,
            )
            self.log(f'[OK] Usuario {usuario} creado con perfil {perfil}.')

        acciones = ttk.Frame(tarjeta_formulario, style='Tarjeta.TFrame')
        acciones.pack(fill='x', pady=(ESPACIO_L, 0))
        ttk.Button(
            acciones, text='Limpiar', style='Quiet.TButton',
            command=lambda: (
                entrada_usuario.delete(0, tk.END),
                entrada_contrasena.delete(0, tk.END),
                entrada_confirmacion.delete(0, tk.END),
                self.lbl_usuario_estado.configure(text=''),
            ),
        ).pack(side='right', padx=(0, ESPACIO_S))
        ttk.Button(
            acciones, text='Crear usuario', style='Primary.TButton',
            command=registrar,
        ).pack(side='right')
        entrada_usuario.bind('<Return>', lambda _evento: entrada_contrasena.focus_set())
        entrada_contrasena.bind('<Return>', lambda _evento: entrada_confirmacion.focus_set())
        entrada_confirmacion.bind('<Return>', lambda _evento: registrar())
        self.entry_nuevo_usuario = entrada_usuario

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
        if self._validando_access:
            return
        self._validando_access = True
        self.lbl_conteo_access.config(text='Validando el respaldo de Access…')
        reproceso = self._lote_reprocesar_id
        try:
            threading.Thread(
                target=self._validar_access_en_segundo_plano,
                args=(path, reproceso), daemon=True,
            ).start()
        except RuntimeError as exc:
            self._terminar_validacion_access(path, None, 0, None, str(exc))

    def _leer_origen_validado(self, path):
        firma = self._firma_access(path)
        errores = self._validar_archivo_access(path)
        if errores:
            raise ValueError('\n'.join(errores))
        lector = AccessReader(path)
        try:
            total = lector.contar_fichas()
        finally:
            lector.close()
        if not firma or firma != self._firma_access(path):
            raise ValueError('El respaldo cambió durante la validación.')
        return firma, total

    def _origen_reproceso(self, identificador, firma, total):
        origen = self.historial_lotes.obtener(identificador, resumen=True)
        if (origen is None or os.path.normcase(os.path.abspath(origen.fuente)) != firma[0]
                or origen.total_recibidos != total):
            raise ValueError('El respaldo no coincide con el lote que se desea reprocesar.')
        return origen

    def _validar_access_en_segundo_plano(self, path, reproceso):
        try:
            firma, total = self._leer_origen_validado(path)
            if reproceso:
                lote = self._origen_reproceso(reproceso, firma, total)
            else:
                lote = self.historial_lotes.recibir(path, total, incremental=True)
            self._publicar_ui(self._terminar_validacion_access, path, firma, total, lote.id, None)
        except Exception as exc:
            self._publicar_ui(self._terminar_validacion_access, path, None, 0, None, str(exc))

    def _terminar_validacion_access(self, path, firma, total, identificador, error):
        self._validando_access = False
        if self.var_access_path.get().strip() != path:
            self._actualizar_info_access()
            return
        if error:
            self.lbl_conteo_access.config(text='El respaldo requiere revisión.')
            self.log('[ERROR] Access: ' + error)
            messagebox.showerror('No se pudo validar Access', error)
            return
        self._validacion_access = firma
        self._lote_actual_id = identificador
        self.panel_lotes.seleccionar_real(identificador)
        self.lbl_conteo_access.config(text=f'Registros FICHAS: {total:,}')
        self.log(f'[OK] Access validado. {total:,} fichas encontradas.')
        self._actualizar_panel()

    def _probar_mysql(self):
        if (not self._requiere_permiso('validar_mysql') or self._validando_mysql
                or self.migracion_en_curso):
            return
        destino = self._destino_actual()
        if not destino.get('host') or not destino.get('database') or not 1 <= destino['port'] <= 65535:
            messagebox.showerror('Destino no válido', 'Revisa el servidor, el puerto y la base MySQL.')
            return
        config = {**destino, 'user': self.entry_user.get(),
                  'password': self.entry_pass.get(), 'charset': 'utf8mb4'}
        self._mysql_validado = self._configuracion_confirmada = False
        self._iniciar_validacion_mysql(config)

    def _iniciar_validacion_mysql(self, config, crear=False):
        self._validando_mysql = True
        self.lbl_conteo_mysql.config(text='Validando el destino MySQL…')
        self._actualizar_panel()
        try:
            threading.Thread(
                target=self._validar_mysql_en_segundo_plano,
                args=(config, crear), daemon=True,
            ).start()
        except RuntimeError as exc:
            self._terminar_validacion_mysql(config, None, str(exc), False)

    def _validar_mysql_en_segundo_plano(self, config, crear):
        writer = MySQLWriter(config)
        try:
            if crear:
                writer.ensure_database()
            writer.connect()
            writer.crear_tablas()
            stats = writer.obtener_estadisticas()
            self._publicar_ui(self._terminar_validacion_mysql, config, stats, None, False)
        except Exception as exc:
            falta_base = not crear and bool(exc.args) and exc.args[0] == 1049
            mensaje = self._error_mysql_sin_secreto(exc, config['password'])
            self._publicar_ui(self._terminar_validacion_mysql, config, None, mensaje, falta_base)
        finally:
            writer.close()

    def _terminar_validacion_mysql(self, config, stats, mensaje, falta_base):
        self._validando_mysql = False
        destino = self._destino_actual()
        if (any(config.get(campo) != destino.get(campo) for campo in ('host', 'port', 'database'))
                or config['user'] != self.entry_user.get()
                or config['password'] != self.entry_pass.get()):
            self.lbl_conteo_mysql.config(text='Destino pendiente de validar')
            return
        if falta_base and messagebox.askyesno(
            'Base de datos no existe', f'¿Quieres crear la base de datos {config["database"]}?',
        ):
            self._iniciar_validacion_mysql(config, crear=True)
            return
        if mensaje:
            self.lbl_conteo_mysql.config(text='Destino pendiente de validar')
            self.log('[ERROR] MySQL: ' + mensaje)
            if not falta_base:
                messagebox.showerror('No se pudo validar MySQL', mensaje)
        else:
            self._mysql_validado = True
            self.lbl_conteo_mysql.config(text=f'Registros migrados: {stats["total_registros"]:,}')
            self.log('[OK] Destino MySQL validado. Tablas verificadas.')
        self._actualizar_panel()

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

        if self._validando_access or self._validando_mysql:
            messagebox.showinfo('Validación en curso', 'Espera a que termine la validación de la conexión.')
            return
        destino = self._destino_actual()
        if not destino.get('host') or not destino.get('database') or not 1 <= destino['port'] <= 65535:
            messagebox.showerror('Destino no válido', 'Revisa el servidor, el puerto y la base MySQL.')
            return
        limite_str = self.var_limite.get().strip()
        if not limite_str.isdecimal():
            messagebox.showerror('Límite no válido', 'Usa un entero no negativo. 0 procesa todo el respaldo.')
            return
        limite = int(limite_str)
        config_mysql = {
            **destino, 'user': self.entry_user.get(), 'password': self.entry_pass.get(),
            'charset': 'utf8mb4',
        }
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
        self.migracion_en_curso = self._preparando_lote = True
        self._lote_actual_id = None
        self._detencion_solicitada.clear()
        self.progress['value'] = 0
        self.lbl_estado.config(text='Validando el respaldo de Access…')
        self._actualizar_panel()
        self._navegar(self.frame_migracion)

        try:
            hilo = threading.Thread(
                target=self._preparar_y_ejecutar,
                args=(path_access, config_mysql, limite, saltar, branch_mapping, status_mapping,
                      self._lote_reprocesar_id, self._usuario_actual(), destino, huella_mapeo),
                daemon=True,
            )
            hilo.start()
        except RuntimeError as exc:
            self._fallo_preparacion(str(exc))

    def _preparar_y_ejecutar(self, path, config, limite, saltar, sucursales, estados,
                            reproceso, usuario, destino, huella):
        try:
            firma, total = self._leer_origen_validado(path)
            if self._detencion_solicitada.is_set():
                self._publicar_ui(self._fallo_preparacion, None)
                return
            if not total:
                raise ValueError('El respaldo no contiene fichas para migrar.')
            if reproceso:
                origen = self._origen_reproceso(reproceso, firma, total)
                if origen.destino != destino:
                    raise ValueError('El destino MySQL debe coincidir con el lote original.')
                lote = self.historial_lotes.recibir_reprocesamiento(reproceso, total, incremental=True)
                limite = lote.total_objetivo
                saltar = True
            else:
                lote = self.historial_lotes.recibir(path, total, incremental=True)
            objetivo = min(total, limite) if limite else total
            self.historial_lotes.actualizar(
                lote.id, estado='en_proceso', etapa='conexion', total_objetivo=objetivo,
                destino=destino, usuario=usuario, iniciado_en=ahora(), omitir_existentes=saltar,
                version_mapeo=self.marc_converter.mapping_version, huella_mapeo=huella,
                evento='Respaldo validado. Conectando al destino MySQL.',
            )
        except Exception as exc:
            self._publicar_ui(self._fallo_preparacion, self._error_mysql_sin_secreto(exc, config.get('password')))
            return
        self._publicar_ui(self._lote_preparado, lote.id, firma)
        self._ejecutar_migracion(path, config, objetivo, saltar, sucursales, estados, lote.id, firma=firma)

    def _lote_preparado(self, identificador, firma):
        self._preparando_lote = False
        self._validacion_access = firma
        self._lote_reprocesar_id = None
        self._lote_actual_id = identificador
        self.panel_lotes.seleccionar_real(identificador)
        self._mostrar_avance_lote(identificador)

    def _fallo_preparacion(self, mensaje):
        self._finalizar_migracion()
        if mensaje:
            self.lbl_estado.config(text='No se pudo preparar la migración.')
            self.log('[ERROR] Preparación: ' + mensaje)
            messagebox.showerror('No se pudo preparar el lote', mensaje)
        else:
            self.lbl_estado.config(text='Preparación detenida.')

    def _ejecutar_migracion(self, path_access, config_mysql, limite, saltar,
                            branch_mapping, status_mapping, lote_id, *, firma=None):
        reader = writer = bloques = None
        cont_ok = cont_err = cont_omitidos = cont_ejemplares = 0
        filas_nuevas = []
        incidencias = []
        ultimo_avance = monotonic()

        def guardar_avance(**extra):
            self.historial_lotes.actualizar(
                lote_id, filas=filas_nuevas, correctos=cont_ok, errores=cont_err,
                omitidos=cont_omitidos, ejemplares=cont_ejemplares,
                incidencias=incidencias[-100:], **extra,
            )
            filas_nuevas.clear()
            self._publicar_ui(self._mostrar_avance_lote, lote_id)

        def comprobar_detencion():
            if self._detencion_solicitada.is_set():
                raise _DetencionSolicitada()

        try:
            comprobar_detencion()
            reader = AccessReader(path_access)
            writer = MySQLWriter(config_mysql)
            writer.connect()
            comprobar_detencion()
            writer.crear_tablas()
            comprobar_detencion()
            guardar_avance(etapa='lectura', evento='Destino conectado. Leyendo fichas del respaldo.')
            lote = self.historial_lotes.obtener(lote_id, resumen=True)
            if ((firma and self._firma_access(path_access) != firma)
                    or (firma is None and reader.contar_fichas() != lote.total_recibidos)):
                raise ValueError('El respaldo cambió después de validarlo. Vuelve a validarlo.')
            comprobar_detencion()
            codigos_repetidos = reader.codigos_adquisicion_repetidos()
            comprobar_detencion()
            bloques = iter(reader.iterar_bloques(limite or None))
            posicion = 0
            for fichas in bloques:
                comprobar_detencion()
                ids = []
                for ficha in fichas:
                    try:
                        ids.append(int(ficha['Ficha_No']))
                    except (KeyError, TypeError, ValueError):
                        continue
                ejemplares_por_ficha = reader.leer_ejemplares_por_ficha(ids)
                comprobar_detencion()
                if not posicion:
                    guardar_avance(etapa='conversion', evento='Convirtiendo y guardando fichas con sus ejemplares.')

                for ficha in fichas:
                    comprobar_detencion()
                    posicion += 1
                    id_ficha = None
                    referencia = f'Fila {posicion}'
                    estado_ficha = 'Rechazada'
                    motivos = []
                    try:
                        id_ficha = int(ficha['Ficha_No'])
                        if not 0 <= id_ficha <= 4294967295:
                            id_ficha = None
                            raise ValueError('El identificador de Access está fuera del rango admitido.')
                        referencia = f'Ficha {id_ficha}'
                        ejemplares = ejemplares_por_ficha.get(id_ficha, [])
                        existe = saltar and writer.registrar_existe(id_ficha)
                        if existe and not lote.lote_origen:
                            estado_ficha = 'Omitida'
                            motivos.append('La ficha ya existe en el destino.')
                            cont_omitidos += 1
                        else:
                            for ejemplar in ejemplares:
                                codigo = str(ejemplar.get('NumAdqui') or '').strip()
                                if codigo.casefold() in codigos_repetidos:
                                    raise ValueError(f'Código de barras repetido en Access: {codigo}.')

                            with writer.transaccion_ficha():
                                if existe:
                                    agregados, sucursales = writer.insertar_ejemplares_faltantes(
                                        id_ficha, ejemplares, branch_mapping,
                                        signatura=ficha.get('Clasificacion'),
                                    )
                                    avisos = [
                                        ('Biblioteca', f'No contemplado: Biblioteca={codigo!r} sin sucursal Koha.')
                                        for codigo in sorted(set(sucursales))
                                    ]
                                else:
                                    agregados, avisos = self._convertir_y_guardar_ficha(
                                        writer, ficha, id_ficha, ejemplares,
                                        branch_mapping, status_mapping,
                                    )
                            cont_ejemplares += agregados
                            for campo, mensaje in avisos:
                                motivos.append(f'{campo}: {mensaje}')
                                incidencias.append({
                                    'referencia': referencia + ' · ' + campo, 'mensaje': mensaje,
                                })
                            if existe:
                                cont_omitidos += 1
                                estado_ficha = 'Omitida'
                                motivos.append(f'Ficha existente. Ejemplares agregados: {agregados}.')
                            else:
                                cont_ok += 1
                                estado_ficha = 'Convertida'
                    except Exception as exc:
                        cont_err += 1
                        mensaje = self._error_mysql_sin_secreto(exc, config_mysql.get('password'))
                        motivos.append(mensaje)
                        incidencias.append({'referencia': referencia, 'mensaje': mensaje})
                        self.log(f'[ERROR] Lote {lote_id}, {referencia}: {mensaje}')
                        try:
                            writer.insertar_log('ERROR', mensaje, id_ficha=id_ficha)
                        except Exception:
                            pass
                    filas_nuevas.append({
                        'id': id_ficha, 'referencia': referencia, 'titulo': str(ficha.get('Titulo') or ''),
                        'estado': estado_ficha, 'motivos': motivos,
                    })
                    if len(filas_nuevas) >= 250 or monotonic() - ultimo_avance >= 0.7:
                        guardar_avance()
                        ultimo_avance = monotonic()

            if posicion != lote.total_objetivo:
                raise ValueError('El número de fichas leídas no coincide con el alcance del lote.')
            if firma and self._firma_access(path_access) != firma:
                raise ValueError('El respaldo cambió durante la ejecución. Revisa el lote antes de continuar.')
            tiene_incidencias = bool(cont_err or incidencias)
            estado = 'con_incidencias' if tiene_incidencias else 'concluido'
            guardar_avance(
                estado=estado, etapa='revision' if tiene_incidencias else 'finalizado',
                evento=f'Ejecución terminada. Convertidas: {cont_ok}; omitidas: {cont_omitidos}; errores: {cont_err}.',
            )
            self.log(f'Lote {lote_id} finalizado. Convertidas: {cont_ok}, omitidas: {cont_omitidos}, errores: {cont_err}.')
            self._publicar_ui(self._finalizar_migracion)
            self._publicar_ui(messagebox.showwarning if tiene_incidencias else messagebox.showinfo,
                'Lote con incidencias' if tiene_incidencias else 'Lote concluido',
                f'Convertidas: {cont_ok}\nYa existentes: {cont_omitidos}\nErrores: {cont_err}'
                f'\nIncidencias: {len(incidencias)}\nEjemplares: {cont_ejemplares}')
        except _DetencionSolicitada:
            try:
                lote = self.historial_lotes.obtener(lote_id, resumen=True)
                pendientes = lote.total_objetivo - cont_ok - cont_omitidos - cont_err
                guardar_avance(estado='detenido', evento=f'Detenido por el usuario. Pendientes: {pendientes}.')
                self._publicar_ui(self._finalizar_migracion)
                self._publicar_ui(messagebox.showinfo, 'Migración detenida',
                    f'Se conservó el avance. Pendientes: {pendientes}.')
            except (OSError, ValueError) as exc:
                self._publicar_ui(self._finalizar_migracion)
                self._publicar_ui(messagebox.showerror, 'No se pudo guardar la detención', str(exc))
        except Exception as exc:
            mensaje = self._error_mysql_sin_secreto(exc, config_mysql.get('password'))
            incidencias.append({'referencia': 'Ejecución', 'mensaje': mensaje})
            try:
                guardar_avance(estado='con_incidencias', evento='Ejecución interrumpida. Revisa las incidencias.')
            except (OSError, ValueError) as error_historial:
                self.log('[ERROR] No se pudo guardar el último avance del lote: ' + str(error_historial))
            self.log(f'[ERROR FATAL] Lote {lote_id}: {mensaje}')
            self._publicar_ui(self._finalizar_migracion)
            self._publicar_ui(messagebox.showerror, 'Error en migración', mensaje)
        finally:
            for recurso in (bloques, reader, writer):
                if recurso is not None:
                    try:
                        recurso.close()
                    except Exception:
                        pass

    def _convertir_y_guardar_ficha(self, writer, ficha, id_ficha, ejemplares,
                                  branch_mapping, status_mapping):
        incidencias = []
        record = self.marc_converter.ficha_a_record(
            ficha, ejemplares, branch_mapping=branch_mapping, status_mapping=status_mapping,
            incidencias=incidencias,
        )
        xml = self.marc_converter.record_a_marcxml(record)
        iso = self.marc_converter.record_a_iso2709(record)
        id_registro = writer.insertar_registro_marc(id_ficha, str(id_ficha), xml, iso)
        avisos = [(item['referencia'], item['mensaje']) for item in incidencias]
        for ejemplar in ejemplares:
            biblioteca = ejemplar.get('Biblioteca')
            codigo = str(biblioteca).strip() if biblioteca is not None else ''
            sucursal = branch_mapping.get(codigo) if codigo else None
            if not sucursal and not any(campo in ('952$a', '952$b') for campo, _ in avisos):
                mensaje = (f'No contemplado: Biblioteca={codigo!r} sin correspondencia Koha.'
                           if codigo else 'Faltante: Biblioteca no tiene valor.')
                avisos.append(('Biblioteca', mensaje))
            writer.insertar_ejemplar(
                id_registro, id_ficha, ejemplar, sucursal, signatura=ficha.get('Clasificacion'),
            )
        return len(ejemplares), avisos

    def _mostrar_avance_lote(self, identificador):
        lote = self.historial_lotes.obtener(identificador, resumen=True)
        if lote is None:
            return
        animar_valor(self.progress, lote.progreso)
        estado = {'con_incidencias': 'Con incidencias', 'concluido': 'Concluido', 'detenido': 'Detenido'}.get(
            lote.estado, ETAPAS[lote.etapa],
        )
        if lote.estado == 'en_proceso' and self._detencion_solicitada.is_set():
            estado = 'Deteniendo al terminar la ficha u operación en curso…'
        self.lbl_estado.config(text=f'{lote.id}: {lote.procesados}/{lote.total_objetivo} · {estado}')
        self.lbl_stats.config(text=f'Correctos: {lote.correctos} | Omitidos: {lote.omitidos} | Errores: {lote.errores} | Incidencias: {len(lote.incidencias)} | Ejemplares: {lote.ejemplares}')
        self._actualizar_panel()

    def _finalizar_migracion(self):
        self.migracion_en_curso = self._preparando_lote = False
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

    def _obtener_registros_revision(self, lote_id, inicio, cantidad):
        if not self._sesion_valida():
            raise PermissionError('La sesión ya no es válida. Inicia sesión nuevamente.')
        try:
            requerir_permiso(self.perfil_usuario, 'revision_muestra')
        except AccesoDenegado as exc:
            raise PermissionError(str(exc)) from exc

        lote = self.historial_lotes.obtener(lote_id)
        if lote is None:
            raise ValueError('No se encontró el lote seleccionado.')
        if not self._politica_lote(lote)['revision']:
            raise ValueError(
                'La revisión requiere registros migrados y que el destino MySQL '
                'coincida con el usado por este lote.'
            )
        if (type(inicio) is not int or type(cantidad) is not int
                or inicio < 0 or cantidad < 1 or cantidad > 100):
            raise ValueError('El rango de registros solicitado no es válido.')

        config = {
            **self._destino_actual(),
            'user': self.entry_user.get(),
            'password': self.entry_pass.get(),
            'charset': 'utf8mb4',
        }
        writer = MySQLWriter(config)
        try:
            writer.connect()
            # El lote define qué fichas correctas pueden revisarse.
            fichas = lote.fichas_correctas[inicio:inicio + cantidad]
            registros = writer.obtener_registros_revision(fichas)
            self.historial_lotes.actualizar(
                lote.id,
                evento=f'Se consultaron {len(registros)} registros migrados para revisión.',
            )
            return registros
        except Exception as exc:
            mensaje = str(exc)
            password = config.get('password')
            if password:
                mensaje = mensaje.replace(password, '***')
            raise RuntimeError(mensaje) from exc
        finally:
            writer.close()

    def _usuario_actual(self):
        if self.auth_service is None:
            return 'sesion-local'
        return self.auth_service.get_username(self.session_token)

    def _writer_revision(self):
        return MySQLWriter({
            **self._destino_actual(),
            'user': self.entry_user.get(),
            'password': self.entry_pass.get(),
            'charset': 'utf8mb4',
        })

    def _validar_lote_revision(self, lote_id, permiso):
        if not self._sesion_valida():
            raise PermissionError('La sesión ya no es válida. Inicia sesión nuevamente.')
        try:
            requerir_permiso(self.perfil_usuario, permiso)
        except AccesoDenegado as exc:
            raise PermissionError(str(exc)) from exc
        lote = self.historial_lotes.obtener(lote_id)
        if lote is None:
            raise ValueError('No se encontró el lote solicitado.')
        if not lote.destino or lote.destino != self._destino_actual():
            raise ValueError(
                'El destino MySQL debe coincidir con el usado por el lote.'
            )
        return lote

    @staticmethod
    def _error_mysql_sin_secreto(error, password):
        mensaje = str(error)
        return mensaje.replace(password, '***') if password else mensaje

    def _proponer_correccion(self, lote_id, id_ficha, marcxml, iso2709,
                             huella_original):
        lote = self._validar_lote_revision(lote_id, 'proponer_correccion')
        # La ficha debe pertenecer al lote; su huella detecta vistas desactualizadas.
        if type(id_ficha) is not int or id_ficha not in lote.fichas_correctas:
            raise ValueError('La ficha no pertenece a los registros correctos de este lote.')
        writer = self._writer_revision()
        try:
            writer.connect()
            registro = writer.obtener_registros_revision([id_ficha])
            if not registro:
                raise ValueError('No se encontró el registro MARC en el destino.')
            if registro[0]['huella_revision'] != huella_original:
                raise ValueError(
                    'El registro cambió desde que se abrió para edición. '
                    'Actualiza la revisión y vuelve a proponer la corrección.'
                )
            propuesta_id = writer.proponer_correccion(
                lote_id, id_ficha, marcxml, iso2709, huella_original,
                self._usuario_actual(),
            )
            self.historial_lotes.actualizar(
                lote.id,
                evento=f'Corrección de ficha {id_ficha} propuesta; pendiente de aprobación.',
            )
            return propuesta_id
        except Exception as exc:
            password = writer.config.get('password')
            raise RuntimeError(
                self._error_mysql_sin_secreto(exc, password),
            ) from exc
        finally:
            writer.close()

    def _listar_correcciones_pendientes(self, lote_id):
        self._validar_lote_revision(lote_id, 'aprobar_correccion')
        writer = self._writer_revision()
        try:
            writer.connect()
            return writer.listar_correcciones_pendientes(lote_id)
        except Exception as exc:
            password = writer.config.get('password')
            raise RuntimeError(
                self._error_mysql_sin_secreto(exc, password),
            ) from exc
        finally:
            writer.close()

    def _resolver_correccion(self, lote_id, propuesta_id, aprobar):
        permiso = 'aprobar_correccion' if aprobar else 'rechazar_correccion'
        lote = self._validar_lote_revision(lote_id, permiso)
        if type(propuesta_id) is not int or type(aprobar) is not bool:
            raise ValueError('La decisión sobre la propuesta no es válida.')
        writer = self._writer_revision()
        try:
            writer.connect()
            estado = writer.resolver_correccion(
                propuesta_id, lote_id, self._usuario_actual(), aprobar,
            )
            self.historial_lotes.actualizar(
                lote.id,
                evento=f'Corrección MARC #{propuesta_id} {estado.lower()} por aprobación.',
            )
            return estado
        except Exception as exc:
            password = writer.config.get('password')
            raise RuntimeError(
                self._error_mysql_sin_secreto(exc, password),
            ) from exc
        finally:
            writer.close()

    def _validar_ficha_observacion(self, lote, id_ficha):
        # Vincula cada nota al conjunto de fichas correctas registrado para el lote.
        if type(id_ficha) is not int or id_ficha not in lote.fichas_correctas:
            raise ValueError('La ficha no pertenece a los registros correctos de este lote.')

    def _listar_observaciones_revision(self, lote_id, id_ficha):
        lote = self._validar_lote_revision(lote_id, 'registrar_observacion')
        self._validar_ficha_observacion(lote, id_ficha)
        writer = self._writer_revision()
        try:
            writer.connect()
            writer.crear_tablas()
            return writer.listar_observaciones_revision(lote_id, id_ficha)
        except Exception as exc:
            password = writer.config.get('password')
            raise RuntimeError(
                self._error_mysql_sin_secreto(exc, password),
            ) from exc
        finally:
            writer.close()

    def _registrar_observacion_revision(self, lote_id, id_ficha, observacion):
        lote = self._validar_lote_revision(lote_id, 'registrar_observacion')
        self._validar_ficha_observacion(lote, id_ficha)
        writer = self._writer_revision()
        try:
            writer.connect()
            writer.crear_tablas()
            observacion_id = writer.registrar_observacion_revision(
                lote_id, id_ficha, self._usuario_actual(), observacion,
            )
            self.historial_lotes.actualizar(
                lote.id,
                evento=f'Observación #{observacion_id} registrada para ficha {id_ficha}.',
            )
            return observacion_id
        except Exception as exc:
            password = writer.config.get('password')
            raise RuntimeError(
                self._error_mysql_sin_secreto(exc, password),
            ) from exc
        finally:
            writer.close()
