"""Interfaz grafica de la migracion Prometeo Access -> MySQL MARC21 -> Koha."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import threading
from queue import Empty, Queue
from time import monotonic
from typing import Optional, Dict, Any, List

from access_reader import AccessReader
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter
from lotes import HistorialLotes, acciones_lote
from panel_lotes import PanelLotes


class _DetencionSolicitada(Exception):
    """Señal interna para terminar entre operaciones, sin cortar una ficha."""


class MigracionApp:
    def __init__(self, root: tk.Tk, historial_lotes=None):
        # Inicializa la ventana, carga la configuracion y prepara el conversor MARC.
        self.root = root
        self.root.title('Prometeo Migrator - Access a MARC21 (Koha)')
        ancho = min(1150, self.root.winfo_screenwidth() - 80)
        alto = min(700, self.root.winfo_screenheight() - 120)
        self.root.geometry(f'{ancho}x{alto}')
        self.root.minsize(min(1000, ancho), min(700, alto))

        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        self.config = self.cargar_config()

        self.access_reader: Optional[AccessReader] = None
        self.mysql_writer: Optional[MySQLWriter] = None

        # Valores por defecto para Koha (942 y 952)
        self.var_item_type_bib = tk.StringVar(value=self.config.get('item_type_bib', 'LIBR0'))
        self.var_item_type_item = tk.StringVar(value=self.config.get('item_type_item', 'LIBR0'))
        self.var_homebranch = tk.StringVar(value=self.config.get('homebranch', 'ITT'))
        self.var_holdingbranch = tk.StringVar(value=self.config.get('holdingbranch', 'ITT'))

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
        # El panel forma parte de la misma ventana y del mismo proceso.
        notebook = ttk.Notebook(self.root)
        self.notebook = notebook
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        self.frame_conexion = ttk.Frame(notebook)
        self.frame_migracion = ttk.Frame(notebook)
        self.frame_config = ttk.Frame(notebook)
        self.frame_log = ttk.Frame(notebook)

        self.panel_lotes = PanelLotes(
            notebook, listar=self.historial_lotes.listar, politica=self._politica_lote,
            iniciar=self._iniciar_desde_panel, exportar=self._exportar_marcxml,
            conexiones=lambda: notebook.select(self.frame_conexion),
            detener=self._solicitar_detencion,
        )
        notebook.add(self.panel_lotes, text='Inicio · Lotes')

        notebook.add(self.frame_conexion, text='1. Conexiones')
        notebook.add(self.frame_migracion, text='2. Migracion')
        notebook.add(self.frame_config, text='3. Configuracion')
        notebook.add(self.frame_log, text='4. Log')

        self._crear_pestana_conexion()
        self._crear_pestana_migracion()
        self._crear_pestana_config()
        self._crear_pestana_log()
        for variable in (self.entry_host, self.entry_port, self.entry_db):
            variable.trace_add('write', lambda *_: self._actualizar_panel())

    def _campo(self, parent, fila, col, texto, valor, ancho=30, show=None):
        # Crea una etiqueta y su campo de entrada para reutilizarlos en formularios.
        ttk.Label(parent, text=texto).grid(row=fila, column=col*2, sticky='e', padx=5, pady=2)
        var = tk.StringVar(value=valor)
        entry = ttk.Entry(parent, textvariable=var, width=ancho, show=show)
        entry.grid(row=fila, column=col*2+1, sticky='w', padx=5, pady=2)
        return var

    def _crear_pestana_conexion(self):
        # Muestra el archivo Access de origen y los datos de conexion MySQL destino.
        f = self.frame_conexion

        lbl_access = ttk.LabelFrame(f, text='Base de datos Access (.mdb/.accdb)')
        lbl_access.pack(fill='x', padx=10, pady=5)

        # Ruta editable; al cambiarla se actualizan nombre y tamano del archivo.
        self.var_access_path = tk.StringVar(value=self.config.get('access', {}).get('path', ''))
        self.var_access_path.trace_add('write', lambda *_: self._actualizar_info_access())
        fila_archivo = ttk.Frame(lbl_access)
        fila_archivo.pack(fill='x', padx=5, pady=(5, 0))
        fila_archivo.columnconfigure(0, weight=1)
        # Permite seleccionar una copia Access o probar su conexion y estructura.
        ttk.Entry(fila_archivo, textvariable=self.var_access_path).grid(
            row=0, column=0, sticky='ew', padx=(0, 5)
        )
        ttk.Button(fila_archivo, text='Examinar...', command=self._seleccionar_access).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(fila_archivo, text='Probar conexion', command=self._probar_access).grid(
            row=0, column=2, padx=(5, 0)
        )

        fila_info = ttk.Frame(lbl_access)
        fila_info.pack(fill='x', padx=5, pady=(3, 5))
        fila_info.columnconfigure(0, weight=1)
        # Informa el nombre y peso del archivo, y el conteo tras probar Access.
        self.lbl_info_access = ttk.Label(
            fila_info, text='Archivo seleccionado: --', anchor='w'
        )
        self.lbl_info_access.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.lbl_conteo_access = ttk.Label(fila_info, text='Registros: --', anchor='e')
        self.lbl_conteo_access.grid(row=0, column=1, sticky='e')
        self._actualizar_info_access()

        lbl_mysql = ttk.LabelFrame(f, text='Base de datos MySQL (destino MARC21)')
        lbl_mysql.pack(fill='x', padx=10, pady=5)

        # Datos necesarios para conectar con el servidor y esquema destino.
        grid = ttk.Frame(lbl_mysql)
        grid.pack(fill='x', padx=5, pady=5)

        self.entry_host = self._campo(grid, 0, 0, 'Host:', self.config.get('mysql', {}).get('host', 'localhost'))
        self.entry_port = self._campo(grid, 0, 2, 'Puerto:', str(self.config.get('mysql', {}).get('port', 3306)), ancho=8)
        self.entry_user = self._campo(grid, 1, 0, 'Usuario:', self.config.get('mysql', {}).get('user', 'root'))
        self.entry_pass = self._campo(grid, 1, 2, 'Contrasena:', self.config.get('mysql', {}).get('password', ''), show='*')
        self.entry_db = self._campo(grid, 2, 0, 'Base de datos:', self.config.get('mysql', {}).get('database', 'prometeo_marc'))

        # Verifica MySQL y crea las tablas si la conexion resulta valida.
        ttk.Button(lbl_mysql, text='Probar conexion MySQL', command=self._probar_mysql).pack(pady=5)
        # Muestra el total de registros MARC ya almacenados en el destino.
        self.lbl_conteo_mysql = ttk.Label(lbl_mysql, text='Registros migrados: --')
        self.lbl_conteo_mysql.pack(pady=2)

    def _crear_pestana_migracion(self):
        # Ofrece controles para iniciar la migracion y consultar su avance.
        f = self.frame_migracion

        lbl_opts = ttk.LabelFrame(f, text='Opciones de migracion')
        lbl_opts.pack(fill='x', padx=10, pady=5)

        self.var_limite = tk.StringVar(value='0')
        # Limita la cantidad procesada; cero representa todas las fichas.
        ttk.Label(lbl_opts, text='Limite de registros (0 = todos):').pack(side='left', padx=5, pady=5)
        ttk.Entry(lbl_opts, textvariable=self.var_limite, width=10).pack(side='left', padx=5, pady=5)

        self.var_saltar_existentes = tk.BooleanVar(value=True)
        # Evita insertar fichas cuyo identificador ya exista en MySQL.
        ttk.Checkbutton(lbl_opts, text='Saltar registros ya migrados',
                        variable=self.var_saltar_existentes).pack(side='left', padx=15, pady=5)

        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill='x', padx=10, pady=10)
        # Ejecuta la migracion validada o exporta los registros MARCXML guardados.
        self.btn_ejecutar = ttk.Button(btn_frame, text='Ejecutar migracion', command=self._iniciar_migracion)
        self.btn_ejecutar.pack(side='left', padx=5)
        self.btn_detener = ttk.Button(btn_frame, text='Detener migración', command=self._solicitar_detencion, state='disabled')
        self.btn_detener.pack(side='left', padx=5)
        self.btn_exportar = ttk.Button(btn_frame, text='Exportar MARCXML del lote', command=self._exportar_marcxml)
        self.btn_exportar.pack(side='left', padx=5)

        lbl_prog = ttk.LabelFrame(f, text='Progreso')
        lbl_prog.pack(fill='both', expand=True, padx=10, pady=5)

        # Barra, estado y contadores de registros, ejemplares y errores.
        self.progress = ttk.Progressbar(lbl_prog, orient='horizontal', mode='determinate')
        self.progress.pack(fill='x', padx=10, pady=5)

        self.lbl_estado = ttk.Label(lbl_prog, text='Listo.')
        self.lbl_estado.pack(pady=2)

        self.lbl_stats = ttk.Label(lbl_prog, text='Registros: 0 | Ejemplares: 0 | Errores: 0')
        self.lbl_stats.pack(pady=2)

    def _crear_pestana_config(self):
        # Permite ajustar la equivalencia de codigos Access y valores Koha/MARC.
        f = self.frame_config

        lbl_map = ttk.LabelFrame(f, text='Mapeo de bibliotecas (Codigo Access -> Codigo sucursal Koha)')
        lbl_map.pack(fill='both', expand=True, padx=10, pady=5)

        txt_frame = ttk.Frame(lbl_map)
        txt_frame.pack(fill='both', expand=True, padx=5, pady=5)
        self.txt_mapeo = tk.Text(txt_frame, width=60, height=12)
        self.txt_mapeo.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(txt_frame, command=self.txt_mapeo.yview)
        scroll.pack(side='right', fill='y')
        self.txt_mapeo.configure(yscrollcommand=scroll.set)

        ejemplo = json.dumps(self.config.get('koha_branch_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_mapeo.insert('1.0', ejemplo)

        lbl_status = ttk.LabelFrame(f, text='Mapeo de estado de ejemplar (Accesible -> Estado Koha)')
        lbl_status.pack(fill='x', padx=10, pady=5)
        # JSON que traduce el valor Accesible al estado deseado en Koha.
        self.txt_status = tk.Text(lbl_status, width=60, height=6)
        self.txt_status.pack(fill='x', padx=5, pady=5)
        ejemplo_status = json.dumps(self.config.get('item_status_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_status.insert('1.0', ejemplo_status)

        lbl_tipos = ttk.LabelFrame(f, text='Valores por defecto para Koha (942 y 952)')
        lbl_tipos.pack(fill='x', padx=10, pady=5)

        # Valores por defecto del tipo de item y de las sucursales en MARC.
        grid_tipos = ttk.Frame(lbl_tipos)
        grid_tipos.pack(fill='x', padx=5, pady=5)

        self.entry_item_type_bib = self._campo(grid_tipos, 0, 0, '942$c - Tipo ítem bibliográfico:', self.var_item_type_bib.get(), ancho=12)
        self.entry_item_type_item = self._campo(grid_tipos, 0, 2, '952$y - Tipo ítem ejemplar:', self.var_item_type_item.get(), ancho=12)
        self.entry_homebranch = self._campo(grid_tipos, 1, 0, '952$a - Homebranch:', self.var_homebranch.get(), ancho=12)
        self.entry_holdingbranch = self._campo(grid_tipos, 1, 2, '952$b - Holdingbranch:', self.var_holdingbranch.get(), ancho=12)

        # Guarda en config.json las conexiones y los mapeos configurados.
        ttk.Button(f, text='Guardar configuracion', command=self._guardar_config).pack(pady=10)

    def _crear_pestana_log(self):
        # Presenta mensajes de conexion, validacion y resultado de la migracion.
        f = self.frame_log
        self.txt_log = tk.Text(f, wrap='word', width=100, height=25)
        self.txt_log.pack(fill='both', expand=True, padx=10, pady=5)
        # Borra solo el texto visible del log; no modifica los datos migrados.
        ttk.Button(f, text='Limpiar log', command=lambda: self.txt_log.delete('1.0', tk.END)).pack(pady=5)

    def cargar_config(self) -> Dict:
        # Lee la configuracion guardada; si no existe, la interfaz usa valores por defecto.
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _cargar_config_en_ui(self):
        # Copia conexiones y mapeos guardados a los controles de la interfaz.
        self.var_access_path.set(self.config.get('access', {}).get('path', ''))
        self.entry_host.set(self.config.get('mysql', {}).get('host', 'localhost'))
        self.entry_port.set(str(self.config.get('mysql', {}).get('port', 3306)))
        self.entry_user.set(self.config.get('mysql', {}).get('user', 'root'))
        self.entry_pass.set(self.config.get('mysql', {}).get('password', ''))
        self.entry_db.set(self.config.get('mysql', {}).get('database', 'prometeo_marc'))

        self.var_item_type_bib.set(self.config.get('item_type_bib', 'LIBR0'))
        self.var_item_type_item.set(self.config.get('item_type_item', 'LIBR0'))
        self.var_homebranch.set(self.config.get('homebranch', 'ITT'))
        self.var_holdingbranch.set(self.config.get('holdingbranch', 'ITT'))

        # Inicializar mapeos por defecto si no hay configuracion guardada
        branch_map = self.config.get('koha_branch_mapping', {})
        status_map = self.config.get('item_status_mapping', {})

        if not branch_map:
            branch_map = {}
        if not status_map:
            status_map = {
                '0': 'available',
                '1': 'available',
                '2': 'checkedout',
                '3': 'available',
            }

        self.txt_mapeo.delete('1.0', tk.END)
        self.txt_mapeo.insert('1.0', json.dumps(branch_map, indent=2, ensure_ascii=False))

        self.txt_status.delete('1.0', tk.END)
        self.txt_status.insert('1.0', json.dumps(status_map, indent=2, ensure_ascii=False))

    def _guardar_config(self):
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
            'koha_branch_mapping': self._parsear_json_texto(self.txt_mapeo.get('1.0', tk.END), {}),
            'item_status_mapping': self._parsear_json_texto(self.txt_status.get('1.0', tk.END), {}),
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
        # Interpreta los mapeos escritos en las cajas de texto como JSON.
        texto = texto.strip()
        if not texto:
            return default
        try:
            return json.loads(texto)
        except Exception:
            return default

    def log(self, mensaje: str):
        # Anade un mensaje al final del registro visible y desplaza la vista.
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

    def _seleccionar_access(self):
        # Abre el selector de archivos filtrado para copias Access.
        path = filedialog.askopenfilename(
            title='Seleccionar base de datos Access aprobada',
            filetypes=[('Bases de datos Access', '*.mdb *.accdb'), ('Todos los archivos', '*.*')],
        )
        if path:
            self.var_access_path.set(path)

    def _actualizar_info_access(self):
        # Actualiza la etiqueta con el nombre y tamano actual de la ruta elegida.
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
            text=f'Archivo: {nombre} | Tamaño: {detalle_tamano}'
        )

    def _validar_archivo_access(self, path: str) -> List[str]:
        # Abre Access solo para validar; cierra la conexion incluso ante errores.
        reader = AccessReader(path)
        try:
            return reader.validar_archivo()
        finally:
            reader.close()

    def _probar_access(self):
        # Comprueba la copia y muestra el total de fichas si la prueba pasa.
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
        # Comprueba los datos visibles de conexion y verifica las tablas destino.
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
                self.mysql_writer = writer  # mantener conexión abierta para exportar
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
                        self.mysql_writer = writer  # mantener conexión abierta
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

    def _obtener_stats_mysql(self, config: Dict) -> Dict:
        # Consulta estadisticas del destino para mostrar el total migrado.
        try:
            writer = MySQLWriter(config)
            stats = writer.obtener_estadisticas()
            writer.close()
            return stats
        except Exception:
            return {'total_registros': 0, 'total_ejemplares': 0, 'por_estado': {}}

    def _iniciar_migracion(self):
        # Valida el archivo y la configuracion antes de permitir el procesamiento.
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
            # Un error de formato o estructura detiene el flujo antes de crear el hilo.
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

        branch_mapping = self._parsear_json_texto(self.txt_mapeo.get('1.0', tk.END), {})
        status_mapping = self._parsear_json_texto(self.txt_status.get('1.0', tk.END), {})
        # Mapeo automático por defecto si no hay configuración
        if not status_mapping:
            status_mapping = {
                '0': 'available',
                '1': 'available',
                '2': 'checkedout',
                '3': 'available',
            }
        if not branch_mapping:
            # Se usa el código de Access directamente como código de sucursal en Koha
            branch_mapping = {}

        item_type_bib = self.entry_item_type_bib.get() or 'LIBR0'
        item_type_item = self.entry_item_type_item.get() or 'LIBR0'
        homebranch = self.entry_homebranch.get() or 'ITT'
        holdingbranch = self.entry_holdingbranch.get() or 'ITT'

        # Actualizar el conversor con los valores actuales
        self.marc_converter = MarcConverter(
            item_type_bib=item_type_bib,
            item_type_item=item_type_item,
            homebranch=homebranch,
            holdingbranch=holdingbranch,
        )

        try:
            self.historial_lotes.actualizar(lote.id, estado='en_proceso', etapa='conexion',
                total_objetivo=min(total, limite) if limite else total, destino=self._destino_actual(),
                evento='Migración iniciada. Conectando al destino MySQL.')
        except (OSError, ValueError) as exc:
            messagebox.showerror('No se pudo registrar el lote', str(exc))
            return
        self.migracion_en_curso = True
        self._detencion_solicitada.clear()
        # Deshabilita el boton durante el trabajo y deja el progreso listo.
        self.btn_ejecutar.config(state='disabled')
        self.progress['value'] = 0
        self.lbl_estado.config(text='Iniciando...')
        self.btn_exportar.configure(state='disabled')
        for frame in (self.frame_conexion, self.frame_config):
            self.notebook.tab(frame, state='disabled')
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
        # El trabajo real informa al historial; Tkinter se actualiza desde su hilo.
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
            # Una conexión propia evita compartir el destino entre el hilo y la UI.
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
                        record = self.marc_converter.ficha_a_record(ficha, ejemplares,
                            branch_mapping=branch_mapping, status_mapping=status_mapping)
                        marcxml = self.marc_converter.record_a_marcxml(record)
                        iso2709 = self.marc_converter.record_a_iso2709(record)
                        id_registro = writer.insertar_registro_marc(id_ficha, str(id_ficha), marcxml, iso2709)
                        for ej in ejemplares:
                            biblioteca = ej.get('Biblioteca')
                            bc = str(biblioteca) if biblioteca is not None else ''
                            branch_code = branch_mapping.get(bc, bc) if branch_mapping else bc
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
            estado = 'con_incidencias' if cont_err else 'concluido'
            guardar_avance(estado=estado, etapa='revision' if cont_err else 'finalizado',
                           evento=f'Ejecución terminada. Correctos: {cont_ok}; omitidos: {cont_omitidos}; errores: {cont_err}.')
            self.log(f'Lote {lote_id} finalizado. OK: {cont_ok}, omitidos: {cont_omitidos}, errores: {cont_err}.')
            self._publicar_ui(self._finalizar_migracion)
            self._publicar_ui(messagebox.showwarning if cont_err else messagebox.showinfo,
                'Lote con incidencias' if cont_err else 'Lote concluido',
                f'Correctos: {cont_ok}\nOmitidos: {cont_omitidos}\nErrores: {cont_err}\nEjemplares: {cont_ejemplares}')
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
        self.lbl_stats.config(text=f'Correctos: {lote.correctos} | Omitidos: {lote.omitidos} | Errores: {lote.errores} | Ejemplares: {lote.ejemplares}')
        self._actualizar_panel()

    def _finalizar_migracion(self):
        # Restablece el estado de la interfaz al terminar o fallar el proceso.
        self.migracion_en_curso = False
        for frame in (self.frame_conexion, self.frame_config):
            self.notebook.tab(frame, state='normal')
        self._actualizar_panel()

    def _exportar_marcxml(self, lote_id=None):
        # Reutiliza la exportación existente, acotada a las fichas del lote.
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
            # Parámetros SQL, nunca interpolar los identificadores de las fichas.
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
