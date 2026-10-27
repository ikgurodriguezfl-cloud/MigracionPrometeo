"""Panel Tkinter del sprint 2, integrado en el Notebook de MigracionApp."""
from dataclasses import asdict
from datetime import datetime
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from lotes import ESTADOS, ETAPAS, lotes_de_ejemplo


class PanelLotes(ttk.Frame):
    def __init__(self, parent, listar, politica, iniciar, exportar, conexiones):
        super().__init__(parent, padding=16, style='Panel.TFrame')
        self.listar = listar
        self.politica = politica
        self.iniciar = iniciar
        self.exportar = exportar
        self.conexiones = conexiones
        self.seleccionado = None
        self.lotes = []
        self.demo = tk.BooleanVar(value=False)
        self.filtro = tk.StringVar(value='Todos')
        self.consulta = tk.StringVar()
        self._estilos()
        self._crear()
        self.actualizar()

    def _estilos(self):
        estilo = ttk.Style(self)
        estilo.configure('Panel.TFrame', background='#f5f6fa')
        estilo.configure('Tarjeta.TFrame', background='#ffffff')
        estilo.configure('Panel.TLabel', background='#f5f6fa', foreground='#777d91', font=('Segoe UI', 9))
        estilo.configure('Titulo.Panel.TLabel', background='#f5f6fa', foreground='#29283e', font=('Segoe UI', 21, 'bold'))
        estilo.configure('Tarjeta.TLabel', background='#ffffff', foreground='#6f7589', font=('Segoe UI', 9))
        estilo.configure('Nombre.TLabel', background='#ffffff', foreground='#35324d', font=('Segoe UI', 14, 'bold'))
        estilo.configure('Numero.TLabel', background='#ffffff', foreground='#7055c5', font=('Segoe UI', 20, 'bold'))
        estilo.configure('Lotes.Treeview', rowheight=32, font=('Segoe UI', 9))
        estilo.configure('Lotes.Treeview.Heading', font=('Segoe UI', 9, 'bold'))
        estilo.configure('Lotes.Horizontal.TProgressbar', background='#8065ca', troughcolor='#ece8f6')

    def _crear(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        cabecera = ttk.Frame(self, style='Panel.TFrame')
        cabecera.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(cabecera, text='Panel de lotes', style='Titulo.Panel.TLabel').pack(side='left')
        ttk.Button(cabecera, text='Configurar conexiones', command=self.conexiones).pack(side='right', padx=(8, 0))
        ttk.Checkbutton(cabecera, text='Ver estados de ejemplo', variable=self.demo, command=self._cambiar_modo).pack(side='right')
        self.aviso = ttk.Label(self, text='Consulta los lotes reales de esta aplicación.', style='Panel.TLabel')
        self.aviso.grid(row=1, column=0, sticky='ew', pady=(0, 12))

        metricas = ttk.Frame(self, style='Panel.TFrame')
        metricas.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        self.metricas = {}
        for columna, (clave, etiqueta) in enumerate((('todos', 'Lotes registrados'), ('en_proceso', 'En proceso'), ('concluido', 'Concluidos'), ('con_incidencias', 'Con incidencias'))):
            metricas.columnconfigure(columna, weight=1, uniform='metricas')
            tarjeta = ttk.Frame(metricas, padding=10, style='Tarjeta.TFrame')
            tarjeta.grid(row=0, column=columna, sticky='ew', padx=(0, 8 if columna < 3 else 0))
            ttk.Label(tarjeta, text=etiqueta, style='Tarjeta.TLabel').pack(anchor='w')
            valor = ttk.Label(tarjeta, text='0', style='Numero.TLabel')
            valor.pack(anchor='w')
            self.metricas[clave] = valor

        cuerpo = ttk.Panedwindow(self, orient='horizontal')
        cuerpo.grid(row=3, column=0, sticky='nsew')
        listado = ttk.Frame(cuerpo, padding=8, style='Tarjeta.TFrame')
        detalle = ttk.Frame(cuerpo, padding=16, style='Tarjeta.TFrame')
        cuerpo.add(listado, weight=3)
        cuerpo.add(detalle, weight=2)
        listado.columnconfigure(0, weight=1)
        listado.rowconfigure(1, weight=1)
        filtros = ttk.Frame(listado, style='Tarjeta.TFrame')
        filtros.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        ttk.Label(filtros, text='Lotes de migración', style='Tarjeta.TLabel').pack(anchor='w', pady=(0, 6))
        combo = ttk.Combobox(filtros, textvariable=self.filtro, values=['Todos'] + list(ESTADOS.values()), state='readonly', width=17)
        combo.pack(side='left', padx=(0, 8))
        combo.bind('<<ComboboxSelected>>', lambda _: self._pintar_tabla())
        entrada = ttk.Entry(filtros, textvariable=self.consulta)
        entrada.pack(side='left', fill='x', expand=True)
        ttk.Label(filtros, text='Filtrar', style='Tarjeta.TLabel').pack(side='left', padx=(5, 0))
        self.consulta.trace_add('write', lambda *_: self._pintar_tabla())
        self.tabla = ttk.Treeview(listado, columns=('lote', 'estado', 'avance', 'total'), show='headings', selectmode='browse', style='Lotes.Treeview')
        for columna, titulo, ancho in (('lote', 'Lote / origen', 240), ('estado', 'Estado', 130), ('avance', 'Avance', 70), ('total', 'Recibidos', 75)):
            self.tabla.heading(columna, text=titulo)
            self.tabla.column(columna, width=ancho, minwidth=65, stretch=columna == 'lote', anchor='w')
        self.tabla.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(listado, orient='vertical', command=self.tabla.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(listado, orient='horizontal', command=self.tabla.xview)
        horizontal.grid(row=2, column=0, sticky='ew')
        self.tabla.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        for estado, color in (('en_espera', '#777d91'), ('en_proceso', '#477bbb'), ('concluido', '#358265'), ('con_incidencias', '#a36d23')):
            self.tabla.tag_configure(estado, foreground=color)
        self.tabla.bind('<<TreeviewSelect>>', self._seleccionar)
        self.sin_lotes = ttk.Label(listado, style='Tarjeta.TLabel', wraplength=430)
        self.sin_lotes.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(8, 0))

        detalle.columnconfigure(0, weight=1)
        self.identificador = ttk.Label(detalle, style='Tarjeta.TLabel')
        self.identificador.grid(row=0, column=0, sticky='w')
        self.nombre = ttk.Label(detalle, style='Nombre.TLabel', wraplength=340)
        self.nombre.grid(row=1, column=0, sticky='ew', pady=(4, 8))
        self.estado = ttk.Label(detalle, style='Tarjeta.TLabel')
        self.estado.grid(row=2, column=0, sticky='ew')
        self.etapa = ttk.Label(detalle, style='Tarjeta.TLabel')
        self.etapa.grid(row=3, column=0, sticky='ew', pady=(4, 8))
        self.barra = ttk.Progressbar(detalle, maximum=100, style='Lotes.Horizontal.TProgressbar')
        self.barra.grid(row=4, column=0, sticky='ew')
        self.conteos = ttk.Label(detalle, style='Tarjeta.TLabel', wraplength=350)
        self.conteos.grid(row=5, column=0, sticky='ew', pady=(7, 10))
        self.siguiente = ttk.Label(detalle, style='Tarjeta.TLabel', wraplength=350)
        self.siguiente.grid(row=6, column=0, sticky='ew', pady=(0, 12))
        acciones = ttk.Frame(detalle, style='Tarjeta.TFrame')
        acciones.grid(row=7, column=0, sticky='ew')
        self.btn_iniciar = ttk.Button(acciones, text='Ejecutar migración', command=self._iniciar)
        self.btn_iniciar.pack(fill='x', pady=3)
        self.btn_exportar = ttk.Button(acciones, text='Exportar MARCXML del lote', command=self._exportar)
        self.btn_exportar.pack(fill='x', pady=3)
        fila = ttk.Frame(acciones, style='Tarjeta.TFrame')
        fila.pack(fill='x', pady=3)
        self.btn_incidencias = ttk.Button(fila, text='Ver incidencias', command=self._incidencias)
        self.btn_incidencias.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.btn_resumen = ttk.Button(fila, text='Guardar resumen', command=self._resumen)
        self.btn_resumen.pack(side='left', fill='x', expand=True)
        self.actualizado = ttk.Label(detalle, style='Tarjeta.TLabel', wraplength=350)
        self.actualizado.grid(row=8, column=0, sticky='ew', pady=(12, 0))
        ttk.Button(self, text='Ver actividad del lote', command=self._actividad).grid(row=4, column=0, sticky='e', pady=(10, 0))

    def _cambiar_modo(self):
        self.seleccionado = None
        self.actualizar()

    def actualizar(self, seleccionar=None):
        self.lotes = lotes_de_ejemplo() if self.demo.get() else self.listar()
        self.aviso.config(text='DEMOSTRACIÓN: datos de ejemplo. No se ejecutan ni exportan migraciones reales.' if self.demo.get() else 'Historial de la aplicación. El avance se actualiza durante la migración.')
        for clave, widget in self.metricas.items():
            widget.config(text=str(len(self.lotes) if clave == 'todos' else sum(lote.estado == clave for lote in self.lotes)))
        if seleccionar and not self.demo.get():
            self.seleccionado = seleccionar
        if not any(lote.id == self.seleccionado for lote in self.lotes):
            preferido = next((lote for lote in self.lotes if lote.estado == 'en_proceso'), self.lotes[0] if self.lotes else None)
            self.seleccionado = preferido.id if preferido else None
        self._pintar_tabla()
        self._pintar_detalle()

    def seleccionar_real(self, identificador):
        self.demo.set(False)
        self.filtro.set('Todos')
        self.consulta.set('')
        self.actualizar(identificador)

    def _pintar_tabla(self):
        self.tabla.delete(*self.tabla.get_children())
        consulta = self.consulta.get().strip().casefold()
        visibles = []
        for lote in self.lotes:
            if self.filtro.get() not in ('Todos', ESTADOS[lote.estado]):
                continue
            if consulta and consulta not in (lote.id + ' ' + lote.fuente).casefold():
                continue
            self.tabla.insert('', 'end', iid=lote.id, values=(f'{lote.id} · {os.path.basename(lote.fuente)}', ESTADOS[lote.estado], f'{lote.progreso:g} %', f'{lote.total_recibidos:,}'), tags=(lote.estado,))
            visibles.append(lote.id)
        if self.seleccionado in visibles:
            self.tabla.selection_set(self.seleccionado)
        self.sin_lotes.config(text='Sin lotes todavía. En Conexiones selecciona Access y pulsa Probar conexión para registrar un lote.' if not self.lotes else f'{len(visibles)} de {len(self.lotes)} lotes visibles. Selecciona una fila para consultar su detalle.')

    def _seleccionar(self, _evento=None):
        seleccion = self.tabla.selection()
        if seleccion:
            self.seleccionado = seleccion[0]
            self._pintar_detalle()

    def lote_actual(self):
        return next((lote for lote in self.lotes if lote.id == self.seleccionado), None)

    def _pintar_detalle(self):
        lote = self.lote_actual()
        if lote is None:
            self.identificador.config(text='NINGÚN LOTE SELECCIONADO')
            self.nombre.config(text='Todo listo para comenzar')
            for etiqueta in (self.estado, self.etapa, self.conteos, self.siguiente, self.actualizado):
                etiqueta.config(text='')
            self.barra['value'] = 0
        else:
            self.identificador.config(text=lote.id)
            self.nombre.config(text=os.path.basename(lote.fuente))
            self.estado.config(text='Estado: ' + ESTADOS[lote.estado])
            self.etapa.config(text='Etapa: ' + ETAPAS[lote.etapa])
            self.barra['value'] = lote.progreso
            self.conteos.config(text=(f'Recibidos: {lote.total_recibidos:,}  ·  En esta ejecución: {lote.total_objetivo:,}\n'
                f'Procesados: {lote.procesados:,} ({lote.progreso:g} %)  ·  Pendientes: {lote.pendientes:,}\n'
                f'Correctos: {lote.correctos:,}  ·  Omitidos: {lote.omitidos:,}  ·  Errores: {lote.errores:,}\n'
                f'Ejemplares guardados: {lote.ejemplares:,}'))
            pasos = {
                'en_espera': 'Siguiente paso: confirma conexiones y opciones, y ejecuta la migración. Si cambiaste el archivo, valida Access otra vez.',
                'en_proceso': 'Procesamiento en curso. La exportación se habilita al concluir sin errores.',
                'concluido': 'Procesamiento finalizado. Revisa el resumen antes de exportar los nuevos registros correctos del lote. Esto no importa a Koha.',
                'con_incidencias': 'Revisa las incidencias y los registros pendientes. La exportación permanece bloqueada para evitar continuar antes de resolverlas.',
            }
            self.siguiente.config(text=pasos[lote.estado])
            self.actualizado.config(text='Última actualización: ' + datetime.fromisoformat(lote.actualizado_en).strftime('%d/%m/%Y %H:%M:%S'))
        politica = self.politica(lote, self.demo.get())
        for accion, boton in (('iniciar', self.btn_iniciar), ('exportar', self.btn_exportar), ('incidencias', self.btn_incidencias), ('resumen', self.btn_resumen)):
            boton.configure(state='normal' if politica[accion] else 'disabled')

    def _iniciar(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['iniciar']:
            self.iniciar(lote.id)

    def _exportar(self):
        lote = self.lote_actual()
        if self.politica(lote, self.demo.get())['exportar']:
            self.exportar(lote.id)

    def _ventana_texto(self, titulo, contenido):
        ventana = tk.Toplevel(self)
        ventana.title(titulo)
        ventana.geometry('700x430')
        ventana.transient(self.winfo_toplevel())
        ventana.columnconfigure(0, weight=1)
        ventana.rowconfigure(0, weight=1)
        marco = ttk.Frame(ventana, padding=12)
        marco.grid(row=0, column=0, sticky='nsew')
        texto = tk.Text(marco, wrap='word', font=('Segoe UI', 10))
        texto.pack(side='left', fill='both', expand=True)
        barra = ttk.Scrollbar(marco, command=texto.yview)
        barra.pack(side='right', fill='y')
        texto.configure(yscrollcommand=barra.set)
        texto.insert('1.0', contenido)
        texto.configure(state='disabled')
        ttk.Button(ventana, text='Cerrar', command=ventana.destroy).grid(row=1, column=0, pady=(0, 12))

    def _incidencias(self):
        lote = self.lote_actual()
        if lote and self.politica(lote, self.demo.get())['incidencias']:
            detalle = '\n\n'.join(f'{item["referencia"]}\n{item["mensaje"]}' for item in lote.incidencias)
            self._ventana_texto(f'Incidencias · {lote.id}', f'{lote.errores} registros con error. Se conservan hasta 100 incidencias recientes.\n\n{detalle}')

    def _actividad(self):
        lote = self.lote_actual()
        if lote:
            self._ventana_texto(f'Actividad · {lote.id}', '\n\n'.join(f'{item["fecha"]}\n{item["mensaje"]}' for item in reversed(lote.actividad)))

    def _resumen(self):
        lote = self.lote_actual()
        if not lote or not self.politica(lote, self.demo.get())['resumen']:
            return
        ruta = filedialog.asksaveasfilename(parent=self, title='Guardar resumen del lote', initialfile=f'{"EJEMPLO-" if self.demo.get() else ""}{lote.id}.json', defaultextension='.json', filetypes=[('Resumen JSON', '*.json')])
        if not ruta:
            return
        try:
            with open(ruta, 'w', encoding='utf-8') as archivo:
                json.dump({'demostracion': self.demo.get(), 'lote': asdict(lote), 'procesados': lote.procesados, 'pendientes': lote.pendientes, 'progreso': lote.progreso}, archivo, ensure_ascii=False, indent=2)
            messagebox.showinfo('Resumen guardado', 'Se guardó el reporte de seguimiento del lote.', parent=self)
        except OSError as exc:
            messagebox.showerror('No se pudo guardar', str(exc), parent=self)
