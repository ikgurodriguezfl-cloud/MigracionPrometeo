"""Validación compartida por la migración, la revisión y la exportación."""
import csv
from functools import lru_cache
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from pymarc import MARCReader, parse_xml_to_array


NAMESPACE = 'http://www.loc.gov/MARC21/slim'
CATALOGO = json.loads(Path(__file__).with_name('reglas_marc21.json').read_text('utf-8'))
# Campos locales de ejemplar y tipo bibliográfico que escribe el migrador.
LOCALES = {
    '942': dict(repetible=False, indicadores=[' ', ' '], unicos='026acehkmns', repetidos='i'),
    '952': dict(repetible=True, indicadores=[' ', ' '], unicos='0123456789abcdefghijlmnopqrstuvwxyz', repetidos=''),
}
ERROR = 'Error'
AVISO = 'Advertencia'


@dataclass(frozen=True)
class Incidencia:
    gravedad: str
    campo: str
    detalle: str
    subcampo: str = ''
    ocurrencia: int = 0
    regla: str = 'MARC21'
    codigo: str = ''

    def texto(self):
        lugar = self.campo + ('$' + self.subcampo if self.subcampo else '')
        if self.ocurrencia:
            lugar += f' ({self.ocurrencia})'
        return f'{self.gravedad} · {lugar} · {self.detalle} [{self.regla}]'


def estado_ficha(incidencias):
    if any(i.gravedad == ERROR for i in incidencias):
        return 'Con errores'
    return 'Con advertencias' if incidencias else 'Válida'


class FrameworkKoha(dict):
    def __init__(self, reglas):
        super().__init__(reglas)
        self.campos_obligatorios = set()
        self.subcampos_obligatorios = {}
        for (tag, sub), (obligatorio, _) in reglas.items():
            if not obligatorio or tag == '000':
                continue
            if sub in ('', '@'):
                self.campos_obligatorios.add(tag)
            else:
                self.subcampos_obligatorios.setdefault(tag, set()).add(sub)


def cargar_framework(ruta):
    if not ruta:
        return {}
    ruta = Path(ruta)
    stat = ruta.stat()
    try:
        return _leer_framework(ruta, stat.st_mtime_ns, stat.st_size)
    except csv.Error as exc:
        raise ValueError(f'CSV de Koha ilegible: {exc}') from exc


@lru_cache(maxsize=4)
def _leer_framework(ruta, fecha, tamano):
    """Lee las dos tablas del CSV bibliográfico exportado por Koha."""
    perfil = {}
    encabezado = None
    tablas = set()
    codigos = set()
    with open(ruta, newline='', encoding='utf-8-sig') as entrada:
        for fila in csv.reader(entrada, strict=True):
            if not fila or not any(fila) or fila[0] == '#-#':
                continue
            if 'tagfield' in fila and 'mandatory' in fila and 'repeatable' in fila:
                encabezado = fila
                tablas.add('sub' if 'tagsubfield' in fila else 'tag')
                continue
            if not encabezado or len(fila) != len(encabezado):
                raise ValueError('El archivo debe ser un framework bibliográfico CSV exportado desde Koha.')
            datos = dict(zip(encabezado, fila))
            tag = datos['tagfield']
            sub = datos.get('tagsubfield', '')
            if (not re.fullmatch('[0-9]{3}', tag) or
                    ('tagsubfield' in datos and not re.fullmatch('[a-z0-9@]', sub)) or
                    any(datos[k] not in ('0', '1') for k in ('mandatory', 'repeatable'))):
                raise ValueError(f'Regla de Koha inválida en {tag} {sub}.')
            if (tag, sub) in perfil:
                raise ValueError(f'Regla de Koha duplicada en {tag} {sub}.')
            codigos.add(datos.get('frameworkcode', ''))
            perfil[tag, sub] = (datos['mandatory'] == '1', datos['repeatable'] == '1')
    if tablas != {'tag', 'sub'} or len(codigos) != 1 or not perfil:
        raise ValueError('Se requieren campos y subcampos de un único framework bibliográfico de Koha.')
    return FrameworkKoha(perfil)


def regla_campo(tag):
    return CATALOGO['campos'].get(tag) or LOCALES.get(tag)


