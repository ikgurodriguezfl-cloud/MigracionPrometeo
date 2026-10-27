"""Interfaz grafica de la migracion Prometeo Access -> MySQL MARC21 -> Koha."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import threading
from typing import Optional, Dict, Any

from access_reader import AccessReader
from marc_converter import MarcConverter
from mysql_writer import MySQLWriter


class MigracionApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Prometeo Migrator - Access a MARC21 (Koha)')
        self.root.geometry('900x650')
        self.root.minsize(800, 600)

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

        self._crear_interfaz()
        self._cargar_config_en_ui()

    def _crear_interfaz(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        self.frame_conexion = ttk.Frame(notebook)
        self.frame_migracion = ttk.Frame(notebook)
        self.frame_config = ttk.Frame(notebook)
        self.frame_log = ttk.Frame(notebook)

        notebook.add(self.frame_conexion, text='1. Conexiones')
        notebook.add(self.frame_migracion, text='2. Migracion')
        notebook.add(self.frame_config, text='3. Configuracion')
        notebook.add(self.frame_log, text='4. Log')

        self._crear_pestana_conexion()
        self._crear_pestana_migracion()
        self._crear_pestana_config()
        self._crear_pestana_log()

    def _campo(self, parent, fila, col, texto, valor, ancho=30, show=None):
        ttk.Label(parent, text=texto).grid(row=fila, column=col*2, sticky='e', padx=5, pady=2)
        var = tk.StringVar(value=valor)
        entry = ttk.Entry(parent, textvariable=var, width=ancho, show=show)
        entry.grid(row=fila, column=col*2+1, sticky='w', padx=5, pady=2)
        return var

    def _crear_pestana_conexion(self):
        f = self.frame_conexion

        lbl_access = ttk.LabelFrame(f, text='Base de datos Access (.mdb)')
        lbl_access.pack(fill='x', padx=10, pady=5)

        self.var_access_path = tk.StringVar(value=self.config.get('access', {}).get('path', ''))
        ttk.Entry(lbl_access, textvariable=self.var_access_path, width=80).pack(side='left', padx=5, pady=5, fill='x', expand=True)
        ttk.Button(lbl_access, text='Examinar...', command=self._seleccionar_access).pack(side='left', padx=5)
        ttk.Button(lbl_access, text='Probar conexion', command=self._probar_access).pack(side='left', padx=5)

        self.lbl_conteo_access = ttk.Label(lbl_access, text='Registros: --')
        self.lbl_conteo_access.pack(side='right', padx=5, pady=5)

        lbl_mysql = ttk.LabelFrame(f, text='Base de datos MySQL (destino MARC21)')
        lbl_mysql.pack(fill='x', padx=10, pady=5)

        grid = ttk.Frame(lbl_mysql)
        grid.pack(fill='x', padx=5, pady=5)

        self.entry_host = self._campo(grid, 0, 0, 'Host:', self.config.get('mysql', {}).get('host', 'localhost'))
        self.entry_port = self._campo(grid, 0, 2, 'Puerto:', str(self.config.get('mysql', {}).get('port', 3306)), ancho=8)
        self.entry_user = self._campo(grid, 1, 0, 'Usuario:', self.config.get('mysql', {}).get('user', 'root'))
        self.entry_pass = self._campo(grid, 1, 2, 'Contrasena:', self.config.get('mysql', {}).get('password', ''), show='*')
        self.entry_db = self._campo(grid, 2, 0, 'Base de datos:', self.config.get('mysql', {}).get('database', 'prometeo_marc'))

        ttk.Button(lbl_mysql, text='Probar conexion MySQL', command=self._probar_mysql).pack(pady=5)
        self.lbl_conteo_mysql = ttk.Label(lbl_mysql, text='Registros migrados: --')
        self.lbl_conteo_mysql.pack(pady=2)

    def _crear_pestana_migracion(self):
        f = self.frame_migracion

        lbl_opts = ttk.LabelFrame(f, text='Opciones de migracion')
        lbl_opts.pack(fill='x', padx=10, pady=5)

        self.var_limite = tk.StringVar(value='0')
        ttk.Label(lbl_opts, text='Limite de registros (0 = todos):').pack(side='left', padx=5, pady=5)
        ttk.Entry(lbl_opts, textvariable=self.var_limite, width=10).pack(side='left', padx=5, pady=5)

        self.var_saltar_existentes = tk.BooleanVar(value=True)
        ttk.Checkbutton(lbl_opts, text='Saltar registros ya migrados',
                        variable=self.var_saltar_existentes).pack(side='left', padx=15, pady=5)

        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill='x', padx=10, pady=10)
        self.btn_ejecutar = ttk.Button(btn_frame, text='Ejecutar migracion', command=self._iniciar_migracion)
        self.btn_ejecutar.pack(side='left', padx=5)
        ttk.Button(btn_frame, text='Exportar MARCXML a archivo', command=self._exportar_marcxml).pack(side='left', padx=5)

        lbl_prog = ttk.LabelFrame(f, text='Progreso')
        lbl_prog.pack(fill='both', expand=True, padx=10, pady=5)

        self.progress = ttk.Progressbar(lbl_prog, orient='horizontal', mode='determinate')
        self.progress.pack(fill='x', padx=10, pady=5)

        self.lbl_estado = ttk.Label(lbl_prog, text='Listo.')
        self.lbl_estado.pack(pady=2)

        self.lbl_stats = ttk.Label(lbl_prog, text='Registros: 0 | Ejemplares: 0 | Errores: 0')
        self.lbl_stats.pack(pady=2)

    def _crear_pestana_config(self):
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
        self.txt_status = tk.Text(lbl_status, width=60, height=6)
        self.txt_status.pack(fill='x', padx=5, pady=5)
        ejemplo_status = json.dumps(self.config.get('item_status_mapping', {}), indent=2, ensure_ascii=False)
        self.txt_status.insert('1.0', ejemplo_status)

        lbl_tipos = ttk.LabelFrame(f, text='Valores por defecto para Koha (942 y 952)')
        lbl_tipos.pack(fill='x', padx=10, pady=5)

        grid_tipos = ttk.Frame(lbl_tipos)
        grid_tipos.pack(fill='x', padx=5, pady=5)

        self.entry_item_type_bib = self._campo(grid_tipos, 0, 0, '942$c - Tipo ítem bibliográfico:', self.var_item_type_bib.get(), ancho=12)
        self.entry_item_type_item = self._campo(grid_tipos, 0, 2, '952$y - Tipo ítem ejemplar:', self.var_item_type_item.get(), ancho=12)
        self.entry_homebranch = self._campo(grid_tipos, 1, 0, '952$a - Homebranch:', self.var_homebranch.get(), ancho=12)
        self.entry_holdingbranch = self._campo(grid_tipos, 1, 2, '952$b - Holdingbranch:', self.var_holdingbranch.get(), ancho=12)

        ttk.Button(f, text='Guardar configuracion', command=self._guardar_config).pack(pady=10)

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
        texto = texto.strip()
        if not texto:
            return default
        try:
            return json.loads(texto)
        except Exception:
            return default

    def log(self, mensaje: str):
        self.txt_log.insert(tk.END, mensaje + '\n')
        self.txt_log.see(tk.END)
        self.root.update_idletasks()

    def _seleccionar_access(self):
        path = filedialog.askopenfilename(
            title='Seleccionar base de datos Access',
            filetypes=[('Access 2003', '*.mdb'), ('Todos los archivos', '*.*')],
        )
        if path:
            self.var_access_path.set(path)

    def _probar_access(self):
        path = self.var_access_path.get().strip()
        if not path:
            messagebox.showwarning('Atencion', 'Seleccione primero el archivo .mdb')
            return
        try:
            reader = AccessReader(path)
            if reader.test_connection():
                total = reader.contar_fichas()
                reader.close()
                self.lbl_conteo_access.config(text='Registros FICHAS: ' + str(total))
                self.log('[OK] Conexion Access exitosa. ' + str(total) + ' fichas encontradas.')
                messagebox.showinfo('Exito', 'Conexion Access exitosa.\n' + str(total) + ' registros en FICHAS.')
            else:
                raise Exception('No se pudo conectar.')
        except Exception as e:
            self.log('[ERROR] Access: ' + str(e))
            messagebox.showerror('Error', 'No se pudo conectar a Access:\n' + str(e))

    def _probar_mysql(self):
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
        try:
            writer = MySQLWriter(config)
            stats = writer.obtener_estadisticas()
            writer.close()
            return stats
        except Exception:
            return {'total_registros': 0, 'total_ejemplares': 0, 'por_estado': {}}

    def _iniciar_migracion(self):
        if self.migracion_en_curso:
            messagebox.showwarning('Atencion', 'Ya hay una migracion en curso.')
            return

        path_access = self.var_access_path.get().strip()
        if not path_access or not os.path.exists(path_access):
            messagebox.showerror('Error', 'Seleccione un archivo .mdb valido.')
            return

        config_mysql = {
            'host': self.entry_host.get(),
            'port': int(self.entry_port.get() or 3306),
            'user': self.entry_user.get(),
            'password': self.entry_pass.get(),
            'database': self.entry_db.get(),
            'charset': 'utf8mb4',
        }

        limite_str = self.var_limite.get().strip()
        limite = int(limite_str) if limite_str.isdigit() else 0
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

        self.migracion_en_curso = True
        self.btn_ejecutar.config(state='disabled')
        self.progress['value'] = 0
        self.lbl_estado.config(text='Iniciando...')

        hilo = threading.Thread(
            target=self._ejecutar_migracion,
            args=(path_access, config_mysql, limite, saltar, branch_mapping, status_mapping),
            daemon=True,
        )
        hilo.start()

    def _ejecutar_migracion(self, path_access, config_mysql, limite, saltar,
                            branch_mapping, status_mapping):
        try:
            reader = AccessReader(path_access)

            # Usar conexión existente si hay, si no crear una nueva y guardarla
            if self.mysql_writer is None:
                writer = MySQLWriter(config_mysql)
                writer.connect()
                writer.crear_tablas()
                self.mysql_writer = writer
            else:
                writer = self.mysql_writer

            total_fichas = reader.contar_fichas()
            if limite > 0:
                total_fichas = min(total_fichas, limite)
            self.log('Total fichas a procesar: ' + str(total_fichas))

            fichas = reader.leer_fichas(limite=limite if limite > 0 else None)

            cont_ok = 0
            cont_err = 0
            cont_ejemplares = 0

            for idx, ficha in enumerate(fichas, start=1):
                id_ficha = int(ficha['Ficha_No'])

                if saltar and writer.registrar_existe(id_ficha):
                    continue

                try:
                    ejemplares = reader.leer_ejemplares_por_ficha([id_ficha]).get(id_ficha, [])
                    record = self.marc_converter.ficha_a_record(
                        ficha, ejemplares,
                        branch_mapping=branch_mapping,
                        status_mapping=status_mapping,
                    )
                    marcxml = self.marc_converter.record_a_marcxml(record)
                    iso2709 = self.marc_converter.record_a_iso2709(record)

                    id_registro = writer.insertar_registro_marc(
                        id_ficha, str(id_ficha), marcxml, iso2709
                    )

                    for ej in ejemplares:
                        biblioteca = ej.get('Biblioteca')
                        branch_code = ''
                        if biblioteca is not None:
                            bc = str(biblioteca)
                            branch_code = branch_mapping.get(bc, bc) if branch_mapping else bc
                        signatura = ficha.get('Clasificacion')
                        writer.insertar_ejemplar(
                            id_registro, id_ficha, ej, branch_code, signatura=signatura
                        )
                        cont_ejemplares += 1

                    cont_ok += 1

                    if idx % 50 == 0 or idx == total_fichas:
                        pct = int((idx / total_fichas) * 100)
                        self.root.after(0, self.progress.__setitem__, 'value', pct)
                        self.root.after(0, self.lbl_estado.config, {'text': 'Procesando ' + str(idx) + '/' + str(total_fichas) + '...'})
                        self.root.after(0, self.lbl_stats.config, {
                            'text': 'Registros: ' + str(cont_ok) + ' | Ejemplares: ' + str(cont_ejemplares) + ' | Errores: ' + str(cont_err)
                        })

                except Exception as e:
                    cont_err += 1
                    self.log('[ERROR] Ficha ' + str(id_ficha) + ': ' + str(e))
                    try:
                        writer.insertar_log('ERROR', str(e), id_ficha=id_ficha)
                    except Exception:
                        pass

            reader.close()
            # No cerrar writer para permitir exportar despues

            self.root.after(0, self.progress.__setitem__, 'value', 100)
            self.root.after(0, self.lbl_estado.config, {'text': 'Migracion completada.'})
            self.root.after(0, self.lbl_stats.config, {
                'text': 'Registros: ' + str(cont_ok) + ' | Ejemplares: ' + str(cont_ejemplares) + ' | Errores: ' + str(cont_err)
            })
            self.log('Migracion finalizada. OK: ' + str(cont_ok) + ', Errores: ' + str(cont_err) + ', Ejemplares: ' + str(cont_ejemplares))
            self.root.after(0, messagebox.showinfo, 'Completado',
                          'Migracion terminada.\nOK: ' + str(cont_ok) + '\nErrores: ' + str(cont_err) + '\nEjemplares: ' + str(cont_ejemplares))

        except Exception as e:
            self.log('[ERROR FATAL] ' + str(e))
            self.root.after(0, messagebox.showerror, 'Error fatal', str(e))
        finally:
            self.root.after(0, self._finalizar_migracion)

    def _finalizar_migracion(self):
        self.migracion_en_curso = False
        self.btn_ejecutar.config(state='normal')

    def _exportar_marcxml(self):
        if not self.mysql_writer:
            # Intentar crear conexión con los valores actuales de la UI
            try:
                config = {
                    'host': self.entry_host.get(),
                    'port': int(self.entry_port.get() or 3306),
                    'user': self.entry_user.get(),
                    'password': self.entry_pass.get(),
                    'database': self.entry_db.get(),
                    'charset': 'utf8mb4',
                }
                self.mysql_writer = MySQLWriter(config)
                self.mysql_writer.connect()
            except Exception as e:
                messagebox.showwarning('Atencion', 'Configure y conecte MySQL primero.\n' + str(e))
                return

        path = filedialog.asksaveasfilename(
            title='Exportar registros MARCXML',
            defaultextension='.xml',
            filetypes=[('MARCXML', '*.xml'), ('Todos', '*.*')],
        )
        if not path:
            return
        try:
            with self.mysql_writer.conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) AS total FROM registros_marc')
                total = cur.fetchone()['total']

            with self.mysql_writer.conn.cursor() as cur:
                cur.execute('SELECT marca_marcxml FROM registros_marc')
                filas = cur.fetchall()

            with open(path, 'w', encoding='utf-8') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<collection xmlns="http://www.loc.gov/MARC21/slim">\n')
                for fila in filas:
                    # La marca_marcxml ya viene con su propia envoltura <collection>...
                    # Extraemos solo el contenido del <record> para meterlo en nuestro collection padre
                    xml = fila['marca_marcxml']
                    # Buscamos el contenido entre <record> y </record>
                    start = xml.find('<record>')
                    end = xml.find('</record>')
                    if start != -1 and end != -1:
                        record_xml = xml[start:end + len('</record>')]
                        f.write(record_xml + '\n')
                f.write('</collection>\n')

            messagebox.showinfo('Exito', 'Exportados ' + str(len(filas)) + ' registros a ' + path)
        except Exception as e:
            messagebox.showerror('Error', str(e))
