"""Vista de resultados de importación y rechazos de Koha (Sprint 5)."""
import csv
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from koha_importer import KohaResponseParser
from mysql_writer import MySQLWriter
from ui_kit import (
    SUPERFICIE, TEXTO, TEXTO_MUTADO,
    EXITO, EXITO_SUAVE, ERROR, ERROR_SUAVE, ADVERTENCIA,
    FUENTE, TAM_METRICA_VALOR, TAM_METRICA_ETIQUETA,
    ESPACIO_XS, ESPACIO_S, ESPACIO_M, ESPACIO_L, ESPACIO_XL,
    encabezado_pagina, seccion_tarjeta, tarjeta,
)


class VistaResultadosKoha(ttk.Frame):
    def __init__(self, parent, get_mysql_config, get_usuario,
                 get_lote_activo=None, get_lote_obj=None,
                 get_lista_lotes=None, on_registrar_evento=None):
        super().__init__(parent, style='App.TFrame')
        self.get_mysql_config = get_mysql_config
        self.get_usuario = get_usuario
        self.get_lote_activo = get_lote_activo
        self.get_lote_obj = get_lote_obj
        self.get_lista_lotes = get_lista_lotes
        self.on_registrar_evento = on_registrar_evento

        self.var_lote = tk.StringVar(value='')
        self.var_filtro = tk.StringVar(value='TODOS')
        self.var_busqueda = tk.StringVar()

        self.configure(padding=(ESPACIO_L, ESPACIO_M, ESPACIO_L, ESPACIO_XL))
        self._construir_ui()

    def _construir_ui(self):
        encabezado_pagina(
            self,
            'Resultados de importación Koha',
            'Selecciona o escribe un lote, importa el reporte devuelto por Koha y descarga el informe conciliado.',
            icono='check',
        )

        # --- BARRA DE SELECCIÓN E IMPORTACIÓN REAL ---
        card_lote = seccion_tarjeta(self, 'LOTE Y RESPUESTA DE KOHA')
        card_lote.pack(fill='x', pady=(0, ESPACIO_M))

        fila_lote = ttk.Frame(card_lote, style='Tarjeta.TFrame')
        fila_lote.pack(fill='x')

        ttk.Label(fila_lote, text='Seleccionar o escribir lote', style='Field.TLabel').pack(
            side='left', padx=(0, ESPACIO_S)
        )
        self.combo_lotes = ttk.Combobox(
            fila_lote,
            textvariable=self.var_lote,
            width=26,
            state='normal',
            postcommand=self._actualizar_opciones_lotes,
        )
        self.combo_lotes.pack(side='left', padx=(0, ESPACIO_S))
        self.combo_lotes.bind('<<ComboboxSelected>>', lambda _e: self.cargar_datos(silencioso=True))
        self.combo_lotes.bind('<Return>', lambda _e: self.cargar_datos())

        ttk.Button(
            fila_lote, text='Consultar', style='Secondary.TButton',
            command=self.cargar_datos,
        ).pack(side='left', padx=(0, ESPACIO_S))

        ttk.Button(
            fila_lote, text='Importar reporte Koha…', style='Primary.TButton',
            command=self.importar_archivo_koha,
        ).pack(side='left', padx=(0, ESPACIO_S))

        ttk.Button(
            fila_lote, text='Generar prueba con datos reales', style='Quiet.TButton',
            command=self.ejecutar_prueba_con_datos_reales,
        ).pack(side='left')

        ttk.Button(
            fila_lote, text='Descargar reporte de calidad', style='Secondary.TButton',
            command=self.exportar_reporte_lote,
        ).pack(side='right')

        # --- TARJETAS DE CONCILIACIÓN ---
        grid_metricas = ttk.Frame(self, style='App.TFrame')
        grid_metricas.pack(fill='x', pady=(0, ESPACIO_M))
        for i in range(4):
            grid_metricas.columnconfigure(i, weight=1, uniform='kpi_koha')

        self.lbl_enviados = self._crear_kpi(grid_metricas, 0, 'TOTAL ENVIADOS (APROBADOS)', '0', TEXTO)
        self.lbl_aceptados = self._crear_kpi(grid_metricas, 1, 'ACEPTADOS POR KOHA', '0', EXITO)
        self.lbl_rechazados = self._crear_kpi(grid_metricas, 2, 'RECHAZADOS POR KOHA', '0', ERROR)
        self.lbl_conciliacion = self._crear_kpi(grid_metricas, 3, 'ESTADO DE CONCILIACIÓN', 'PENDIENTE', TEXTO_MUTADO)

        # --- TABLA DE DETALLE Y BÚSQUEDA ---
        card_tabla = seccion_tarjeta(self, 'DETALLE DE REGISTROS PROCESADOS POR KOHA')
        card_tabla.pack(fill='both', expand=True)

        barra_filtros = ttk.Frame(card_tabla, style='Tarjeta.TFrame')
        barra_filtros.pack(fill='x', pady=(0, ESPACIO_M))

        ttk.Label(barra_filtros, text='Filtrar por estado', style='Field.TLabel').pack(
            side='left', padx=(0, ESPACIO_S)
        )
        combo = ttk.Combobox(
            barra_filtros,
            textvariable=self.var_filtro,
            values=('TODOS', 'ACEPTADO', 'RECHAZADO'),
            state='readonly',
            width=15,
        )
        combo.pack(side='left', padx=(0, ESPACIO_L))
        combo.bind('<<ComboboxSelected>>', lambda _e: self.filtrar_tabla())

        ttk.Label(barra_filtros, text='Localizar registro (ID Ficha, 001 o causa)', style='Field.TLabel').pack(
            side='left', padx=(0, ESPACIO_S)
        )
        entry_buscar = ttk.Entry(barra_filtros, textvariable=self.var_busqueda, width=36)
        entry_buscar.pack(side='left', fill='x', expand=True)
        entry_buscar.bind('<KeyRelease>', lambda _e: self.filtrar_tabla())

        tabla_contenedor = ttk.Frame(card_tabla, style='Tarjeta.TFrame')
        tabla_contenedor.pack(fill='both', expand=True)
        tabla_contenedor.columnconfigure(0, weight=1)
        tabla_contenedor.rowconfigure(0, weight=1)

        columnas = ('id_ficha', 'id_control', 'estado_marc', 'resultado', 'biblionumber', 'causa')
        self.tree = ttk.Treeview(
            tabla_contenedor, columns=columnas, show='headings', style='Lotes.Treeview'
        )
        self.tree.heading('id_ficha', text='ID Ficha (Access)')
        self.tree.heading('id_control', text='Control MARC (001)')
        self.tree.heading('estado_marc', text='Estado en MySQL')
        self.tree.heading('resultado', text='Resultado Koha')
        self.tree.heading('biblionumber', text='Biblionumber Koha')
        self.tree.heading('causa', text='Causa de rechazo / Detalle')

        self.tree.column('id_ficha', width=120, anchor='center')
        self.tree.column('id_control', width=140, anchor='center')
        self.tree.column('estado_marc', width=130, anchor='center')
        self.tree.column('resultado', width=130, anchor='center')
        self.tree.column('biblionumber', width=140, anchor='center')
        self.tree.column('causa', width=400, anchor='w')

        self.tree.tag_configure('ACEPTADO', background=EXITO_SUAVE, foreground=EXITO)
        self.tree.tag_configure('RECHAZADO', background=ERROR_SUAVE, foreground=ERROR)

        scroll_y = ttk.Scrollbar(tabla_contenedor, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll_y.grid(row=0, column=1, sticky='ns')

    def _crear_kpi(self, parent, col, titulo, valor_inicial, color):
        padx = (0, ESPACIO_S) if col < 3 else (0, 0)
        card = tarjeta(parent, padding=(ESPACIO_M, ESPACIO_M))
        card.grid(row=0, column=col, sticky='nsew', padx=padx)

        ttk.Label(
            card, text=titulo, background=SUPERFICIE, foreground=TEXTO_MUTADO,
            font=(FUENTE, TAM_METRICA_ETIQUETA, 'bold')
        ).pack(anchor='w')

        lbl_valor = ttk.Label(
            card, text=valor_inicial, background=SUPERFICIE, foreground=color,
            font=(FUENTE, TAM_METRICA_VALOR, 'bold')
        )
        lbl_valor.pack(anchor='w', pady=(ESPACIO_XS, 0))
        return lbl_valor

    def _actualizar_opciones_lotes(self):
        """Combina los lotes del historial local y los ya importados en MySQL."""
        opciones = []
        vistos = set()

        # 1. Lotes del historial de la aplicación
        if self.get_lista_lotes:
            try:
                for item in self.get_lista_lotes():
                    lid = item.id if hasattr(item, 'id') else str(item)
                    if lid and lid not in vistos:
                        opciones.append(lid)
                        vistos.add(lid)
            except Exception:
                pass

        # 2. Lotes con resultados guardados en MySQL (importaciones_koha)
        writer = None
        try:
            writer = self._conectar_writer()
            for lid in writer.listar_lotes_koha():
                if lid and lid not in vistos:
                    opciones.append(lid)
                    vistos.add(lid)
        except Exception:
            pass
        finally:
            if writer:
                writer.close()

        self.combo_lotes['values'] = opciones
        return opciones

    def sincronizar_lote_activo(self):
        opciones = self._actualizar_opciones_lotes()
        lote_id = self.get_lote_activo() if self.get_lote_activo else None

        if lote_id:
            self.var_lote.set(lote_id)
            self.cargar_datos(silencioso=True)
        elif not self.var_lote.get().strip() and opciones:
            self.var_lote.set(opciones[0])
            self.cargar_datos(silencioso=True)

    def _conectar_writer(self):
        cfg = self.get_mysql_config()
        if not cfg.get('host') or not cfg.get('database'):
            raise ValueError('Configura y valida primero la conexión a MySQL en la sección Conexión.')
        writer = MySQLWriter(cfg)
        writer.connect()
        writer.crear_tablas()
        return writer

    def importar_archivo_koha(self):
        lote_id = self.var_lote.get().strip()
        if not lote_id:
            messagebox.showwarning('Lote requerido', 'Selecciona o escribe primero el identificador del lote.')
            return

        ruta = filedialog.askopenfilename(
            title='Seleccionar reporte o log de importación de Koha',
            filetypes=[
                ('Reportes Koha (CSV, TSV, JSON, Log)', '*.csv *.tsv *.json *.log *.txt'),
                ('Todos los archivos', '*.*'),
            ],
        )
        if not ruta:
            return

        writer = None
        try:
            registros, aceptados, rechazados = KohaResponseParser.parsear_archivo(ruta)
            lote_obj = self.get_lote_obj(lote_id) if self.get_lote_obj else None
            fichas_lote = lote_obj.fichas_correctas if lote_obj else None

            writer = self._conectar_writer()
            res = writer.registrar_resultado_importacion_koha(
                lote_id=lote_id,
                usuario=self.get_usuario(),
                resultados_registros=registros,
                conteo_koha_aceptados=aceptados,
                conteo_koha_rechazados=rechazados,
                fichas_enviadas_lote=fichas_lote,
            )
            if self.on_registrar_evento:
                self.on_registrar_evento(
                    lote_id,
                    f"Importación Koha conciliada: {res['aceptados']} aceptados, "
                    f"{res['rechazados']} rechazados ({res['estado_conciliacion']})."
                )
            self._actualizar_opciones_lotes()
            self.cargar_datos(silencioso=True)

            if res['estado_conciliacion'] == 'CONCILIADO':
                messagebox.showinfo(
                    'Importación Koha conciliada',
                    f"Lote {lote_id} conciliado correctamente:\n"
                    f"• Enviados: {res['enviados']}\n"
                    f"• Aceptados por Koha: {res['aceptados']}\n"
                    f"• Rechazados por Koha: {res['rechazados']}"
                )
            else:
                messagebox.showwarning(
                    'Discrepancia detectada en conciliación',
                    f"Los conteos de Koha no coinciden con el total enviado del lote {lote_id}:\n"
                    f"• Enviados esperados: {res['enviados']}\n"
                    f"• Reportados por Koha: {res['aceptados'] + res['rechazados']} "
                    f"({res['aceptados']} aceptados + {res['rechazados']} rechazados)"
                )
        except Exception as exc:
            messagebox.showerror('Error al procesar respuesta de Koha', str(exc))
        finally:
            if writer:
                writer.close()

    def ejecutar_prueba_con_datos_reales(self):
        lote_id = self.var_lote.get().strip() or 'LOTE-PRUEBA-KOHA'
        self.var_lote.set(lote_id)
        writer = None
        try:
            writer = self._conectar_writer()
            with writer.conn.cursor() as cur:
                cur.execute(
                    "SELECT id_ficha_acceso, id_control FROM registros_marc "
                    "ORDER BY id_ficha_acceso ASC LIMIT 10"
                )
                filas = cur.fetchall()

            if not filas:
                messagebox.showinfo(
                    'Sin registros migrados',
                    'Primero ejecuta una migración de Access a MySQL para tener registros reales.'
                )
                return

            resultados = []
            aceptados = 0
            rechazados = 0
            for idx, fila in enumerate(filas, start=1):
                if idx % 4 == 0:
                    rechazados += 1
                    resultados.append({
                        'id_ficha_acceso': fila['id_ficha_acceso'],
                        'id_control': fila['id_control'] or str(fila['id_ficha_acceso']),
                        'resultado': 'RECHAZADO',
                        'causa_rechazo': 'Código de barras (952$p) duplicado en sucursal destino Koha.',
                    })
                else:
                    aceptados += 1
                    resultados.append({
                        'id_ficha_acceso': fila['id_ficha_acceso'],
                        'id_control': fila['id_control'] or str(fila['id_ficha_acceso']),
                        'resultado': 'ACEPTADO',
                        'biblionumber_koha': 10000 + idx,
                    })

            res = writer.registrar_resultado_importacion_koha(
                lote_id=lote_id,
                usuario=self.get_usuario(),
                resultados_registros=resultados,
                conteo_koha_aceptados=aceptados,
                conteo_koha_rechazados=rechazados,
            )
            self._actualizar_opciones_lotes()
            self.cargar_datos(silencioso=True)
            messagebox.showinfo(
                'Conciliación de prueba completada',
                f"Se procesaron {res['enviados']} registros reales de MySQL:\n"
                f"• Aceptados: {res['aceptados']}\n"
                f"• Rechazados: {res['rechazados']}\n"
                f"• Estado: {res['estado_conciliacion']}"
            )
        except Exception as exc:
            messagebox.showerror('Error en prueba', str(exc))
        finally:
            if writer:
                writer.close()

    def cargar_datos(self, silencioso=False):
        lote = self.var_lote.get().strip()
        if not lote:
            if not silencioso:
                messagebox.showwarning('Lote requerido', 'Selecciona o ingresa el identificador del lote a consultar.')
            return
        writer = None
        try:
            writer = self._conectar_writer()
            resumen = writer.obtener_resumen_koha(lote)
            if not resumen:
                self.lbl_enviados.configure(text='0')
                self.lbl_aceptados.configure(text='0')
                self.lbl_rechazados.configure(text='0')
                self.lbl_conciliacion.configure(text='SIN IMPORTAR', foreground=ADVERTENCIA)
                self.tree.delete(*self.tree.get_children())
                if not silencioso:
                    messagebox.showinfo(
                        'Sin resultados Koha',
                        f'El lote {lote} aún no tiene resultados de importación registrados.'
                    )
                return

            self.lbl_enviados.configure(text=f"{resumen['total_enviados']:,}")
            self.lbl_aceptados.configure(text=f"{resumen['total_aceptados']:,}")
            self.lbl_rechazados.configure(text=f"{resumen['total_rechazados']:,}")

            es_ok = resumen['estado_conciliacion'] == 'CONCILIADO'
            self.lbl_conciliacion.configure(
                text=resumen['estado_conciliacion'],
                foreground=EXITO if es_ok else ERROR,
            )
            self.filtrar_tabla(writer)
        except Exception as exc:
            if not silencioso:
                messagebox.showerror('Error al consultar Koha', str(exc))
        finally:
            if writer:
                writer.close()

    def filtrar_tabla(self, writer_existente=None):
        lote = self.var_lote.get().strip()
        if not lote:
            return
        writer = writer_existente
        cerrar_al_final = False
        try:
            if writer is None:
                writer = self._conectar_writer()
                cerrar_al_final = True
            registros = writer.listar_detalle_koha(
                lote,
                filtro_estado=self.var_filtro.get(),
                busqueda=self.var_busqueda.get(),
            )
            self.tree.delete(*self.tree.get_children())
            for reg in registros:
                estado = reg['resultado']
                biblio = reg['biblionumber_koha'] if reg['biblionumber_koha'] else '—'
                causa = (
                    reg['causa_rechazo']
                    if reg['causa_rechazo']
                    else 'Registro bibliográfico y ejemplares incorporados en Koha.'
                )
                self.tree.insert(
                    '', 'end',
                    values=(
                        reg['id_ficha_acceso'],
                        reg['id_control'] or 'N/A',
                        reg['estado_marc'] or 'VALIDADO',
                        estado,
                        biblio,
                        causa,
                    ),
                    tags=(estado,),
                )
        except Exception as exc:
            messagebox.showerror('Error de filtrado', str(exc))
        finally:
            if cerrar_al_final and writer:
                writer.close()

    def exportar_reporte_lote(self):
        lote = self.var_lote.get().strip()
        writer = None
        try:
            writer = self._conectar_writer()
            resumen = writer.obtener_resumen_koha(lote)
            if not resumen:
                messagebox.showinfo('Sin datos', 'No hay resultados de Koha para exportar en este lote.')
                return
            registros = writer.listar_detalle_koha(lote)
        except Exception as exc:
            messagebox.showerror('Error', str(exc))
            return
        finally:
            if writer:
                writer.close()

        ruta = filedialog.asksaveasfilename(
            title='Guardar reporte de calidad e importación Koha',
            initialfile=f'Reporte_Koha_{lote}.csv',
            defaultextension='.csv',
            filetypes=[('Archivo CSV (Excel)', '*.csv')],
        )
        if not ruta:
            return

        with open(ruta, 'w', newline='', encoding='utf-8-sig') as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow(['REPORTE DE IMPORTACIÓN Y CONCILIACIÓN KOHA - NexoMARC'])
            csv_writer.writerow([
                'Lote', lote, 'Fecha', resumen['fecha_importacion'], 'Responsable', resumen['usuario']
            ])
            csv_writer.writerow([
                'Total Enviados', resumen['total_enviados'],
                'Aceptados Koha', resumen['total_aceptados'],
                'Rechazados Koha', resumen['total_rechazados'],
                'Estado Conciliación', resumen['estado_conciliacion'],
            ])
            csv_writer.writerow([])
            csv_writer.writerow([
                'ID_Ficha_Access', 'Control_MARC_001', 'Resultado_Koha', 'Biblionumber_Koha', 'Causa_Rechazo'
            ])
            for r in registros:
                csv_writer.writerow([
                    r['id_ficha_acceso'],
                    r['id_control'],
                    r['resultado'],
                    r['biblionumber_koha'] or '',
                    r['causa_rechazo'] or 'Importado sin incidencias',
                ])

        if messagebox.askyesno('Reporte generado', f'Reporte exportado correctamente en:\n{ruta}\n\n¿Deseas abrir el archivo?'):
            os.startfile(ruta)