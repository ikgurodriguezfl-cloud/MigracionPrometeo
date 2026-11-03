"""Exportación atómica de las fichas confirmadas de un lote."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET

NS = 'http://www.loc.gov/MARC21/slim'
ET.register_namespace('', NS)


def registro_guardado(xml, id_ficha):
    # El conversor 1.0 almacenaba la colección sin su última etiqueta.
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        raiz = ET.fromstring(xml.rstrip() + '</collection>')
    if raiz.tag != f'{{{NS}}}collection' or len(raiz) != 1 or raiz[0].tag != f'{{{NS}}}record':
        raise ValueError(f'La ficha {id_ficha} no contiene un único registro MARCXML.')
    registro = raiz[0]
    controles = registro.findall(f"{{{NS}}}controlfield[@tag='001']")
    if len(controles) != 1 or controles[0].text != str(id_ficha):
        raise ValueError(f'El campo MARC 001 no coincide con la ficha {id_ficha}.')
    return registro


def exportar_lote(conn, ids, ruta):
    temporal = None
    try:
        with NamedTemporaryFile(dir=Path(ruta).parent, mode='wb', delete=False) as salida:
            temporal = salida.name
            salida.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<collection xmlns="{NS}">\n'.encode())
            for inicio in range(0, len(ids), 500):
                grupo = ids[inicio:inicio + 500]
                parametros = ','.join(['%s'] * len(grupo))
                with conn.cursor() as cursor:
                    cursor.execute('SELECT id_ficha_acceso, marca_marcxml FROM registros_marc '
                                   f'WHERE id_ficha_acceso IN ({parametros}) ORDER BY id_ficha_acceso', tuple(grupo))
                    filas = cursor.fetchall()
                if sorted(grupo) != sorted(f['id_ficha_acceso'] for f in filas):
                    raise ValueError('Las fichas del destino ya no coinciden con el lote.')
                for fila in filas:
                    registro = registro_guardado(fila['marca_marcxml'], fila['id_ficha_acceso'])
                    salida.write(ET.tostring(registro, encoding='utf-8') + b'\n')
            salida.write(b'</collection>\n')
        os.replace(temporal, ruta)
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)