def es_repetible(tag, perfil=None):
    perfil = perfil or {}
    regla = regla_campo(tag)
    local = perfil.get((tag, ''))
    if tag in LOCALES and local:
        return local[1]
    return bool((regla or local) and (not regla or regla['repetible']) and
                (not local or local[1]))


def _material(leader):
    tipo = leader[6]
    if tipo in 'at':
        return 'CONTINUING RESOURCES' if tipo == 'a' and leader[7] in 'bis' else 'BOOKS'
    if tipo in 'cdij':
        return 'MUSIC'
    if tipo in 'ef':
        return 'MAPS'
    if tipo in 'gkor':
        return 'VISUAL MATERIALS'
    return {'m': 'COMPUTER FILES', 'p': 'MIXED MATERIALS'}.get(tipo)


def normalizar_posiciones_libro(campos):
    """Sustituye únicamente códigos incompatibles por el valor oficial sin codificar."""
    cambios = []
    for tramo, valores in CATALOGO['posiciones_008']['BOOKS'].items():
        ini, fin = map(int, tramo.split('-'))
        for pos in range(ini, fin + 1):
            if campos[pos] not in valores and '|' in valores:
                campos[pos] = '|'
                cambios.append(str(pos))
    return cambios


def fuente_catalogacion_008(codigo):
    """008/39 de Access: conserva el código conocido o usa el relleno MARC."""
    minuscula = codigo.lower()
    permitidos = CATALOGO['posiciones_008']['ALL MATERIALS']['39-39']
    return minuscula if len(minuscula) == 1 and minuscula in permitidos else '|'


def _revisar_008(valor, leader, problemas):
    def error(pos, texto):
        problemas.append(Incidencia(ERROR, '008', f'{pos} · {texto}'))
    if len(valor) != 40:
        error('00–39', '008 debe tener exactamente 40 caracteres.')
        return
    try:
        datetime.strptime(valor[:6], '%y%m%d')
        if not valor[:6].isascii() or not valor[:6].isdigit():
            raise ValueError
    except ValueError:
        error('00–05', 'Indica la fecha de ingreso en formato AAMMDD.')
    material = _material(leader) if len(leader) == 24 else None
    tablas = CATALOGO['posiciones_008']
    for nombre in ('ALL MATERIALS', material):
        for posiciones, validos in tablas.get(nombre, {}).items():
            ini, fin = map(int, posiciones.split('-'))
            if any(c not in validos for c in valor[ini:fin + 1]):
                error(posiciones, f'Código incompatible con {nombre}: {valor[ini:fin + 1]!r}.')
    if material == 'MUSIC' and valor[18:20] not in CATALOGO['formas_musicales'] + ['||']:
        error('18–19', 'Forma de composición musical desconocida.')
    if material == 'MAPS' and valor[22:24] not in CATALOGO['proyecciones'] + ['||']:
        error('22–23', 'Código de proyección cartográfica desconocido.')
    if material == 'VISUAL MATERIALS' and not re.fullmatch(r'\d{3}|---|nnn|\|\|\|', valor[18:21]):
        error('18–20', 'La duración debe ser numérica o un código MARC de duración desconocida.')
    if not re.fullmatch(r'[a-z]{2}[a-z ]|\|\|\|', valor[15:18]):
        error('15–17', 'Código de lugar de publicación inválido.')
    if not re.fullmatch(r'[a-z]{3}| {3}|\|\|\|', valor[35:38]):
        error('35–37', 'Código de idioma inválido.')


def isbn_valido(valor):
    numero = re.sub(r'[\s-]', '', valor.split('(', 1)[0]).upper()
    if re.fullmatch(r'\d{9}[\dX]', numero):
        return sum((10 - i) * (10 if c == 'X' else int(c))
                   for i, c in enumerate(numero)) % 11 == 0
    if re.fullmatch(r'97[89]\d{10}', numero):
        return sum(int(c) * (1 if i % 2 == 0 else 3)
                   for i, c in enumerate(numero)) % 10 == 0
    return False

