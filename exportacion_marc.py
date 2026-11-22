"""Exportación por bloques de las copias vigentes del destino del lote."""
import csv
from contextlib import ExitStack
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

from pymarc import record_to_xml

from validacion_marc import ERROR, inspeccionar_copias, NAMESPACE


def exportar_lote(ruta, lote, writer, perfil=None):
    """XML/MRC completo o ZIP parcial con el detalle de cada exclusión."""
    ruta = Path(ruta)
    formato = ruta.suffix.lower()
    if formato not in ('.xml', '.mrc', '.zip'):
        raise ValueError('Usa una extensión .xml, .mrc o .zip.')
    if lote.pendientes:
        raise ValueError('El lote tiene fichas pendientes. Termina el reprocesamiento antes de exportar.')
    if len(set(lote.fichas_correctas)) != lote.correctos:
        raise ValueError('Los identificadores del historial no coinciden con las fichas convertidas.')
    if lote.errores and formato != '.zip':
        raise ValueError(f'Hay {lote.errores} fichas rechazadas en la migración. Revisa sus motivos en el lote o elige el ZIP parcial.')
    if lote.errores and lote.resultados is None:
        raise ValueError('El historial antiguo carece del detalle necesario para identificar las fichas rechazadas.')

    exportadas = advertidas = excluidas = 0
    ejemplos = []
    with ExitStack() as recursos:
        tmp = NamedTemporaryFile(dir=ruta.parent, delete=False)
        tmp.close()
        temporal = Path(tmp.name)
        recursos.callback(temporal.unlink, missing_ok=True)
        with ExitStack() as salida:
            if formato == '.zip':
                zipfile = salida.enter_context(ZipFile(temporal, 'w', compression=ZIP_DEFLATED))
                stream = salida.enter_context(zipfile.open('registros.xml', 'w', force_zip64=True))
                informe = recursos.enter_context(TemporaryFile(mode='w+', encoding='utf-8-sig', newline=''))
                reporte = csv.writer(informe)
                reporte.writerow(('ficha_access', 'resultado', 'motivo'))
                for fila in lote.resultados or ():
                    if fila['estado'] in ('Omitida', 'Rechazada'):
                        ref = fila['id'] if fila['id'] is not None else fila['referencia']
                        motivo = ' · '.join(fila['motivos'])
                        # Las hojas de cálculo pueden interpretar valores de texto como fórmulas.
                        reporte.writerow((ref, fila['estado'], "'" + motivo if motivo.lstrip().startswith(('=', '+', '-', '@')) else motivo))
                if lote.omitidos and lote.resultados is None:
                    reporte.writerow(('', 'Omitidas históricas', f'{lote.omitidos} ya existentes. El historial no conservó sus identificadores.'))
            else:
                stream = salida.enter_context(temporal.open('wb'))
            if formato != '.mrc':
                stream.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<collection xmlns="{NAMESPACE}">\n'.encode())
            for inicio in range(0, lote.correctos, 100):
                ids = lote.fichas_correctas[inicio:inicio+100]
                filas = writer.obtener_copias(ids)
                if {f['id_ficha_acceso'] for f in filas} != set(ids) or len(filas) != len(ids):
                    raise ValueError('El destino ya no contiene todas las fichas solicitadas. Verifica la conexión del lote.')
                for fila in filas:
                    record, issues = inspeccionar_copias(fila['marca_marcxml'], fila['marca_iso2709'], perfil, fila.get('duplicado'))
                    errores = [i.texto() for i in issues if i.gravedad == ERROR]
                    if errores:
                        excluidas += 1
                        if len(ejemplos) < 3:
                            ejemplos.append(f"Ficha {fila['id_ficha_acceso']} · {errores[0]}")
                        if formato == '.zip':
                            reporte.writerow((fila['id_ficha_acceso'], 'Con errores', ' · '.join(errores)))
                        continue
                    stream.write(fila['marca_iso2709'] if formato == '.mrc' else record_to_xml(record) + b'\n')
                    advertidas += bool(issues)
                    exportadas += 1
            if formato != '.mrc':
                stream.write(b'</collection>\n')
            if (excluidas and formato != '.zip') or not exportadas:
                raise ValueError(f'{excluidas} fichas con errores. Abre «Revisar fichas» para corregirlas.\n' + '\n'.join(ejemplos))
            if formato == '.zip':
                stream.close()
                informe.seek(0)
                with zipfile.open('exclusiones.csv', 'w', force_zip64=True) as destino:
                    while bloque := informe.read(65536):
                        destino.write(bloque.encode('utf-8'))
        os.replace(temporal, ruta)
    return exportadas, advertidas, excluidas + lote.errores
