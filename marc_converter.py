"""Conversion de registros Prometeo (Access) a formato MARC21 para Koha."""
from io import BytesIO
from pymarc import Record, Field, Subfield, XMLWriter
from typing import List, Dict, Optional
from datetime import datetime

from access_reader import formatear_fecha_marc


class MarcConverter:
    """Construye registros MARC21 validos para Koha."""

    def __init__(self, agencia_catalogo: str = 'MX-Prometeo', idioma_default: str = 'spa',
                 item_type_bib: str = 'LIBR0', item_type_item: str = 'LIBR0',
                 homebranch: str = 'ITT', holdingbranch: str = 'ITT'):
        self.agencia_catalogo = agencia_catalogo
        self.idioma_default = idioma_default
        self.item_type_bib = item_type_bib
        self.item_type_item = item_type_item
        self.homebranch = homebranch
        self.holdingbranch = holdingbranch

    def _limpiar(self, valor) -> Optional[str]:
        if valor is None:
            return None
        s = str(valor).strip()
        return s if s else None

    def _generar_008(self, ficha: Dict) -> str:
        """Genera un campo 008 de 40 caracteres basico para Koha."""
        campos = list(' ' * 40)

        fecha = ficha.get('Fecha')
        anio = '0000'
        if fecha is not None:
            try:
                anio = str(fecha.year)
                if len(anio) != 4:
                    anio = '0000'
            except Exception:
                anio = '0000'

        # 0-5: Fecha de ingreso (YYMMDD) - usamos 000000 por defecto
        campos[0:6] = list('000000')
        # 6: Tipo de fecha (s = fecha unica)
        campos[6] = 's'
        # 7-10: Fecha de publicacion (Date 1)
        campos[7:11] = list(anio)
        # 11-14: Fecha de publicacion fin (Date 2) - espacios
        # 15: Tipo de publicacion - espacio
        # 16-17: espacios
        # 18-19: Pais de publicacion (mx = Mexico)
        campos[18:20] = list('mx')
        # 20: espacio
        # 21-23: Idioma (spa)
        campos[21:24] = list('spa')
        # 24-28: espacios
        # 29: Forma de elemento (b = monografia)
        campos[29] = 'b'
        # 30-39: espacios

        return ''.join(campos)

    def ficha_a_record(self, ficha: Dict, ejemplares: List[Dict],
                       branch_mapping: Optional[Dict[str, str]] = None,
                       status_mapping: Optional[Dict[str, str]] = None) -> Record:
        """Crea un objeto Record de pymarc con los datos de la ficha y sus ejemplares."""
        if status_mapping is None:
            status_mapping = {
                '0': 'available',
                '1': 'available',
                '2': 'checkedout',
                '3': 'available',
            }
        if branch_mapping is None:
            branch_mapping = {}

        record = Record()
        # Leader para monografia (libro)
        record.leader = '00000cam a2200000 a 4500'

        ficha_no = str(ficha.get('Ficha_No', ''))

        # 001 - Identificador de control
        record.add_field(Field(tag='001', data=ficha_no))

        # 005 - Fecha y hora de ultima transaccion
        fecha_mod = ficha.get('FechaMod')
        fecha = ficha.get('Fecha')
        dt = fecha_mod or fecha or datetime.now()
        record.add_field(Field(tag='005', data=formatear_fecha_marc(dt)))

        # 008 - Fecha de publicacion y características fisicas
        record.add_field(Field(tag='008', data=self._generar_008(ficha)))

        # 040 - Agencia catalogadora
        record.add_field(Field(
            tag='040',
            indicators=[' ', ' '],
            subfields=[
                Subfield('a', self.agencia_catalogo),
                Subfield('c', self.agencia_catalogo),
            ],
        ))

        # 020 - ISBN
        isbn = self._limpiar(ficha.get('ISBN'))
        if isbn:
            record.add_field(Field(
                tag='020',
                indicators=[' ', ' '],
                subfields=[Subfield('a', isbn)],
            ))

        # 041 - Idioma
        record.add_field(Field(
            tag='041',
            indicators=[' ', ' '],
            subfields=[Subfield('a', self.idioma_default)],
        ))

        # 082 - Clasificación CDD
        clasificacion = self._limpiar(ficha.get('Clasificacion'))
        if clasificacion:
            record.add_field(Field(
                tag='082',
                indicators=[' ', ' '],
                subfields=[Subfield('a', clasificacion)],
            ))

        # 100 - Autor principal
        autor = self._limpiar(ficha.get('Autor'))
        if autor:
            record.add_field(Field(
                tag='100',
                indicators=['1', ' '],
                subfields=[Subfield('a', autor)],
            ))

        # 245 - Titulo principal (obligatorio en Koha)
        titulo = self._limpiar(ficha.get('Titulo'))
        if titulo:
            subfields_245 = [Subfield('a', titulo)]
            if autor:
                subfields_245.append(Subfield('c', autor))
            record.add_field(Field(
                tag='245',
                indicators=['1', '0'],
                subfields=subfields_245,
            ))

        # 942 - Tipo de ítem bibliográfico (requerido por Koha)
        record.add_field(Field(
            tag='942',
            indicators=[' ', ' '],
            subfields=[Subfield('c', self.item_type_bib)],
        ))

        # --- Ejemplares -> Campo 952 (Items de Koha) ---
        for ej in ejemplares:
            subfields_952 = []

            # $a = Homebranch (biblioteca de origen)
            if self.homebranch:
                subfields_952.append(Subfield('a', self.homebranch))

            # $b = Holdingbranch (biblioteca actual donde esta fisicamente)
            if self.holdingbranch:
                subfields_952.append(Subfield('b', self.holdingbranch))

            # $y = Tipo de ítem del ejemplar (reglas de prestamo)
            if self.item_type_item:
                subfields_952.append(Subfield('y', self.item_type_item))

            # $p = Codigo de barras (NumAdqui) - indispensable para prestamos
            num_adqui = self._limpiar(ej.get('NumAdqui'))
            if num_adqui:
                subfields_952.append(Subfield('p', num_adqui))

            # $o = Signatura topografica / Call number (clasificacion)
            if clasificacion:
                subfields_952.append(Subfield('o', clasificacion))

            # $z = Estado del ítem (opcional pero util)
            accesible = ej.get('Accesible')
            if accesible is not None:
                estado = str(accesible)
                if status_mapping and estado in status_mapping:
                    estado = status_mapping[estado]
                subfields_952.append(Subfield('z', estado))

            # $c = Coleccion (volumen/tomo) opcional
            volumen = ej.get('Volumen')
            tomo = ej.get('Tomo')
            partes_c = []
            if volumen is not None:
                partes_c.append('V' + str(volumen))
            if tomo is not None and tomo != 0:
                partes_c.append('T' + str(tomo))
            if partes_c:
                subfields_952.append(Subfield('c', ' '.join(partes_c)))

            if subfields_952:
                record.add_field(Field(
                    tag='952',
                    indicators=[' ', ' '],
                    subfields=subfields_952,
                ))

        return record

    def record_a_marcxml(self, record: Record) -> str:
        buffer = BytesIO()
        writer = XMLWriter(buffer)
        writer.write(record)
        xml = buffer.getvalue().decode('utf-8')
        writer.close()
        return xml

    def record_a_iso2709(self, record: Record) -> bytes:
        return record.as_marc()

    def record_a_json(self, record: Record) -> str:
        import json
        return json.dumps(record.as_dict(), ensure_ascii=False, indent=2)