def validar_ficha(record, perfil=None):
    perfil = perfil or {}
    issues = []
    leader = str(record.leader)
    if not re.fullmatch(r'[0-9]{5}[acdnp][acdefgijkmoprt][abcdims][ a]a22[0-9]{5}[ 1234578uz][ acinu][ abc]4500', leader):
        issues.append(Incidencia(ERROR, 'LDR', 'Revisa las 24 posiciones, el tipo de material, UTF-8, los contadores 22 y el mapa 4500.'))
    vistos = Counter()
    bytes_registro = 26 + 12 * len(record.fields)
    # Requisitos operativos del proyecto (001 también identifica el registro en MySQL).
    obligatorios = {'001': '', '005': '', '008': '', '040': 'ac', '245': 'a'}
    for tag, subs in obligatorios.items():
        if not record.get_fields(tag):
            issues.append(Incidencia(ERROR, tag, 'Falta el campo requerido para esta migración.', subs[:1], regla='Perfil de migración'))
    for tag in getattr(perfil, 'campos_obligatorios', ()):
        if not record.get_fields(tag):
            issues.append(Incidencia(ERROR, tag, 'Campo obligatorio en el framework.', regla='Koha'))

    for field in record.fields:
        tag = field.tag
        vistos[tag] += 1
        n = vistos[tag]

        def add(texto, sub='', gravedad=ERROR, regla='MARC21', codigo=''):
            issues.append(Incidencia(gravedad, tag, texto, sub, n, regla, codigo))

        try:
            longitud = len(field.as_marc(encoding='utf-8'))
            if longitud > 9999:
                add('El campo supera 9 999 bytes, el máximo que admite el directorio ISO2709.')
            bytes_registro += longitud
        except (ValueError, TypeError, UnicodeError, IndexError):
            add('El campo contiene un valor que no puede representarse en UTF-8 MARC21.')
        norma = regla_campo(tag)
        if not re.fullmatch('[0-9]{3}', tag) or not (norma or (tag >= '010' and (tag, '') in perfil)):
            add('La serie 440 es obsoleta. Revisa la mención 490 y su acceso 830.' if tag == '440' else
                'Etiqueta desconocida. Comprueba la etiqueta o carga el framework para un campo local.')
        if n > 1 and not es_repetible(tag, perfil):
            add('El campo no es repetible.', regla='Koha' if norma and norma['repetible'] else 'MARC21')
        if field.is_control_field():
            dato = field.data or ''
            if not dato.strip() or re.search(r'[\x00-\x1f]', dato):
                add('El campo de control está vacío o contiene caracteres de control.')
            if tag == '001' and len(dato) > 50:
                add('El destino admite hasta 50 caracteres para el número de control.', regla='Perfil de migración')
            if tag == '005':
                try:
                    if not re.fullmatch(r'[0-9]{14}\.[0-9]', dato):
                        raise ValueError
                    datetime.strptime(dato[:14], '%Y%m%d%H%M%S')
                except ValueError:
                    add('005 debe tener el formato MARC AAAAMMDDhhmmss.d con fecha y hora válidas.')
            if tag == '008':
                _revisar_008(dato, leader, issues)
            continue
        if tag == '880':
            enlace = (field.get_subfields('6') or [''])[0][:3]
            norma = regla_campo(enlace)
            if not norma or enlace == '880' or enlace < '010':
                add('Indica la etiqueta asociada en el enlace.', '6')
                norma = None
        if len(field.indicators) != 2:
            add('Se requieren exactamente dos indicadores.')
        for i, indicador in enumerate(field.indicators[:2]):
            permitidos = norma['indicadores'][i] if norma else ''
            if not re.fullmatch('[0-9a-z ]', indicador or '') or (permitidos and indicador not in permitidos):
                if tag == '082' and i == 0:
                    add('Indicador 1 de Dewey. Confirma la edición: 0 completa, 1 abreviada o 7 otra edición con $2.')
                else:
                    add(f'Indicador {i + 1} inválido: {indicador!r}.')
        presentes = Counter()
        for sf in field.subfields:
            code = sf.code
            presentes[code] += 1
            local = perfil.get((tag, code))
            if (not re.fullmatch('[a-z0-9]', code) or
                    (norma and code not in norma['unicos'] + norma['repetidos'] and not local and tag != '886') or
                    (not norma and not local)):
                add('Código de subcampo no definido para esta etiqueta.', code)
            if presentes[code] > 1 and ((norma and code in norma['unicos'] and not (tag in LOCALES and local))
                                        or (local and not local[1])):
                add('Subcampo no repetible dentro de la misma ocurrencia.', code)
            if tag == '245' and code == 'a' and not any(c.isalnum() for c in sf.value):
                add('Introduce el título de la obra.', 'a', regla='Perfil de migración')
            if not sf.value.strip() or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', sf.value):
                add('Introduce un valor sin separadores de control.', code)
        if not presentes:
            add('Agrega al menos un subcampo.')
        requeridos = set(obligatorios.get(tag, ''))
        requeridos.update(getattr(perfil, 'subcampos_obligatorios', {}).get(tag, ()))
        for sub in sorted(requeridos - presentes.keys()):
            add('Falta el subcampo obligatorio.', sub, regla='Koha' if (tag, sub) in perfil else 'Perfil de migración')
        if tag == '952':
            for sub in ('a', 'b', 'y'):
                if sub not in presentes and sub not in requeridos:
                    add('Confirma el dato de ejemplar para Koha.', sub, AVISO, 'Calidad')
        if tag == '082' and field.indicator1 == '7' and not field.get_subfields('2'):
            add('Indica la otra edición de Dewey en $2.', '2')
        if tag == '020':
            for isbn in field.get_subfields('a'):
                if not isbn_valido(isbn):
                    add('Verifica el ISBN y su dígito de control.', 'a', AVISO, 'Calidad', 'isbn:' + isbn)

    if bytes_registro > 99999:
        issues.append(Incidencia(ERROR, 'LDR', 'La longitud del registro supera los 99 999 bytes que admite ISO2709.'))
    def aviso(tag, texto, sub='', codigo=''):
        issues.append(Incidencia(AVISO, tag, texto, sub, regla='Calidad', codigo=codigo))
    principales = record.get_fields('100', '110', '111', '130')
    if len({f.tag for f in principales}) > 1:
        issues.append(Incidencia(ERROR, principales[-1].tag, 'Sólo se admite una entrada principal 1XX.'))
    codigos = set()
    for num, item in enumerate(record.get_fields('952'), start=1):
        for codigo in item.get_subfields('p'):
            normalizado = codigo.strip().casefold()
            if normalizado in codigos:
                issues.append(Incidencia(ERROR, '952', 'Código de barras repetido en esta ficha.', 'p', num, 'Koha'))
            codigos.add(normalizado)
    if not record.get_fields('020'):
        aviso('020', 'Sin ISBN registrado. Confirma si el recurso dispone de uno.')
    if not record.get_fields('100', '110', '111', '130'):
        aviso('100', 'Sin entrada principal de autor o título uniforme.')
    publicaciones = record.get_fields('260', '264')
    for sub, nombre in [('a', 'lugar'), ('b', 'editor'), ('c', 'fecha')]:
        if not any(f.get_subfields(sub) for f in publicaciones):
            aviso(publicaciones[0].tag if publicaciones else '260/264', f'Falta el {nombre} de publicación.' if sub != 'c' else 'Falta la fecha de publicación.', sub)
    if not any(f.get_subfields('a') for f in record.get_fields('300')):
        aviso('300', 'Descripción física sin extensión.', 'a')
    if not record.get_fields('650'):
        aviso('650', 'Sin materia temática registrada.')
    fijo = record.get('008')
    if fijo and len(fijo.data or '') == 40:
        valor = fijo.data
        if '|' in valor[18:35]:
            aviso('008', 'Hay posiciones de material sin codificar (|). Consulta el origen conservado cuando esté disponible.', codigo='008-material')
        idiomas = [v for f in record.get_fields('041') for v in f.get_subfields('a')]
        if idiomas and valor[35:38] not in ('und', 'mul', '|||', '   ') and valor[35:38] != idiomas[0][:3]:
            aviso('041', 'El primer idioma difiere de 008/35–37.', 'a', '041-idioma')
        fechas = [v for f in publicaciones for v in f.get_subfields('c')]
        if fechas and valor[6] == 's' and valor[7:11].isdigit() and not any(valor[7:11] in v for v in fechas):
            aviso('008', 'El año en 07–10 difiere de la fecha de publicación.')
    return issues


