"""Conversion de registros Prometeo (Access) a formato MARC21 para Koha."""
from io import BytesIO
from pymarc import Record, Field, Subfield, XMLWriter
from typing import List, Dict, Optional
from datetime import datetime

from access_reader import formatear_fecha_marc


class MarcConverter:
    """Construye registros MARC21 validos para Koha."""

    def __init__(self, agencia_catalogo: str = 'MX-Prometeo', idioma_default: str = 'spa'):
        self.agencia_catalogo = agencia_catalogo
        self.idioma_default = idioma_default

    def _limpiar(self, valor) -> Optional[str]:
        if valor is None:
            return None
        s = str(valor).strip()
        return s if s else None

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
        record.leader = '00000nam a2200000 a 4500'

        ficha_no = str(ficha.get('Ficha_No', ''))

        # 001 - Identificador de control
        record.add_field(Field(tag='001', data=ficha_no))

        # 005 - Fecha y hora de ultima transaccion
        fecha_mod = ficha.get('FechaMod')
        fecha = ficha.get('Fecha')
        dt = fecha_mod or fecha or datetime.now()
        record.add_field(Field(tag='005', data=formatear_fecha_marc(dt)))

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

        # 245 - Titulo principal
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

        # --- Ejemplares -> Campo 952 (Items de Koha) ---
        for ej in ejemplares:
            subfields_952 = []

            # $a = branchcode
            biblioteca = ej.get('Biblioteca')
            branch_code = ''
            if biblioteca is not None:
                bc = str(biblioteca)
                branch_code = branch_mapping.get(bc, bc) if branch_mapping else bc
            if branch_code:
                subfields_952.append(Subfield('a', branch_code))

            # $i = itemcallnumber (signatura/clasificacion)
            if clasificacion:
                subfields_952.append(Subfield('i', clasificacion))

            # $o = barcode / numero de adquisicion
            num_adqui = self._limpiar(ej.get('NumAdqui'))
            if num_adqui:
                subfields_952.append(Subfield('o', num_adqui))

            # $z = itemstatus
            accesible = ej.get('Accesible')
            if accesible is not None:
                estado = str(accesible)
                if status_mapping and estado in status_mapping:
                    estado = status_mapping[estado]
                subfields_952.append(Subfield('z', estado))

            # $c = collection (volumen/tomo)
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
