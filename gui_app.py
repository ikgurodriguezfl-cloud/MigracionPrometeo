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
from permissions import MATRIZ_PERMISOS, requerir_permiso, AccesoDenegado
from identidad import aplicar_estilo, centrar, logo
from exportacion_marc import exportar_lote


class _DetencionSolicitada(Exception):
    """Señal interna para terminar entre operaciones, sin cortar una ficha."""


class MigracionApp:
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
        aplicar_estilo(root)
        centrar(root)

        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        self.config = self.cargar_config()

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
        barra = ttk.Frame(self.root, style='Marca.TFrame', padding=(8, 3))
        barra.pack(fill='x')
        logo(barra, 'nayarit-cecan.png').pack(side='left')
        self.cuenta = ttk.Menubutton(barra, text='Cuenta')
        menu = tk.Menu(self.cuenta, tearoff=False)
        if self.perfil_usuario == 'Administracion':
            menu.add_command(label='Crear usuario', command=self._abrir_registro_usuario)
        menu.add_command(label='Cerrar sesión', command=self._cerrar_sesion)
        self.cuenta.configure(menu=menu)
        self.cuenta.pack(side='right')
        self.estado_mysql = tk.StringVar(value='MySQL · sin probar')
        self.abrir_ajustes = ttk.Button(barra, text='Ajustes', command=lambda: self.notebook.select(self.ajustes))
        self.abrir_ajustes.pack(side='right', padx=3)
        ttk.Button(barra, text='Ayuda', command=self._iniciar_tutorial).pack(side='right', padx=3)
        ttk.Label(self.root, textvariable=self.estado_mysql, anchor='e').pack(fill='x', padx=10)

        ttk.Style(self.root).layout('Espacio.TNotebook.Tab', [])
        self.notebook = ttk.Notebook(self.root, style='Espacio.TNotebook')
        self.notebook.pack(fill='both', expand=True)
        self.frame_conexion = ttk.Frame(self.notebook, padding=10)
        self.ajustes = ttk.Frame(self.notebook, padding=8)
        self.panel_lotes = PanelLotes(self.notebook, self.historial_lotes.listar, self._politica_lote,
                                      self._iniciar_desde_panel, self._exportar_marcxml,
                                      self._nuevo_lote, self._solicitar_detencion)
        for marco, nombre in ((self.panel_lotes,'Lotes'),(self.frame_conexion,'Preparar'),(self.ajustes,'Ajustes')):
            self.notebook.add(marco, text=nombre)
        for marco, titulo in ((self.frame_conexion,'Preparar un lote'), (self.ajustes,'Ajustes')):
            cabecera = ttk.Frame(marco)
            cabecera.pack(fill='x', pady=(0,6))
            ttk.Label(cabecera, text=titulo, style='Titulo.TLabel').pack(side='left')
            ttk.Button(cabecera, text='Volver a lotes', command=lambda: self.notebook.select(self.panel_lotes)).pack(side='right')

        self.notebook_ajustes = ttk.Notebook(self.ajustes)
        self.notebook_ajustes.pack(fill='both', expand=True)
        self.destino = ttk.Frame(self.notebook_ajustes)
        self.frame_config = ttk.Frame(self.notebook_ajustes)
        self.frame_log = ttk.Frame(self.notebook_ajustes)
        if self.perfil_usuario == 'Administracion':
            self.notebook_ajustes.add(self.destino, text='Destino MySQL')
            self.notebook_ajustes.add(self.frame_config, text='Mapeo MARC21')
        self.notebook_ajustes.add(self.frame_log, text='Bitácora')
        self._crear_preparacion()
        self._crear_destino(self.destino)
        self._crear_pestana_config()
        self._crear_pestana_log()
        for var in (self.entry_host, self.entry_port, self.entry_db, self.entry_user, self.entry_pass):
            var.trace_add('write', self._cambio_destino)

    def _cambio_destino(self, *_):
        self.estado_mysql.set('MySQL · sin probar')
        self._actualizar_panel()

    def _nuevo_lote(self):
        if (self._sesion_valida() and not self.migracion_en_curso
                and self.perfil_usuario in MATRIZ_PERMISOS['validar_access']):
            self.notebook.select(self.frame_conexion)

    def _campo(self, parent, fila, col, texto, valor, ancho=30, show=None):
        ttk.Label(parent, text=texto).grid(row=fila, column=col*2, sticky='e', padx=5, pady=2)
        var = tk.StringVar(value=valor)
        entry = ttk.Entry(parent, textvariable=var, width=ancho, show=show)
        entry.grid(row=fila, column=col*2+1, sticky='w', padx=5, pady=2)
        return var

    def _crear_preparacion(self):
        f = self.frame_conexion

        lbl_access = ttk.LabelFrame(f, text='Base de datos Access (.mdb/.accdb)')
        lbl_access.pack(fill='x', padx=10, pady=5)

        self.var_access_path = tk.StringVar(value=self.config.get('access', {}).get('path', ''))
        self.var_access_path.trace_add('write', lambda *_: self._actualizar_info_access())
        fila_archivo = ttk.Frame(lbl_access)
        fila_archivo.pack(fill='x', padx=5, pady=(5, 0))
        fila_archivo.columnconfigure(0, weight=1)
        ttk.Entry(fila_archivo, textvariable=self.var_access_path).grid(
            row=0, column=0, sticky='ew', padx=(0, 5)
        )
        ttk.Button(fila_archivo, text='Examinar...', command=self._seleccionar_access).grid(
            row=0, column=1, padx=5
        )


        fila_info = ttk.Frame(lbl_access)
        fila_info.pack(fill='x', padx=5, pady=(3, 5))
        fila_info.columnconfigure(0, weight=1)
        self.lbl_info_access = ttk.Label(
            fila_info, text='Archivo seleccionado: --', anchor='w'
        )
        self.lbl_info_access.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.lbl_conteo_access = ttk.Label(fila_info, text='Registros: --', anchor='e')
        self.lbl_conteo_access.grid(row=0, column=1, sticky='e')
        self._actualizar_info_access()

        opciones = ttk.LabelFrame(f, text='Alcance de esta ejecución', padding=8)
        opciones.pack(fill='x', padx=10, pady=5)
        self.var_limite = tk.StringVar(value='0')
        ttk.Label(opciones, text='Máximo de fichas (0 = todas)').pack(anchor='w')
        ttk.Entry(opciones, width=10, textvariable=self.var_limite).pack(anchor='w')
        self.var_saltar_existentes = tk.BooleanVar(value=True)
        ttk.Checkbutton(opciones, text='Omitir fichas ya migradas', variable=self.var_saltar_existentes).pack(anchor='w')
        ttk.Button(f, text='Validar y preparar lote', style='Principal.TButton',
                   command=self._probar_access).pack(anchor='e', padx=10, pady=8)

    def _crear_destino(self, f):
        lbl_mysql = ttk.LabelFrame(f, text='Base de datos MySQL (destino MARC21)')
        lbl_mysql.pack(fill='x', padx=10, pady=5)

        grid = ttk.Frame(lbl_mysql)
        grid.pack(fill='x', padx=5, pady=5)

        self.entry_host = self._campo(grid, 0, 0, 'Host:', self.config.get('mysql', {}).get('host', 'localhost'))
        self.entry_port = self._campo(grid, 3, 0, 'Puerto:', str(self.config.get('mysql', {}).get('port', 3306)), ancho=8)
        self.entry_user = self._campo(grid, 1, 0, 'Usuario:', self.config.get('mysql', {}).get('user', 'root'))
        self.entry_pass = self._campo(grid, 4, 0, 'Contrasena:', self.config.get('mysql', {}).get('password', ''), show='*')
        self.entry_db = self._campo(grid, 2, 0, 'Base de datos:', self.config.get('mysql', {}).get('database', 'prometeo_marc'))

        ttk.Button(lbl_mysql, text='Probar conexion MySQL', command=self._probar_mysql).pack(pady=5)
        ttk.Button(lbl_mysql, text='Guardar ajustes', command=self._guardar_config).pack(pady=3)
        self.lbl_conteo_mysql = ttk.Label(lbl_mysql, text='Registros migrados: --')
        self.lbl_conteo_mysql.pack(pady=2)

    def _crear_pestana_config(self):
        f = self.frame_config
        ttk.Button(f, text='Guardar ajustes', command=self._guardar_config).pack(side='bottom', pady=4)

        lbl_map = ttk.LabelFrame(f, text='Mapeo de bibliotecas (Codigo Access -> Codigo sucursal Koha)')
        lbl_map.pack(fill='both', expand=True, padx=10, pady=5)

        txt_frame = ttk.Frame(lbl_map)
        txt_frame.pack(fill='both', expand=True, padx=5, pady=5)
        self.txt_mapeo = tk.Text(txt_frame, width=25, height=3)
        self.txt_mapeo.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(txt_frame, command=self.txt_mapeo.yview)
        scroll.pack(side='right', fill='y')
        self.txt_mapeo.configure(yscrollcommand=scroll.set)

        ejemplo = json.dumps(self.config.get('koha_branch_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_mapeo.insert('1.0', ejemplo)

        lbl_status = ttk.LabelFrame(f, text='Mapeo de estado de ejemplar (Accesible -> Estado Koha)')
        lbl_status.pack(fill='x', padx=10, pady=5)
        self.txt_status = tk.Text(lbl_status, width=25, height=3)
        self.txt_status.pack(fill='x', padx=5, pady=5)
        ejemplo_status = json.dumps(self.config.get('item_status_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_status.insert('1.0', ejemplo_status)

        lbl_tipos = ttk.LabelFrame(f, text='Valores por defecto para Koha (942 y 952)')
        lbl_tipos.pack(fill='x', padx=10, pady=5)

        grid_tipos = ttk.Frame(lbl_tipos)
        grid_tipos.pack(fill='x', padx=5, pady=5)

        self.entry_item_type_bib = self._campo(grid_tipos, 0, 0, '942$c - Tipo ítem bibliográfico:', self.var_item_type_bib.get(), ancho=12)
        self.entry_item_type_item = self._campo(grid_tipos, 2, 0, '952$y - Tipo ítem ejemplar:', self.var_item_type_item.get(), ancho=12)
        self.entry_homebranch = self._campo(grid_tipos, 1, 0, '952$a - Homebranch:', self.var_homebranch.get(), ancho=12)
        self.entry_holdingbranch = self._campo(grid_tipos, 3, 0, '952$b - Holdingbranch:', self.var_holdingbranch.get(), ancho=12)



    def _crear_pestana_log(self):
        f = self.frame_log
        self.txt_log = tk.Text(f, wrap='word', width=100, height=25)
        self.txt_log.pack(fill='both', expand=True, padx=10, pady=5)
        ttk.Button(f, text='Limpiar log', command=lambda: self.txt_log.delete('1.0', tk.END)).pack(pady=5)

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
        if not self._sesion_valida() or self.perfil_usuario != 'Administracion':
            return
        destino = self._destino_actual()
        if not destino or not 1 <= destino['port'] <= 65535:
            messagebox.showerror('Puerto no válido', 'El puerto debe estar entre 1 y 65535.')
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
            messagebox.showinfo('Exito', 'Configuracion guardada.')
            self.log('Configuracion guardada.')
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
        for accion, permiso in (('iniciar','iniciar_conversion'), ('detener','iniciar_conversion'),
                                ('exportar','aprobar_exportacion')):
            politica[accion] = politica[accion] and self.perfil_usuario in MATRIZ_PERMISOS[permiso]
        return politica

    def _actualizar_panel(self):
        if not hasattr(self, 'entry_db'):
            return
        self.panel_lotes.actualizar()
        permitir = (not self.migracion_en_curso and not self.historial_lotes.solo_lectura
                    and self.perfil_usuario in MATRIZ_PERMISOS['validar_access'])
        self.panel_lotes.nuevo.configure(state='normal' if permitir else 'disabled')
        self.abrir_ajustes.configure(state='disabled' if self.migracion_en_curso else 'normal')

    def _solicitar_detencion(self, identificador=None):
        identificador = identificador or self._lote_actual_id
        lote = self.historial_lotes.obtener(identificador)
        if not self._politica_lote(lote)['detener']:
            return
        self._detencion_solicitada.set()
        self.log(f'Lote {identificador}: detención solicitada por el usuario.')
        self._actualizar_panel()

    def _iniciar_desde_panel(self, identificador):
        lote = self.historial_lotes.obtener(identificador)
        if not self._politica_lote(lote)['iniciar']:
            messagebox.showwarning('Acción no disponible', 'Valida el respaldo seleccionado antes de iniciar ese lote.')
            return
        self._lote_actual_id = identificador
        self.var_limite.set(str(lote.total_objetivo))
        self.var_saltar_existentes.set(lote.omitir_existentes)
        self._iniciar_migracion()

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
            messagebox.showwarning('Migración en curso', 'Detén el lote antes de cerrar la sesión.')
            return
        self._cerrando = True
        self.root.after_cancel(self._after_ui)
        if self.auth_service is not None:
            self.auth_service.logout(self.session_token)
        if self.on_logout is not None:
            self.on_logout()
        else:
            self.cerrar()

    def _iniciar_tutorial(self):
        """Inicia un tutorial guiado e interactivo paso a paso por la aplicación."""
        es_admin = self.auth_service is not None and self.auth_service.is_admin(self.session_token)

        # Referencias a los botones objetivo de cada paso (para resaltarlos).
        btn_nuevo_lote = getattr(self.panel_lotes, 'nuevo', None)
        btn_ejecutar = getattr(self.panel_lotes, 'btn_iniciar', None)
        btn_exportar = getattr(self.panel_lotes, 'btn_exportar', None)
        btn_cuenta = getattr(self, 'cuenta', None)

        def navegar(marco_principal=None, sub_pestana=None):
            if marco_principal is not None:
                self.notebook.select(marco_principal)
                self.root.update_idletasks()
            if sub_pestana is not None:
                self.notebook_ajustes.select(sub_pestana)
                self.root.update_idletasks()

        def resaltar_objetivo(widget, color='#c00000'):
            """Dibuja un borde rojo punteado alrededor del widget sin tapar el contenido."""
            if widget is None:
                return None
            try:
                widget.update_idletasks()
                x = widget.winfo_x()
                y = widget.winfo_y()
                w = widget.winfo_width()
                h = widget.winfo_height()
                if w <= 1 or h <= 1:
                    return None
                parent = widget.master
                canvas = tk.Canvas(parent, width=w, height=h, highlightthickness=0,
                                   bg=parent.cget('background'))
                canvas.place(x=x, y=y)
                canvas.create_rectangle(2, 2, w - 3, h - 3, outline=color, width=3, dash=(6, 4))
                widget.lift()  # El widget queda encima del canvas para seguir siendo clickeable
                return canvas
            except tk.TclError:
                return None

        def quitar_resaltado(overlay):
            """Elimina el borde de resaltado."""
            if overlay is not None:
                try:
                    overlay.destroy()
                except tk.TclError:
                    pass

        pasos = [
            {
                'titulo': 'Modo tutorial',
                'mensaje': ('Se ha iniciado el modo tutorial de Prometeo Migrator.\n\n'
                            'Pulsa OK para comenzar con el primer paso.'),
                'pestana': None,
                'sub_pestana': None,
                'objetivo': None,
                'objetivo_nombre': None,
            },
            {
                'titulo': 'Paso 1 - Nuevo lote',
                'mensaje': ('Paso 1: Haz clic en el botón "Nuevo lote" resaltado abajo.\n\n'
                            'Este botón te lleva a la pantalla para preparar un nuevo lote de migración.\n\n'
                            'Una vez que hagas clic en el botón resaltado, continuarán los siguientes pasos.'),
                'pestana': self.panel_lotes,
                'sub_pestana': None,
                'objetivo': btn_nuevo_lote,
                'objetivo_nombre': 'botón Nuevo lote',
            },
            {
                'titulo': 'Paso 2 - Base de datos MySQL',
                'mensaje': ('Paso 2: Haz clic en la pestaña "Destino MySQL" resaltada abajo.\n\n'
                            'Aquí eliges la base de datos MySQL de destino.\n\n'
                            'Debes tener MySQL instalado y funcionando para que la migración '
                            'pueda escribir los registros MARC21 convertidos.'),
                'pestana': self.ajustes,
                'sub_pestana': self.destino,
                'objetivo': self.notebook_ajustes,
                'objetivo_nombre': 'pestaña Destino MySQL',
            },
            {
                'titulo': 'Paso 3 - Configuración avanzada',
                'mensaje': ('Paso 3: Haz clic en la pestaña "Mapeo MARC21" resaltada abajo.\n\n'
                            'Aquí configuras los mapeos de bibliotecas, estados de ejemplar '
                            'y los valores por defecto para Koha (campos 942 y 952).'),
                'pestana': self.ajustes,
                'sub_pestana': self.frame_config,
                'objetivo': self.notebook_ajustes,
                'objetivo_nombre': 'pestaña Mapeo MARC21',
            },
            {
                'titulo': 'Paso 4 - Log',
                'mensaje': ('Paso 4: Haz clic en la pestaña "Bitácora" resaltada abajo.\n\n'
                            'El log muestra los eventos y mensajes de la migración en tiempo real.'),
                'pestana': self.ajustes,
                'sub_pestana': self.frame_log,
                'objetivo': self.notebook_ajustes,
                'objetivo_nombre': 'pestaña Bitácora',
            },
            {
                'titulo': 'Paso 5 - Configurar el lote',
                'mensaje': ('Paso 5: Configura el lote en la pantalla de Lotes.\n\n'
                            'Selecciona tu archivo de respaldo Access, valida la conexión y el sistema '
                            'registrará el lote para su procesamiento.\n\n'
                            'Cuando hayas revisado la pantalla, pulsa OK para continuar.'),
                'pestana': self.panel_lotes,
                'sub_pestana': None,
                'objetivo': None,
                'objetivo_nombre': None,
            },
            {
                'titulo': 'Paso 6 - Botón Ejecutar migración',
                'mensaje': ('Paso 6: Haz clic en el botón "Ejecutar migración" resaltado abajo.\n\n'
                            'Este botón inicia el procesamiento del lote seleccionado.\n\n'
                            'Una vez que hagas clic en el botón resaltado, continuarán los siguientes pasos.'),
                'pestana': None,
                'sub_pestana': None,
                'objetivo': btn_ejecutar,
                'objetivo_nombre': 'botón Ejecutar migración',
            },
            {
                'titulo': 'Paso 7 - Botón Exportar MARCXML',
                'mensaje': ('Paso 7: Haz clic en el botón "Exportar MARCXML del lote" resaltado abajo.\n\n'
                            'Este botón genera un archivo MARCXML con los registros '
                            'correctos una vez el lote concluya sin errores.\n\n'
                            'Una vez que hagas clic en el botón resaltado, continuarán los siguientes pasos.'),
                'pestana': None,
                'sub_pestana': None,
                'objetivo': btn_exportar,
                'objetivo_nombre': 'botón Exportar MARCXML del lote',
            },
        ]

        if es_admin and btn_cuenta is not None:
            pasos.append({
                'titulo': 'Paso 8 - Crear usuario (Administrador)',
                'mensaje': ('Último paso: Haz clic en el menú "Cuenta" resaltado de la barra superior.\n\n'
                            'Como administrador, puedes crear nuevos usuarios.\n\n'
                            'Funciones de cada rol:\n'
                            '• Ejecucion: valida Access e inicia conversiones.\n'
                            '• Revision: revisa muestras de los registros.\n'
                            '• Aprobacion: aprueba exportaciones a MARCXML.\n'
                            '• Administracion: acceso completo, incluida creación de usuarios y configuración.\n\n'
                            'Una vez que hagas clic en el menú resaltado, finalizará el tutorial.'),
                'pestana': None,
                'sub_pestana': None,
                'objetivo': btn_cuenta,
                'objetivo_nombre': 'menú Cuenta',
            })

        for paso in pasos:
            navegar(paso['pestana'], paso['sub_pestana'])

            if paso['objetivo'] is not None:
                # Resaltar el objetivo con borde rojo punteado (sin tapar contenido)
                overlay = resaltar_objetivo(paso['objetivo'])
                # Mostrar popup no modal (solo informa, no bloquea)
                dlg = self._mostrar_dialogo_tutorial_no_modal(paso['titulo'], paso['mensaje'])

                clic_var = tk.BooleanVar(value=False)

                def al_clic(evento, cv=clic_var, overlay=overlay, dlg=dlg,
                            obj=paso['objetivo']):
                    if not cv.get():
                        cv.set(True)
                        quitar_resaltado(overlay)
                        try:
                            dlg.destroy()
                        except tk.TclError:
                            pass
                        try:
                            obj.unbind('<Button-1>')
                        except tk.TclError:
                            pass

                paso['objetivo'].bind('<Button-1>', al_clic, add='+')

                # Esperar a que el usuario haga clic en el objetivo (sin bloquear la interfaz)
                self.root.wait_variable(clic_var)
            else:
                self._mostrar_dialogo_tutorial(paso['titulo'], paso['mensaje'])

        self._mostrar_dialogo_tutorial(
            'Tutorial completado',
            'Has finalizado el modo tutorial. Ya puedes usar el sistema.',
        )

    def _mostrar_dialogo_tutorial_no_modal(self, titulo, mensaje):
        """Muestra un cuadro de diálogo NO modal que solo informa qué hacer."""
        dlg = tk.Toplevel(self.root)
        dlg.title(titulo)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        # Sin grab_set, sin wait_window: no bloquea la interfaz principal

        marco = ttk.Frame(dlg, padding=20)
        marco.pack(fill='both', expand=True)

        ttk.Label(marco, text=mensaje, wraplength=420, justify='left').pack(
            fill='x', pady=(0, 16)
        )

        ttk.Button(marco, text='Entendido', command=dlg.destroy).pack()

        return dlg

    def _mostrar_dialogo_tutorial(self, titulo, mensaje):
        """Muestra un cuadro de diálogo modal sin sonido del sistema (solo para pasos sin objetivo)."""
        dlg = tk.Toplevel(self.root)
        dlg.title(titulo)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        marco = ttk.Frame(dlg, padding=20)
        marco.pack(fill='both', expand=True)

        ttk.Label(marco, text=mensaje, wraplength=400, justify='left').pack(
            fill='x', pady=(0, 16)
        )

        ttk.Button(marco, text='OK', command=dlg.destroy).pack()

        dlg.wait_window()

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
            limite = int(self.var_limite.get())
            if limite < 0:
                raise ValueError('El límite debe ser cero o un entero positivo.')
            errores = self._validar_archivo_access(path)
            if errores:
                raise ValueError('\n'.join(errores))

            reader = AccessReader(path)
            try:
                total = reader.contar_fichas()
            finally:
                reader.close()
            lote = self.historial_lotes.recibir(path, total)
            self._lote_actual_id = lote.id
            self.historial_lotes.actualizar(lote.id, total_objetivo=min(limite, total) if limite else total,
                omitir_existentes=self.var_saltar_existentes.get())
            self._validacion_access = self._firma_access(path)
            self.panel_lotes.seleccionar_real(lote.id)
            self._actualizar_panel()
            self.lbl_conteo_access.config(text='Registros FICHAS: ' + str(total))
            self.log('[OK] Conexion Access exitosa. ' + str(total) + ' fichas encontradas.')
            self.notebook.select(self.panel_lotes)
        except Exception as e:
            self.log('[ERROR] Access: ' + str(e))
            messagebox.showerror('Error', 'No se pudo conectar a Access:\n' + str(e))

    def _mysql_verificado(self):
        self.estado_mysql.set('MySQL · conexión verificada')

    def _probar_mysql(self):
        if not self._sesion_valida() or self.perfil_usuario != 'Administracion':
            return
        self.estado_mysql.set('MySQL · sin verificar')
        writer = None
        try:
            config = self._destino_actual()
            if not config or not 1 <= config['port'] <= 65535:
                raise ValueError('El puerto debe estar entre 1 y 65535.')
            config.update(user=self.entry_user.get(), password=self.entry_pass.get())
            writer = MySQLWriter(config)
            try:
                writer.connect()
            except Exception as exc:
                if not exc.args or exc.args[0] != 1049:
                    raise
                if not messagebox.askyesno('Base de datos inexistente', '¿Crear la base indicada en este servidor?'):
                    return
                writer.ensure_database()
            writer.crear_tablas()
            stats = writer.obtener_estadisticas()
            self.lbl_conteo_mysql.config(text=f"Registros migrados: {stats['total_registros']}")
            self._mysql_verificado()
            self.log('[OK] Conexión MySQL y tablas verificadas.')
            messagebox.showinfo('Conexión verificada', 'El destino MySQL está disponible.')
        except Exception as exc:
            self.estado_mysql.set('MySQL · revisar conexión')
            mensaje = str(exc)
            clave = self.entry_pass.get()
            if clave:
                mensaje = mensaje.replace(clave, '***')
            self.log('[ERROR] MySQL: '+mensaje)
            messagebox.showerror('Error de conexión', mensaje)
        finally:
            if writer:
                writer.close()

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
                usuario=self.auth_service.nombre_usuario(self.session_token) if self.auth_service else None,
                resultados=[], version_mapeo=self.marc_converter.mapping_version,
                huella_mapeo=huella_mapeo,
                evento=(f'Migración iniciada con mapeo MARC21 versión '
                        f'{self.marc_converter.mapping_version} '
                        f'(SHA-256 {huella_mapeo}). Conectando al destino MySQL.'))
        except (OSError, ValueError) as exc:
            messagebox.showerror('No se pudo registrar el lote', str(exc))
            return
        self.migracion_en_curso = True
        self._detencion_solicitada.clear()
        self._actualizar_panel()
        self.notebook.select(self.panel_lotes)

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
        resultados = []
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
                fichas_correctas=fichas_correctas, resultados=resultados, incidencias=incidencias[-100:], **extra)
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
            self._publicar_ui(self._mysql_verificado)
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
                inicio_incidencias = len(incidencias)
                estado_ficha = 'Rechazada'
                id_ficha = None
                try:
                    id_ficha = int(ficha['Ficha_No'])
                    if saltar and writer.registrar_existe(id_ficha):
                        cont_omitidos += 1
                        estado_ficha = 'Omitida'
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
                        with writer.transaccion_ficha():
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
                        cont_ejemplares += len(ejemplares)
                        estado_ficha = 'Convertida'
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
                resultados.append({
                    'id': id_ficha, 'referencia': f'Ficha {id_ficha}' if id_ficha is not None else f'Fila {idx}',
                    'titulo': str(ficha.get('Titulo') or ''), 'estado': estado_ficha,
                    'motivos': [f"{i['referencia']}: {i['mensaje']}" for i in incidencias[inicio_incidencias:]],
                })
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
            exportar_lote(writer.conn, lote.fichas_correctas, path)
            self.historial_lotes.actualizar(lote.id, evento=f'Se exportaron {lote.correctos} registros correctos a MARCXML.')
            self._actualizar_panel()
            messagebox.showinfo('Exito', f'Exportados {lote.correctos} registros del lote {lote.id} a {path}')
        except Exception as e:
            clave = self.entry_pass.get()
            mensaje = str(e).replace(clave, '***') if clave else str(e)
            messagebox.showerror('Error', mensaje)
        finally:
            if writer:
                writer.close()