def _leer_iso(datos):
    """Verifica el directorio original antes de que pymarc lo regenere."""
    if not datos or len(datos) < 26 or not datos[:5].isdigit() or int(datos[:5]) != len(datos):
        raise ValueError('ISO2709 debe contener exactamente un registro con longitud válida.')
    if not datos[12:17].isdigit():
        raise ValueError('La dirección base del Leader no es numérica.')
    base = int(datos[12:17])
    if (not 25 <= base < len(datos) or (base - 25) % 12 or
            datos[base - 1] != 30 or datos[-1] != 29):
        raise ValueError('Directorio o terminador ISO2709 inválido.')
    datos.decode('utf-8')
    tramos = []
    for pos in range(24, base - 1, 12):
        entrada = datos[pos:pos+12]
        if not entrada.isdigit():
            raise ValueError('Etiqueta, longitud o posición no numérica en el directorio.')
        inicio = base + int(entrada[7:])
        fin = inicio + int(entrada[3:7])
        if inicio >= fin or fin > len(datos) - 1 or datos[fin-1] != 30 or b'\x1e' in datos[inicio:fin-1]:
            raise ValueError('Posición o longitud de campo inválida en el directorio.')
        tramos.append((inicio, fin))
    previo = base
    for inicio, fin in sorted(tramos):
        if inicio != previo:
            raise ValueError('Directorio con campos solapados o espacios sin describir.')
        previo = fin
    if previo != len(datos) - 1:
        raise ValueError('El directorio no describe todos los campos.')
    record = next(iter(MARCReader(datos)), None)
    if record is None:
        raise ValueError('No se pudo decodificar ISO2709.')
    return record


