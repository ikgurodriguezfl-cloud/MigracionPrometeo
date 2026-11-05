"""Construye registros MARC21 desde reglas declarativas versionadas."""
from io import BytesIO, StringIO
from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree

from pymarc import (
    Field, MARCReader, Record, Subfield, XMLWriter, parse_xml_to_array,
)

from access_reader import formatear_fecha_marc, parsear_etiquetas_marc


class _NonClosingBytesIO(BytesIO):
    def close(self):
        self.flush()


class MarcConverter:
    """Construye registros MARC21 con el mapeo versionado y los datos de origen."""

    CONFIGURACION_DEFAULT = Path(__file__).with_name('mapeo_marc21.json')

    def __init__(self, agencia_catalogo: Optional[str] = None,
                 idioma_default: Optional[str] = None,
                 item_type_bib: Optional[str] = None,
                 item_type_item: Optional[str] = None,
                 homebranch: Optional[str] = None,
                 holdingbranch: Optional[str] = None,
                 mapping_path: Optional[str] = None):
        self.mapping_path = Path(mapping_path) if mapping_path else self.CONFIGURACION_DEFAULT
        self.mapping = self._cargar_mapeo(self.mapping_path)
        self.mapping_version = self.mapping['version']
        self.settings = deepcopy(self.mapping['settings'])
        valores = {
            'agencia_catalogo': agencia_catalogo,
            'idioma_default': idioma_default,
            'item_type_bib': item_type_bib,
            'item_type_item': item_type_item,
            'homebranch': homebranch,
            'holdingbranch': holdingbranch,
        }
        for clave, valor in valores.items():
            if valor is not None:
                self.settings[clave] = valor
        for clave, valor in self.settings.items():
            if not isinstance(valor, str):
                raise ValueError(f'El ajuste MARC {clave} debe ser texto.')
        self.agencia_catalogo = self.settings['agencia_catalogo']
        self.idioma_default = self.settings['idioma_default']
        self.item_type_bib = self.settings['item_type_bib']
        self.item_type_item = self.settings['item_type_item']
        self.homebranch = self.settings['homebranch']
        self.holdingbranch = self.settings['holdingbranch']

    @staticmethod
    def _cargar_mapeo(ruta: Path) -> Dict:
        try:
            documento = json.loads(ruta.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'No se pudo cargar el mapeo MARC21 {ruta}: {exc}') from exc
        if (not isinstance(documento, dict)
                or not isinstance(documento.get('version'), str)
                or not documento['version'].strip()
                or not isinstance(documento.get('settings'), dict)
                or not isinstance(documento.get('mappings'), dict)
                or not isinstance(documento.get('record'), dict)
                or not isinstance(documento['record'].get('leader'), str)
                or not isinstance(documento['record'].get('fields'), list)):
            raise ValueError(f'El archivo de mapeo MARC21 no tiene una estructura válida: {ruta}')
        for regla in documento['record']['fields']:
            if not isinstance(regla, dict) or not isinstance(regla.get('tag'), str):
                raise ValueError('Cada regla MARC debe declarar una etiqueta.')
            if regla.get('repeat') not in (None, 'ejemplares'):
                raise ValueError(f"Repetición no reconocida en la regla {regla['tag']}.")
            if 'indicators' in regla and (
                    not isinstance(regla['indicators'], list)
                    or len(regla['indicators']) != 2
                    or any(not isinstance(value, str) or len(value) != 1
                           for value in regla['indicators'])):
                raise ValueError(f"Indicadores inválidos en la regla {regla['tag']}.")
            if 'source_tag' in regla and (
                    regla['source_tag'] != regla['tag']
                    or not re.fullmatch(r'\d{3}', regla['source_tag'])
                    or 'indicators' not in regla):
                raise ValueError(f"Etiqueta de origen inválida en la regla {regla['tag']}.")
            if regla.get('source_transform') not in (None, 'titulo', 'publicacion', 'idioma'):
                raise ValueError(f"Transformación de origen inválida en la regla {regla['tag']}.")
        status = documento['mappings'].get('status', {})
        if not isinstance(status, dict) or not isinstance(status.get('default', {}), dict):
            raise ValueError('El mapeo de estado debe ser un objeto JSON.')
        return documento

    @classmethod
    def mapping_defaults(cls, mapping_path: Optional[str] = None) -> Dict:
        mapping = cls._cargar_mapeo(Path(mapping_path) if mapping_path else cls.CONFIGURACION_DEFAULT)
        return deepcopy(mapping['mappings'].get('status', {}).get('default', {}))

    def mapping_fingerprint(self, branch_mapping=None, status_mapping=None) -> str:
        """Identifica las reglas y los mapeos/ajustes efectivos de una ejecución."""
        contenido = {
            'rules': self.mapping,
            'settings': self.settings,
            'branch_mapping': branch_mapping or {},
            'status_mapping': status_mapping if status_mapping is not None else self.mapping_defaults(),
        }
        serializado = json.dumps(contenido, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return sha256(serializado.encode('utf-8')).hexdigest()

    @staticmethod
    def _limpiar(valor) -> Optional[str]:
        if valor is None:
            return None
        texto = str(valor).replace('\r\n', '\n').replace('\r', '\n').strip()
        return texto or None

    @staticmethod
    def _incidencia(incidencias, regla, tipo, detalle):
        if incidencias is not None:
            incidencias.append({
                'referencia': regla,
                'mensaje': f'{tipo}: {detalle}',
            })

    def _valor_fuente(self, nombre, datos, descriptor, regla, incidencias):
        valor = datos.get(nombre)
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            politica = descriptor.get('on_missing', 'omit')
            if politica == 'report_omit':
                self._incidencia(incidencias, regla, 'Faltante', f'no se recibió {nombre}; se omitió el dato.')
            return None
        if isinstance(valor, (list, tuple, set)):
            valores = list(valor)
            if len(valores) == 1:
                valor = valores[0]
            elif not valores:
                if descriptor.get('on_missing') == 'report_omit':
                    self._incidencia(incidencias, regla, 'Faltante',
                                     f'no se recibió {nombre}; se omitió el dato.')
                return None
            else:
                if descriptor.get('on_ambiguous', 'report_omit') == 'report_blank':
                    self._incidencia(incidencias, regla, 'Ambiguo', f'{nombre} contiene varios valores.')
                else:
                    self._incidencia(incidencias, regla, 'Ambiguo', f'{nombre} contiene varios valores; se omitió el dato.')
                return None
        elif isinstance(valor, dict):
            self._incidencia(incidencias, regla, 'Ambiguo', f'{nombre} contiene una estructura no escalar.')
            return None
        return valor

    def _resolver(self, descriptor, ficha, ejemplar, incidencias, regla,
                  runtime_mappings):
        if 'literal' in descriptor:
            return self._limpiar(descriptor['literal'])
        if 'setting' in descriptor:
            valor = self.settings.get(descriptor['setting'])
            if valor is None or not str(valor).strip():
                if descriptor.get('on_missing') == 'report_omit':
                    self._incidencia(incidencias, regla, 'Faltante',
                                     f"el ajuste {descriptor['setting']} no está definido.")
                return None
            return str(valor).strip()
        nombre_mapeo = descriptor.get('mapping')
        if 'fallback_setting' in descriptor and runtime_mappings.get(nombre_mapeo) is None:
            return self._limpiar(self.settings.get(descriptor['fallback_setting']))
        nombre_fuente = descriptor.get('source')
        if nombre_fuente is None:
            return None
        datos = (ficha if descriptor.get('scope') == 'ficha'
                 else ejemplar if ejemplar is not None else ficha)
        valor = self._valor_fuente(nombre_fuente, datos, descriptor, regla, incidencias)
        if valor is None:
            return None
        transformacion = descriptor.get('transform', 'text')
        if transformacion == 'iso_date':
            if isinstance(valor, (datetime, date)):
                return valor.strftime('%Y-%m-%d')
            self._incidencia(incidencias, regla, 'No contemplado',
                             f'{nombre_fuente} no contiene una fecha reconocida; se omitió el subcampo.')
            return None
        if transformacion == 'year':
            if isinstance(valor, (datetime, date)):
                return f'{valor.year:04d}'
            self._incidencia(incidencias, regla, 'No contemplado',
                             f'{nombre_fuente} no contiene una fecha reconocida.')
            return None
        if transformacion not in ('text', 'mapped_text'):
            raise ValueError(f'Transformación de subcampo no reconocida: {transformacion}')
        texto = self._limpiar(valor)
        if texto is None:
            return None
        if nombre_mapeo:
            definicion = self.mapping['mappings'].get(nombre_mapeo)
            if not isinstance(definicion, dict):
                raise ValueError(f'No existe el mapeo "{nombre_mapeo}" en el archivo MARC.')
            tabla = runtime_mappings.get(nombre_mapeo)
            if tabla is None:
                tabla = definicion.get('default', {})
            if not isinstance(tabla, dict):
                raise ValueError(f'El mapeo "{nombre_mapeo}" debe ser un objeto JSON.')
            if texto not in tabla:
                if descriptor.get('on_unmapped', definicion.get('on_unmapped')) == 'report_omit':
                    self._incidencia(incidencias, regla, 'No contemplado',
                                     f'{nombre_fuente}={texto!r} no tiene correspondencia; se omitió el subcampo.')
                return None
            destino = tabla[texto]
            if not isinstance(destino, str) or not destino.strip():
                self._incidencia(incidencias, regla, 'No contemplado',
                                 f'la correspondencia para {nombre_fuente}={texto!r} está vacía o no es texto.')
                return None
            return destino.strip()
        return texto

    def _resolver_fecha_005(self, descriptor, ficha, incidencias, regla):
        for nombre in descriptor['sources']:
            fecha = ficha.get(nombre)
            if fecha is None or (isinstance(fecha, str) and not fecha.strip()):
                continue
            if isinstance(fecha, (list, tuple, set)):
                valores = list(fecha)
                if not valores:
                    continue
                if len(valores) == 1:
                    fecha = valores[0]
                else:
                    self._incidencia(incidencias, regla, 'Ambiguo',
                                     f'{nombre} contiene varios valores; se omitió el campo.')
                    return None
            if not isinstance(fecha, (datetime, date)):
                self._incidencia(incidencias, regla, 'No contemplado',
                                 f'{nombre} no contiene una fecha reconocida; se omitió el campo.')
                return None
            return formatear_fecha_marc(fecha)
        if descriptor.get('transform') == 'date_or_now':
            if descriptor.get('on_missing') == 'report_now':
                self._incidencia(incidencias, regla, 'Faltante',
                                 'FechaMod y Fecha no están disponibles; se aplicó la fecha de ejecución autorizada.')
            return formatear_fecha_marc(datetime.now())
        return None

    def _resolver_posiciones(self, descriptor, ficha, incidencias, regla):
        campos = [' '] * descriptor['length']
        for posicion in descriptor['positions']:
            inicio = posicion['start']
            if 'literal' in posicion:
                valor = posicion['literal']
            elif 'source' in posicion:
                fuente = posicion['source']
                valor_original = ficha.get(fuente)
                if isinstance(valor_original, (list, tuple, set)):
                    valores = list(valor_original)
                    if len(valores) == 1:
                        valor_original = valores[0]
                    elif not valores:
                        valor_original = None
                    else:
                        if posicion.get('on_ambiguous') == 'report_blank':
                            self._incidencia(incidencias, regla, 'Ambiguo',
                                             f'{fuente} contiene varios valores; se dejaron espacios.')
                        ancho = posicion.get('width', 4)
                        campos[inicio:inicio + ancho] = [' '] * ancho
                        continue
                if valor_original is None or (
                        isinstance(valor_original, str) and not valor_original.strip()):
                    valor = (posicion.get('missing_value', '')
                             if posicion.get('on_missing') == 'literal' else '')
                    if posicion.get('report_missing'):
                        self._incidencia(incidencias, regla, 'Faltante',
                                         f'{fuente} no está disponible; se aplicó el valor autorizado {valor!r}.')
                elif posicion.get('transform') == 'year':
                    if isinstance(valor_original, (datetime, date)):
                        valor = f'{valor_original.year:04d}'
                    else:
                        self._incidencia(incidencias, regla, 'No contemplado',
                                         f'{fuente} no contiene una fecha reconocida; se dejaron espacios.')
                        valor = ''
                else:
                    raise ValueError(
                        f"Transformación de posición no reconocida: {posicion.get('transform')}"
                    )
            else:
                raise ValueError(f'Posición incompleta en la regla {regla}.')
            ancho = posicion.get('width', len(valor))
            campos[inicio:inicio + ancho] = list(valor.ljust(ancho)[:ancho])
        return ''.join(campos)

    def _resolver_subcampo(self, descriptor, ficha, ejemplar, incidencias,
                           regla, runtime_mappings):
        transformacion = descriptor.get('transform')
        if transformacion == 'volume_tomo':
            partes = []
            for parte in descriptor['parts']:
                fuente = parte['source']
                valor = ejemplar.get(fuente)
                if valor is None:
                    continue
                if isinstance(valor, (list, tuple, set)):
                    valores = list(valor)
                    if len(valores) > 1:
                        if descriptor.get('on_ambiguous') == 'report_omit':
                            self._incidencia(incidencias, regla, 'Ambiguo',
                                             f'{fuente} contiene varios valores; se omitió el subcampo.')
                        return None
                    valor = valores[0] if valores else None
                if valor is None:
                    continue
                if valor == 0 and not parte.get('include_zero', True):
                    continue
                partes.append(parte['prefix'] + str(valor))
            if not partes and descriptor.get('on_missing') == 'report_omit':
                self._incidencia(incidencias, regla, 'Faltante',
                                 'Volumen y Tomo no están disponibles; se omitió el subcampo.')
            return ' '.join(partes) or None
        return self._resolver(descriptor, ficha, ejemplar, incidencias, regla,
                              runtime_mappings)

    def _datos_fijos_access(self, ficha, incidencias):
        """Conserva posiciones conocidas y usa códigos de desconocido en las demás."""
        campos = list('|' * 40)
        campos[6:18] = list('nuuuuuuuuxx ')
        campos[35:40] = list(self.settings['idioma_default'][:3].ljust(3, '|') + ' u')
        original = ficha.get('DatosFijos')
        longitud_original = len(original) if isinstance(original, str) else 0
        if isinstance(original, str) and original:
            normalizado = original.replace('^', ' ')
            campos[:min(40, len(normalizado))] = list(normalizado[:40])
            if len(normalizado) > 40:
                self._incidencia(incidencias, '008', 'Ambiguo',
                                 'DatosFijos supera 40 posiciones; el original se conserva en 887.')
        elif original is not None and not isinstance(original, str):
            self._incidencia(incidencias, '008', 'Ambiguo',
                             'DatosFijos no es texto; se conservaron los códigos de desconocido.')
        elif not original:
            self._incidencia(incidencias, '008', 'Faltante',
                             'No se recibió DatosFijos; la fecha de publicación queda desconocida.')
        fecha_ingreso = ''.join(campos[:6])
        try:
            datetime.strptime(fecha_ingreso, '%y%m%d')
        except ValueError:
            fecha = ficha.get('Fecha')
            if not isinstance(fecha, (datetime, date)):
                fecha = datetime.now()
            campos[:6] = list(fecha.strftime('%y%m%d'))
        if campos[6] not in 'bcdeikmnpqrst u'.replace(' ', ''):
            campos[6] = 'n'
        for posicion in range(7, 15):
            if campos[posicion] not in '0123456789u |':
                campos[posicion] = 'u'
        pais = ''.join(campos[15:18]).lower()
        campos[15:18] = list(pais if re.fullmatch(r'[a-z]{2}[a-z ]', pais) else 'xx ')
        if campos[6] == 's' and ''.join(campos[7:11]) in ('    ', '0000', '||||'):
            campos[6:15] = list('nuuuuuuuu')
        etiquetas = ficha.get('EtiquetasMARC')
        idiomas = [codigo
                   for campo in parsear_etiquetas_marc(etiquetas if isinstance(etiquetas, str) else None)
                   if campo['tag'] == '041'
                   for codigo in self._idiomas_access(campo['content'])]
        idioma = ''.join(campos[35:38]).lower()
        permitidos = self.mapping.get('access_source', {}).get('language_codes', '').split()
        valido = bool(re.fullmatch(r'[a-z]{3}', idioma) and (not permitidos or idioma in permitidos))
        if longitud_original < 38 or not valido:
            campos[35:38] = list(idiomas[0] if idiomas else self.settings['idioma_default'][:3].ljust(3, '|'))
            if longitud_original >= 38 and idioma.strip(' |'):
                self._incidencia(incidencias, '008', 'Ambiguo',
                                 'El idioma de DatosFijos requiere revisión; el original se conserva en 887.')
        else:
            campos[35:38] = list(idioma)
            if idiomas and idioma not in ('mul', 'und') and idioma != idiomas[0]:
                self._incidencia(incidencias, '041', 'Ambiguo',
                                 'Los idiomas de DatosFijos y EtiquetasMARC no coinciden; se conservaron para revisión.')
        return ''.join(campos)

    def _idiomas_access(self, contenido):
        normalizado = re.sub(r'[\s.,;/-]', '', contenido).lower()
        if not re.fullmatch(r'(?:[a-z]{3})+', normalizado):
            return []
        codigos = [normalizado[inicio:inicio + 3] for inicio in range(0, len(normalizado), 3)]
        permitidos = self.mapping.get('access_source', {}).get('language_codes', '').split()
        if permitidos and any(codigo not in permitidos for codigo in codigos):
            return []
        return codigos

    def _subcampos_access(self, contenido, transformacion, tag, incidencias):
        contenido = contenido.replace('\r\n', '\n').replace('\r', '\n')
        # Si el origen ya expresa subcampos MARC, se respetan sus límites.
        if '\x1f' in contenido:
            partes = contenido.split('\x1f')
            if not partes[0] and all(len(parte) > 1 and re.fullmatch(r'[a-z0-9]', parte[0])
                                     for parte in partes[1:]):
                return [Subfield(parte[0], parte[1:]) for parte in partes[1:]]
            self._incidencia(incidencias, tag, 'Ambiguo',
                             'Los subcampos de origen no son válidos; el original se conserva en 887.')
            return []
        if transformacion == 'titulo':
            titulo, separador, responsabilidad = contenido.partition(' /')
            subcampos = [Subfield('a', titulo + (' /' if separador else ''))]
            if separador and responsabilidad.strip():
                subcampos.append(Subfield('c', responsabilidad.strip()))
            return subcampos
        if transformacion == 'publicacion':
            lugar, separador, resto = contenido.partition(':')
            if not separador or not lugar.strip() or not resto.strip():
                self._incidencia(incidencias, tag, 'Ambiguo',
                                 'La publicación no separa lugar y editorial; se conserva completa en $a y en 887.')
                return [Subfield('a', contenido)]
            editorial, coma, fecha = resto.rpartition(',')
            subcampos = [Subfield('a', lugar.rstrip() + ' :')]
            if coma and re.match(r'\s*\[?[cp]?\s*\d{4}', fecha, re.IGNORECASE):
                subcampos.extend([Subfield('b', editorial.strip() + ','), Subfield('c', fecha.strip())])
            else:
                subcampos.append(Subfield('b', resto.strip()))
            return subcampos
        if transformacion == 'idioma':
            idiomas = self._idiomas_access(contenido)
            if idiomas:
                return [Subfield('a', idioma) for idioma in idiomas]
            self._incidencia(incidencias, tag, 'Ambiguo',
                             'El idioma no coincide con los códigos contemplados; se conserva en 887 para revisión.')
            return []
        return [Subfield('a', contenido)]

    def _agregar_regla(self, record, regla, ficha, ejemplar, incidencias,
                       runtime_mappings):
        tag = regla['tag']
        referencia = tag
        if 'source_tag' in regla:
            originales = [campo for campo in runtime_mappings.get('source_fields', [])
                          if campo['tag'] == regla['source_tag'] and campo['content']]
            if originales:
                for original in originales:
                    subcampos = self._subcampos_access(
                        original['content'], regla.get('source_transform'), tag, incidencias)
                    if subcampos:
                        record.add_field(Field(tag=tag, indicators=regla['indicators'], subfields=subcampos))
                return
        if 'data' in regla:
            descriptor = regla['data']
            transformacion = descriptor.get('transform')
            if transformacion == 'date_or_now':
                contenido = self._resolver_fecha_005(descriptor, ficha, incidencias, tag)
            elif transformacion == 'positions':
                contenido = self._resolver_posiciones(descriptor, ficha, incidencias, tag)
            elif transformacion == 'prometeo_008':
                contenido = self._datos_fijos_access(ficha, incidencias)
            else:
                contenido = self._resolver(descriptor, ficha, ejemplar, incidencias,
                                           tag, runtime_mappings)
            if contenido is not None:
                record.add_field(Field(tag=tag, data=contenido))
            return

        subcampos = []
        for descriptor in regla.get('subfields', []):
            codigo = descriptor['code']
            subcampo_ref = f'{tag}${codigo}'
            contenido = self._resolver_subcampo(
                descriptor, ficha, ejemplar, incidencias, subcampo_ref,
                runtime_mappings,
            )
            if contenido is not None:
                subcampos.append(Subfield(codigo, contenido))
        if subcampos:
            record.add_field(Field(
                tag=tag,
                indicators=regla['indicators'],
                subfields=subcampos,
            ))

    def ficha_a_record(self, ficha: Dict, ejemplares: List[Dict],
                       branch_mapping: Optional[Dict[str, str]] = None,
                       status_mapping: Optional[Dict[str, str]] = None,
                       incidencias: Optional[List[Dict[str, str]]] = None) -> Record:
        """Convierte una ficha aplicando exclusivamente las reglas del JSON."""
        record = Record()
        record.leader = self.mapping['record']['leader']
        origen = self.mapping.get('access_source')
        campos_origen = []
        if origen:
            valor = ficha.get(origen['field'])
            if valor is not None and not isinstance(valor, str):
                self._incidencia(incidencias, origen['field'], 'Ambiguo',
                                 'Las etiquetas de origen no son texto; requieren revisión.')
            else:
                campos_origen = parsear_etiquetas_marc(valor)
                if valor and not campos_origen:
                    self._incidencia(incidencias, origen['field'], 'No contemplado',
                                     'No se reconoció el formato de etiquetas; el original se conserva en 887.')
        runtime_mappings = {'status': status_mapping, 'branch': branch_mapping,
                            'source_fields': campos_origen}
        for regla in self.mapping['record']['fields']:
            if regla.get('repeat') == 'ejemplares':
                for ejemplar in ejemplares:
                    self._agregar_regla(record, regla, ficha, ejemplar,
                                        incidencias, runtime_mappings)
            else:
                self._agregar_regla(record, regla, ficha, None, incidencias,
                                    runtime_mappings)
        if origen:
            datos_originales = {nombre: ficha[nombre] for nombre in origen['preserve_fields']
                                if ficha.get(nombre) is not None}
            if datos_originales:
                record.add_ordered_field(Field(tag='887', indicators=[' ', ' '], subfields=[
                    Subfield('a', json.dumps(datos_originales, ensure_ascii=False, default=str)),
                    Subfield('2', 'prometeo'),
                ]))
            material = ficha.get('TipoMaterial')
            if material is not None and str(material) != '0':
                self._incidencia(incidencias, 'TipoMaterial', 'No contemplado',
                                 f'El tipo {material!r} requiere confirmar su correspondencia MARC; se conserva en 887.')
            reconocidos = {regla.get('source_tag') for regla in self.mapping['record']['fields']}
            for tag in sorted({campo['tag'] for campo in campos_origen
                               if campo['content']} - reconocidos - set(origen['local_tags'])):
                self._incidencia(incidencias, tag, 'No contemplado',
                                 'La etiqueta no tiene correspondencia; su contenido se conserva en 887.')
        if record.get('245') and not any(record.get_fields(tag) for tag in ('100', '110', '111', '130')):
            record['245'].indicator1 = '0'
        return record

    def record_a_marcxml(self, record: Record) -> str:
        iso2709 = record.as_marc()
        registro_normalizado = next(
            iter(MARCReader(BytesIO(iso2709), to_unicode=True)), None,
        )
        if registro_normalizado is None:
            raise ValueError('No se pudo normalizar el registro MARC para exportarlo.')
        buffer = _NonClosingBytesIO()
        writer = XMLWriter(buffer)
        try:
            writer.write(registro_normalizado)
        finally:
            writer.close()
        marcxml = buffer.getvalue().decode('utf-8')
        try:
            ElementTree.fromstring(marcxml)
            registros_xml = parse_xml_to_array(StringIO(marcxml), strict=True)
        except Exception as exc:
            raise ValueError(f'No se pudo generar un MARCXML válido: {exc}') from exc
        if (len(registros_xml) != 1
                or registros_xml[0].as_dict() != registro_normalizado.as_dict()):
            raise ValueError(
                'El MARCXML generado no coincide con el registro ISO2709.'
            )
        return marcxml

    def record_a_iso2709(self, record: Record) -> bytes:
        return record.as_marc()

    def record_a_json(self, record: Record) -> str:
        return json.dumps(record.as_dict(), ensure_ascii=False, indent=2)
