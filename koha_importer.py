"""Parser real de resultados y logs de importación devueltos por Koha."""
import csv
import json
import os
import re
from typing import Dict, List, Tuple


class KohaResponseParser:
    """
    Procesa archivos reales de resultado de importación de Koha (CSV, TSV, JSON o log
    de bulkmarcimport) y los concilia contra la salida aprobada del lote en MySQL.
    """

    @staticmethod
    def parsear_archivo(ruta_archivo: str) -> Tuple[List[Dict], int, int]:
        """
        Lee el archivo de respuesta de Koha y devuelve:
        (lista_registros, total_aceptados_reportados, total_rechazados_reportados)
        """
        if not os.path.isfile(ruta_archivo):
            raise FileNotFoundError(f"No se encontró el archivo de respuesta de Koha: {ruta_archivo}")

        ext = os.path.splitext(ruta_archivo)[1].lower()
        if ext == ".json":
            return KohaResponseParser._parsear_json(ruta_archivo)
        if ext in (".csv", ".tsv"):
            return KohaResponseParser._parsear_csv(ruta_archivo, "\t" if ext == ".tsv" else ",")
        return KohaResponseParser._parsear_log_texto(ruta_archivo)

    @staticmethod
    def _parsear_csv(ruta: str, delimitador: str) -> Tuple[List[Dict], int, int]:
        registros = []
        aceptados = 0
        rechazados = 0

        with open(ruta, "r", encoding="utf-8-sig", newline="") as f:
            lector = csv.DictReader(f, delimiter=delimitador)
            if not lector.fieldnames:
                raise ValueError("El archivo CSV de Koha está vacío o no tiene encabezados.")

            # Normalizar nombres de columnas habituales de reportes de etapa de Koha
            cols = {c.strip().lower(): c for c in lector.fieldnames}
            col_id = (
                cols.get("id_ficha")
                or cols.get("id_control")
                or cols.get("001")
                or cols.get("record_id")
                or cols.get("control_number")
            )
            col_status = (
                cols.get("status")
                or cols.get("estado")
                or cols.get("resultado")
                or cols.get("import_status")
            )
            col_biblio = (
                cols.get("biblionumber")
                or cols.get("biblio_id")
                or cols.get("koha_id")
            )
            col_error = (
                cols.get("error")
                or cols.get("causa")
                or cols.get("reason")
                or cols.get("message")
                or cols.get("detalle")
            )

            if not col_id or not col_status:
                raise ValueError(
                    "El CSV de Koha debe incluir al menos las columnas de identificador "
                    "(id_control / 001 / id_ficha) y estado (status / resultado)."
                )

            for fila in lector:
                raw_id = str(fila.get(col_id, "")).strip()
                if not raw_id:
                    continue
                id_num = KohaResponseParser._extraer_entero(raw_id)
                if id_num is None:
                    raise ValueError(f"Identificador de control no numérico en respuesta Koha: {raw_id!r}")

                estado_raw = str(fila.get(col_status, "")).strip().upper()
                es_aceptado = estado_raw in ("IMPORTED", "ACEPTADO", "OK", "ADDED", "SUCCESS", "1")
                resultado = "ACEPTADO" if es_aceptado else "RECHAZADO"

                biblionumber = None
                if col_biblio and fila.get(col_biblio):
                    biblionumber = KohaResponseParser._extraer_entero(str(fila[col_biblio]))

                causa = None
                if resultado == "RECHAZADO":
                    causa = (
                        str(fila.get(col_error, "")).strip()
                        if col_error and fila.get(col_error)
                        else f"Rechazado por Koha (estado reportado: {estado_raw or 'ERROR'})"
                    )
                    rechazados += 1
                else:
                    aceptados += 1

                registros.append({
                    "id_ficha_acceso": id_num,
                    "id_control": raw_id,
                    "resultado": resultado,
                    "biblionumber_koha": biblionumber,
                    "causa_rechazo": causa,
                })

        return registros, aceptados, rechazados

    @staticmethod
    def _parsear_json(ruta: str) -> Tuple[List[Dict], int, int]:
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)

        items = data.get("records", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("El JSON de Koha debe contener una lista de registros.")

        registros = []
        aceptados = 0
        rechazados = 0
        for item in items:
            raw_id = str(item.get("id_ficha_acceso") or item.get("id_control") or item.get("001") or "").strip()
            id_num = KohaResponseParser._extraer_entero(raw_id)
            if id_num is None:
                continue
            estado_raw = str(item.get("resultado") or item.get("status") or "").strip().upper()
            es_aceptado = estado_raw in ("IMPORTED", "ACEPTADO", "OK", "ADDED", "SUCCESS")
            resultado = "ACEPTADO" if es_aceptado else "RECHAZADO"
            if es_aceptado:
                aceptados += 1
            else:
                rechazados += 1
            registros.append({
                "id_ficha_acceso": id_num,
                "id_control": raw_id,
                "resultado": resultado,
                "biblionumber_koha": KohaResponseParser._extraer_entero(str(item.get("biblionumber") or "")),
                "causa_rechazo": None if es_aceptado else (item.get("causa_rechazo") or item.get("error") or "Error de validación MARC en Koha"),
            })
        return registros, aceptados, rechazados

    @staticmethod
    def _parsear_log_texto(ruta: str) -> Tuple[List[Dict], int, int]:
        """
        Soporta salida textual de bulkmarcimport.pl o logs de etapa de Koha.
        Ejemplos soportados:
          001=1042 | IMPORTED | biblionumber=5812
          001=1043 | REJECTED | Invalid 952$p duplicate barcode
        """
        registros = []
        aceptados = 0
        rechazados = 0
        patron = re.compile(
            r"(?:001|id|ficha)[=:\s#]+(\d+).*?\b(IMPORTED|ACEPTADO|OK|REJECTED|RECHAZADO|ERROR)\b(?:.*?(?:biblionumber|biblio)[=:\s]+(\d+))?(?:.*?[\|\-:]\s*(.+))?$",
            re.IGNORECASE,
        )
        with open(ruta, "r", encoding="utf-8", errors="replace") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                m = patron.search(linea)
                if not m:
                    continue
                id_num = int(m.group(1))
                estado_raw = m.group(2).upper()
                es_aceptado = estado_raw in ("IMPORTED", "ACEPTADO", "OK")
                resultado = "ACEPTADO" if es_aceptado else "RECHAZADO"
                biblio = int(m.group(3)) if m.group(3) else None
                causa = None if es_aceptado else (m.group(4).strip() if m.group(4) else "Rechazado durante bulkmarcimport en Koha")

                if es_aceptado:
                    aceptados += 1
                else:
                    rechazados += 1

                registros.append({
                    "id_ficha_acceso": id_num,
                    "id_control": str(id_num),
                    "resultado": resultado,
                    "biblionumber_koha": biblio,
                    "causa_rechazo": causa,
                })

        if not registros:
            raise ValueError(
                "No se reconocieron líneas de resultado de Koha en el archivo de texto. "
                "Usa el reporte CSV/JSON exportado por Koha o el log de bulkmarcimport."
            )
        return registros, aceptados, rechazados

    @staticmethod
    def _extraer_entero(valor: str):
        digitos = re.search(r"\d+", valor or "")
        return int(digitos.group(0)) if digitos else None