def _leer_xml(xml):
    q = '{' + NAMESPACE + '}'
    root = ET.fromstring(xml)
    if root.tag == q + 'collection' and len(root) == 1:
        root = root[0]
    if root.tag != q + 'record' or not len(root) or root[0].tag != q + 'leader':
        raise ValueError('Se esperaba exactamente un registro MARCXML con Leader y espacio de nombres MARC21/slim.')
    if len(root[0]) or len(root[0].text or '') != 24:
        raise ValueError('Leader MARCXML inválido.')
    for campo in list(root)[1:]:
        if not re.fullmatch('[0-9]{3}', campo.get('tag', '')):
            raise ValueError('Etiqueta MARCXML inválida.')
        if campo.tag == q + 'controlfield':
            if len(campo) or campo.get('tag', '999') >= '010':
                raise ValueError('Campo de control MARCXML inválido.')
        elif campo.tag == q + 'datafield':
            if campo.get('tag', '') < '010' or any(len(campo.get(i, '')) != 1 for i in ('ind1', 'ind2')):
                raise ValueError('Etiqueta o indicadores MARCXML inválidos.')
            if any(s.tag != q + 'subfield' or len(s) or len(s.get('code', '')) != 1 for s in campo):
                raise ValueError('Subcampo MARCXML inválido.')
        else:
            raise ValueError('Elemento inesperado en el registro MARCXML.')
    registros = parse_xml_to_array(StringIO(xml), strict=True)
    if len(registros) != 1:
        raise ValueError('Se esperaba exactamente un registro MARCXML.')
    return registros[0]


def inspeccionar_copias(xml, iso, perfil=None, duplicado=False):
    issues = []
    copias = []
    for campo, leer, valor in [('MARCXML', _leer_xml, xml), ('ISO2709', _leer_iso, iso)]:
        try:
            copias.append(leer(valor))
        except Exception as exc:
            issues.append(Incidencia(ERROR, campo, str(exc)))
    if len(copias) == 2 and copias[0].as_dict() != copias[1].as_dict():
        issues.append(Incidencia(ERROR, 'MARCXML/ISO2709', 'Las copias representan fichas diferentes. Revisa los campos antes de proponer una corrección.'))
    record = copias[0] if copias else None
    if record is not None:
        issues.extend(validar_ficha(record, perfil))
    if duplicado:
        issues.append(Incidencia(AVISO, '001', 'Otro registro del destino tiene el mismo número de control.', regla='Calidad'))
    return record, issues
