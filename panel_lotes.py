"""Consulta y control de lotes reales dentro de la ventana principal."""
import json
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from lotes import ESTADOS, ETAPAS

PAGINA = 50


class PanelLotes(ttk.Frame):
    def __init__(self, parent, listar, politica, iniciar, exportar, conexiones, detener):
        super().__init__(parent, padding=(10, 6))
        self.listar, self.politica = listar, politica
        self.iniciar, self.exportar, self.detener = iniciar, exportar, detener
        self.lotes = []
        self.seleccionado = None
        self.pagina = 0
        self.filtro = tk.StringVar(value='Todos')
        self.consulta = tk.StringVar()
        self.buscar_ficha = tk.StringVar()
        self.tipo_ficha = tk.StringVar(value='Todas')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(4, weight=2)

        cabecera = ttk.Frame(self)
        cabecera.grid(row=0, column=0, sticky='ew')
        resumen = ttk.Frame(cabecera)
        resumen.pack(side='bottom', fill='x', pady=(3, 2))
        self.metricas = {}
        for columna, (clave, texto) in enumerate((('en_espera', 'En espera'), ('en_proceso', 'En proceso'),
                                                  ('concluido', 'Concluidos'), ('con_incidencias', 'Con incidencias'))):
            tarjeta = ttk.Frame(resumen, padding=(5, 2), style='Marca.TFrame')
            tarjeta.grid(row=0, column=columna, sticky='ew', padx=1)
            resumen.columnconfigure(columna, weight=1, uniform='metricas')
            numero = ttk.Label(tarjeta, style='Cifra.TLabel')
            numero.pack(side='left')
            ttk.Label(tarjeta, text=texto, style='Leyenda.TLabel').pack(side='left', padx=4)
            self.metricas[clave] = numero
        self.titulo = ttk.Label(cabecera, text='Lotes', style='Titulo.TLabel')
        self.titulo.pack(side='left')
        self.nuevo = ttk.Button(cabecera, text='Nuevo lote', command=conexiones, style='Principal.TButton')
        self.nuevo.pack(side='right')
        filtros = ttk.Frame(self)
        filtros.grid(row=1, column=0, sticky='ew', pady=(3, 4))
        ttk.Label(filtros, text='Buscar lote').pack(side='left')
        ttk.Entry(filtros, textvariable=self.consulta, width=14).pack(side='left', fill='x', expand=True, padx=5)
        ttk.Combobox(filtros, textvariable=self.filtro, values=['Todos', *ESTADOS.values()],
                     width=15, state='readonly').pack(side='right')

        lista = ttk.Frame(self)
        lista.grid(row=2, column=0, sticky='nsew')
        self.tabla = ttk.Treeview(lista, columns=('origen', 'estado', 'avance'), show='headings',
                                  selectmode='browse', height=3)
        for clave, titulo, ancho in [('origen','Origen del lote',190),('estado','Estado',110),('avance','Avance',65)]:
            self.tabla.heading(clave, text=titulo)
            self.tabla.column(clave, width=ancho, minwidth=42, stretch=clave == 'origen')
        barra = ttk.Scrollbar(lista, command=self.tabla.yview)
        barra.pack(side='right', fill='y')
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.pack(fill='both', expand=True)
        for estado,color in (('en_proceso','#1e5369'), ('concluido','#1f6645'), ('con_incidencias','#8d4124')):
            self.tabla.tag_configure(estado, foreground=color)
        self.tabla.bind('<<TreeviewSelect>>', self._seleccionar)
        for variable in (self.filtro, self.consulta):
            variable.trace_add('write', lambda *_: self._pintar_tabla())

        estado = ttk.Frame(self)
        estado.grid(row=3, column=0, sticky='ew', pady=4)
        self.identificador = ttk.Label(estado, text='Selecciona un lote')
        self.identificador.pack(side='left')
        self.barra = ttk.Progressbar(estado, length=76)
        self.barra.pack(side='right', padx=3)
        self.vistas = ttk.Notebook(self)
        self.vistas.grid(row=4, column=0, sticky='nsew')
        self.textos = {}
        self.paginas = {}
        for nombre in ('Resumen', 'Fichas', 'Incidencias', 'Actividad'):
            marco = ttk.Frame(self.vistas, padding=5)
            self.vistas.add(marco, text=nombre)
            if nombre == 'Fichas':
                busqueda = ttk.Frame(marco)
                busqueda.pack(fill='x')
                ttk.Label(busqueda, text='Buscar').pack(side='left')
                ttk.Entry(busqueda, textvariable=self.buscar_ficha, width=10).pack(side='left', expand=True, fill='x', padx=4)
                ttk.Combobox(busqueda, textvariable=self.tipo_ficha, width=15, state='readonly',
                             values=('Todas','Convertidas','Con incidencias','Rechazadas','Omitidas')).pack(side='left')
            if nombre in ('Fichas','Incidencias'):
                nav = ttk.Frame(marco)
                nav.pack(side='bottom', fill='x')
                ttk.Button(nav, text='‹', width=3, command=lambda: self._avanzar(-1)).pack(side='left')
                ttk.Button(nav, text='›', width=3, command=lambda: self._avanzar(1)).pack(side='right')
                self.paginas[nombre] = tk.StringVar()
                ttk.Label(nav, textvariable=self.paginas[nombre], anchor='center').pack(fill='x')
            texto = tk.Text(marco, height=3, width=20, wrap='word', font='TkTextFont', relief='flat',
                            padx=7, pady=4, state='disabled', background='white')
            scroll = ttk.Scrollbar(marco, command=texto.yview)
            scroll.pack(side='right', fill='y')
            texto.configure(yscrollcommand=scroll.set)
            texto.pack(fill='both', expand=True)
            self.textos[nombre] = texto
        self.vistas.bind('<<NotebookTabChanged>>', self._reiniciar_pagina)
        for var in (self.buscar_ficha, self.tipo_ficha):
            var.trace_add('write', self._reiniciar_pagina)

        # Fila reservada: sólo la lista y el detalle ceden altura al reducir la ventana.
        pie = ttk.Frame(self)
        pie.grid(row=5, column=0, sticky='ew', pady=(6, 0))
        self.botones = {}
        for i, (accion, titulo, cmd) in enumerate((
                ('iniciar','Ejecutar',self.iniciar), ('detener','Detener',self.detener),
                ('exportar','Exportar MARCXML',self.exportar), ('resumen','Guardar resumen',self._resumen))):
            boton = ttk.Button(pie, text=titulo, width=1,
                               command=lambda a=accion,c=cmd: self._accion(a,c))
            boton.grid(row=0,column=i,sticky='ew',padx=1)
            pie.columnconfigure(i, weight=2 if i > 1 else 1)
            self.botones[accion] = boton
        self.btn_iniciar = self.botones['iniciar']
        self.btn_detener = self.botones['detener']
        self.btn_exportar = self.botones['exportar']
        self.btn_resumen = self.botones['resumen']

    def _avanzar(self, paso):
        self.pagina = max(0, self.pagina + paso)
        self._pintar_detalle()

    def _reiniciar_pagina(self, *_):
        self.pagina = 0
        self._pintar_detalle()

    def actualizar(self, seleccionar=None):
        self.lotes = self.listar()
        for estado, etiqueta in self.metricas.items():
            etiqueta.configure(text=str(sum(lote.estado == estado for lote in self.lotes)))
        if seleccionar:
            self.seleccionado = seleccionar
        self._pintar_tabla()

    def seleccionar_real(self, identificador):
        self.consulta.set('')
        self.filtro.set('Todos')
        self.actualizar(identificador)

    def _pintar_tabla(self):
        filtro = self.filtro.get()
        consulta = self.consulta.get().casefold()
        visibles = [lote for lote in self.lotes if filtro in ('Todos', ESTADOS[lote.estado])
                    and consulta in (lote.id + ' ' + lote.fuente).casefold()]
        ids = {lote.id for lote in visibles}
        for item in self.tabla.get_children():
            if item not in ids:
                self.tabla.delete(item)
        for pos, lote in enumerate(visibles):
            valores = (Path(lote.fuente).name, ESTADOS[lote.estado], f'{lote.progreso:g} %')
            if self.tabla.exists(lote.id):
                self.tabla.item(lote.id, values=valores, tags=(lote.estado,))
            else:
                self.tabla.insert('', pos, iid=lote.id, values=valores, tags=(lote.estado,))
        if self.seleccionado not in ids:
            self.seleccionado = visibles[0].id if visibles else None
            self.pagina = 0
        if self.seleccionado and self.tabla.selection() != (self.seleccionado,):
            self.tabla.selection_set(self.seleccionado)
            self.tabla.see(self.seleccionado)
        self.titulo.configure(text=f'Lotes · {len(self.lotes)}')
        self._pintar_detalle()

    def _seleccionar(self, _evento):
        seleccion = self.tabla.selection()
        if seleccion and seleccion[0] != self.seleccionado:
            self.seleccionado = seleccion[0]
            self._reiniciar_pagina()

    def lote_actual(self):
        return next((lote for lote in self.lotes if lote.id == self.seleccionado), None)

    def _filas(self, lote):
        if lote.resultados is not None:
            return lote.resultados
        # Los lotes históricos sólo identifican las fichas guardadas.
        return [dict(referencia=f'Ficha {i}', estado='Convertida', titulo='', motivos=[])
                for i in lote.fichas_correctas]

    def _contenido(self, vista, lote, politica):
        if vista == 'Resumen':
            return (f'{Path(lote.fuente).name}\n{ESTADOS[lote.estado]} · {ETAPAS[lote.etapa]}\n'
                    f'Recibidos: {lote.total_recibidos}   ·   En esta ejecución: {lote.total_objetivo}\n'
                    f'Convertidas: {lote.correctos}   ·   Omitidas: {lote.omitidos}   ·   Rechazadas: {lote.errores}   ·   Pendientes: {lote.pendientes}\n'
                    f'Ejemplares: {lote.ejemplares}   ·   Usuario: {lote.usuario or "Sin registrar"}\n'
                    f'Mapeo: {lote.version_mapeo or "Sin registrar"}   ·   Inicio: {lote.creado_en}\n'
                    + {'en_espera':'Respaldo validado. Listo para ejecutar.',
                       'en_proceso':'Detención solicitada.' if politica['detencion_solicitada'] else 'Migración en curso.',
                       'con_incidencias':'Revisa las fichas señaladas en Incidencias.',
                       'detenido':'Los avances se conservaron. Puedes guardar el resumen.',
                       'concluido':'Puedes consultar las fichas y guardar el resultado.'}[lote.estado])
        if vista == 'Actividad':
            return '\n\n'.join(f"{i['fecha']}   {i['mensaje']}" for i in reversed(lote.actividad)) or 'Sin actividad registrada.'
        if vista == 'Fichas':
            filtro = self.tipo_ficha.get()
            consulta = self.buscar_ficha.get().strip().casefold()
            resultados = self._filas(lote)
            if filtro == 'Con incidencias':
                resultados = [fila for fila in resultados if fila['motivos']]
            elif filtro != 'Todas':
                resultados = [fila for fila in resultados if filtro == fila['estado'] + 's']
            if consulta:
                resultados = [fila for fila in resultados
                              if consulta in (fila['referencia'] + ' ' + fila['titulo']).casefold()]
        else:
            resultados = [motivo for fila in lote.resultados or [] for motivo in fila['motivos']]
            for incidencia in lote.incidencias:
                if lote.resultados is None or incidencia['referencia'] in ('Ejecución', 'Origen'):
                    resultados.append(f"{incidencia['referencia']}: {incidencia['mensaje']}")
        paginas = max(1, (len(resultados) + PAGINA - 1) // PAGINA)
        self.pagina = min(self.pagina, paginas - 1)
        etiqueta = 'resultado' if len(resultados) == 1 else 'resultados'
        self.paginas[vista].set(f'{len(resultados)} {etiqueta} · {self.pagina + 1}/{paginas}')
        inicio = self.pagina * PAGINA
        lineas = resultados[inicio:inicio + PAGINA]
        if vista == 'Fichas':
            lineas = [self._texto_ficha(fila) for fila in lineas]
        nota = 'Historial anterior: detalle parcial.\n' if lote.resultados is None and lote.procesados else ''
        return nota + ('\n\n'.join(lineas) or 'Sin resultados.')

    @staticmethod
    def _texto_ficha(fila):
        estado = fila['estado']
        if estado == 'Convertida' and fila['motivos']:
            estado = 'Convertida con incidencias'
        encabezado = f"{fila['referencia']} · {estado}"
        if fila['titulo']:
            encabezado += ' · ' + fila['titulo']
        return '\n    '.join([encabezado, *fila['motivos']])

    def _pintar_detalle(self):
        if not hasattr(self, 'botones'):
            return
        lote = self.lote_actual()
        politica = self.politica(lote)
        for accion, boton in self.botones.items():
            boton.configure(state='normal' if politica[accion] else 'disabled')
        self.btn_detener.configure(text='Deteniendo…' if politica['detencion_solicitada'] else 'Detener')
        self.identificador.configure(text=lote.id if lote else 'Sin lote seleccionado')
        self.barra['value'] = lote.progreso if lote else 0
        vista = self.vistas.tab(self.vistas.select(), 'text')
        contenido = self._contenido(vista, lote, politica) if lote else 'Selecciona un lote o pulsa Nuevo lote para validar un respaldo.'
        if not lote and vista in self.paginas:
            self.paginas[vista].set('')
        texto = self.textos[vista]
        if texto.get('1.0', 'end-1c') != contenido:
            texto.configure(state='normal')
            texto.delete('1.0', 'end')
            texto.insert('1.0', contenido)
            texto.configure(state='disabled')

    def _accion(self, accion, funcion):
        lote = self.lote_actual()
        if lote and self.politica(lote)[accion]:
            funcion(lote.id)

    def _resumen(self, identificador):
        lote = self.lote_actual()
        if not lote or lote.id != identificador:
            return
        ruta = filedialog.asksaveasfilename(parent=self, title='Guardar resumen del lote',
            initialfile=lote.id+'.json', defaultextension='.json', filetypes=[('Resumen JSON','*.json')])
        if ruta:
            datos = dict(demostracion=False, lote=asdict(lote), procesados=lote.procesados, pendientes=lote.pendientes, progreso=lote.progreso)
            try:
                Path(ruta).write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('No se pudo guardar', str(exc), parent=self)
