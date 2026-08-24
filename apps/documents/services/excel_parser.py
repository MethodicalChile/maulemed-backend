import csv
import io
from datetime import date, datetime

import openpyxl

from .parsers.flujo_caja_ppto_parser import (
    flujo_caja_ppto_parser,
)
from .parsers.logs_parser import (
    logs_parser,
)
from .parsers.reporte_parser import (
    reporte_parser,
)

DOCUMENT_TYPE_FLUJO_CAJA_PPTO = "flujo_caja_ppto"
DOCUMENT_TYPE_LOGS = "logs"
DOCUMENT_TYPE_REPORTE = "reporte"


class ExcelParser:
    """
    Parser general para archivos de planilla.

    Soporta:
    - XLSX
    - CSV

    Responsabilidades:
    - Leer físicamente el archivo.
    - Extraer hojas.
    - Serializar valores.
    - Mantener la matriz original.
    - Detectar encabezados genéricamente.
    - Delegar a parsers específicos según document_type.

    Los datos genéricos siempre se conservan para
    poder mostrarlos posteriormente en la subvista
    "Datos extraídos".
    """

    def parse(
        self,
        uploaded_file,
        extension,
        document_type=None,
    ):
        uploaded_file.seek(0)

        try:
            if extension == ".csv":
                generic_data = self._parse_csv(
                    uploaded_file
                )

            elif extension == ".xlsx":
                generic_data = self._parse_xlsx(
                    uploaded_file
                )

            elif extension == ".xls":
                raise ValueError(
                    "El formato XLS antiguo todavía no está soportado. "
                    "Convierte el archivo a XLSX."
                )

            else:
                raise ValueError(
                    f"Formato de planilla no soportado: {extension}"
                )

            generic_data[
                "document_type"
            ] = document_type

            parsed_data = (
                self._parse_document(
                    document_type=document_type,
                    spreadsheet_data=generic_data,
                )
            )

            return {
                "type": "spreadsheet",
                "filename": generic_data[
                    "filename"
                ],
                "format": generic_data[
                    "format"
                ],
                "document_type": document_type,

                # Datos especializados que serán
                # utilizados para el dashboard.
                "data": parsed_data,

                # Datos genéricos/originales que
                # mantendremos para la pestaña
                # "Datos extraídos".
                "raw_data": generic_data,
            }

        finally:
            uploaded_file.seek(0)

    # =========================================================
    # PARSER ESPECÍFICO
    # =========================================================

    def _parse_document(
        self,
        document_type,
        spreadsheet_data,
    ):
        """
        Selecciona el parser específico según
        el tipo lógico detectado por DocumentParser.
        """

        if (
            document_type
            == DOCUMENT_TYPE_FLUJO_CAJA_PPTO
        ):
            return flujo_caja_ppto_parser.parse(
                spreadsheet_data
            )

        if (
            document_type
            == DOCUMENT_TYPE_LOGS
        ):
            return logs_parser.parse(
                spreadsheet_data
            )

        if (
            document_type
            == DOCUMENT_TYPE_REPORTE
        ):
            return reporte_parser.parse(
                spreadsheet_data
            )

        return self._generic_specialized_result(
            document_type,
            spreadsheet_data,
        )

    def _generic_specialized_result(
        self,
        document_type,
        spreadsheet_data,
    ):
        """
        Fallback temporal para documentos que todavía
        no poseen parser especializado.

        Esto permite seguir visualizando el archivo
        aunque su dashboard específico todavía no
        esté implementado.
        """

        return {
            "document_type": (
                document_type
                or "unknown"
            ),

            "title": (
                self._get_document_title(
                    document_type
                )
            ),

            "dashboard": {
                "metrics": (
                    self._build_generic_metrics(
                        spreadsheet_data
                    )
                ),

                "charts": [],

                "tables": [],

                "summary": {
                    "title": "Resumen",
                    "text": (
                        "El documento fue procesado "
                        "correctamente, pero todavía "
                        "no posee un dashboard "
                        "especializado."
                    ),
                },
            },
        }

    def _get_document_title(
        self,
        document_type,
    ):
        labels = {
            DOCUMENT_TYPE_FLUJO_CAJA_PPTO: (
                "Flujo de Caja y Presupuesto"
            ),

            DOCUMENT_TYPE_LOGS: (
                "Logs"
            ),

            DOCUMENT_TYPE_REPORTE: (
                "Reporte"
            ),
        }

        return labels.get(
            document_type,
            "Documento",
        )

    def _build_generic_metrics(
        self,
        spreadsheet_data,
    ):
        sheets = spreadsheet_data.get(
            "sheets",
            [],
        )

        return [
            {
                "key": "sheet_count",
                "label": "Hojas",
                "value": spreadsheet_data.get(
                    "sheet_count",
                    0,
                ),
                "format": "number",
            },
            {
                "key": "total_rows",
                "label": "Filas",
                "value": spreadsheet_data.get(
                    "total_rows",
                    0,
                ),
                "format": "number",
            },
            {
                "key": "max_columns",
                "label": "Máximo de columnas",
                "value": max(
                    (
                        sheet.get(
                            "column_count",
                            0,
                        )
                        for sheet in sheets
                    ),
                    default=0,
                ),
                "format": "number",
            },
        ]

    # =========================================================
    # XLSX
    # =========================================================

    def _parse_xlsx(
        self,
        uploaded_file,
    ):
        workbook = openpyxl.load_workbook(
            uploaded_file,
            read_only=True,
            data_only=True,
        )

        try:
            sheets = []

            for worksheet in workbook.worksheets:
                rows = []

                for row in worksheet.iter_rows(
                    values_only=True
                ):
                    serialized_row = [
                        self._serialize_value(
                            value
                        )
                        for value in row
                    ]

                    rows.append(
                        serialized_row
                    )

                rows = (
                    self._remove_empty_trailing_rows(
                        rows
                    )
                )

                sheets.append(
                    self._build_sheet(
                        name=worksheet.title,
                        rows=rows,
                    )
                )

            return {
                "type": "spreadsheet",

                "filename": (
                    uploaded_file.name
                ),

                "format": "xlsx",

                "sheet_count": len(
                    sheets
                ),

                "sheet_names": [
                    sheet[
                        "name"
                    ]
                    for sheet in sheets
                ],

                "total_rows": sum(
                    sheet[
                        "row_count"
                    ]
                    for sheet in sheets
                ),

                "sheets": sheets,
            }

        finally:
            workbook.close()

    # =========================================================
    # CSV
    # =========================================================

    def _parse_csv(
        self,
        uploaded_file,
    ):
        raw_bytes = (
            uploaded_file.read()
        )

        text = self._decode_csv(
            raw_bytes
        )

        dialect = (
            self._detect_csv_dialect(
                text
            )
        )

        reader = csv.reader(
            io.StringIO(
                text
            ),
            dialect,
        )

        rows = [
            [
                self._serialize_value(
                    value
                )
                for value in row
            ]
            for row in reader
        ]

        rows = (
            self._remove_empty_trailing_rows(
                rows
            )
        )

        sheet = self._build_sheet(
            name="CSV",
            rows=rows,
        )

        return {
            "type": "spreadsheet",

            "filename": (
                uploaded_file.name
            ),

            "format": "csv",

            "sheet_count": 1,

            "sheet_names": [
                "CSV"
            ],

            "total_rows": sheet[
                "row_count"
            ],

            "sheets": [
                sheet
            ],
        }

    # =========================================================
    # CONSTRUCCIÓN DE HOJAS
    # =========================================================

    def _build_sheet(
        self,
        name,
        rows,
    ):
        """
        Mantiene la información completa de la hoja
        y además intenta identificar automáticamente
        una fila de encabezados.

        Nunca eliminamos las filas originales porque
        los parsers especializados pueden necesitarlas.
        """

        header_row_index = (
            self._detect_header_row(
                rows
            )
        )

        headers = []
        data_rows = []

        if (
            header_row_index
            is not None
        ):
            headers = rows[
                header_row_index
            ]

            data_rows = rows[
                header_row_index + 1:
            ]

        non_empty_row_count = sum(
            1
            for row in rows
            if self._row_has_data(
                row
            )
        )

        return {
            "name": name,

            "row_count": len(
                rows
            ),

            "non_empty_row_count": (
                non_empty_row_count
            ),

            "column_count": (
                self._column_count(
                    rows
                )
            ),

            # Matriz completa.
            "rows": rows,

            # Resultado heurístico.
            "header_row_index": (
                header_row_index
            ),

            "headers": headers,

            "data_rows": data_rows,

            "data_row_count": len(
                data_rows
            ),
        }

    # =========================================================
    # DETECCIÓN GENÉRICA DE HEADER
    # =========================================================

    def _detect_header_row(
        self,
        rows,
    ):
        """
        Busca una fila que probablemente corresponda
        a encabezados.

        Solo es utilizada para la visualización
        genérica.

        Los parsers especializados trabajan
        directamente sobre rows.
        """

        if not rows:
            return None

        max_rows_to_check = min(
            len(
                rows
            ),
            30,
        )

        best_index = None
        best_score = -1

        for index in range(
            max_rows_to_check
        ):
            row = rows[
                index
            ]

            non_empty = [
                value
                for value in row
                if not self._is_empty(
                    value
                )
            ]

            if len(
                non_empty
            ) < 2:
                continue

            text_values = sum(
                1
                for value in non_empty
                if isinstance(
                    value,
                    str,
                )
                and value.strip()
            )

            numeric_values = sum(
                1
                for value in non_empty
                if isinstance(
                    value,
                    (
                        int,
                        float,
                    ),
                )
                and not isinstance(
                    value,
                    bool,
                )
            )

            unique_values = len(
                {
                    str(
                        value
                    )
                    .strip()
                    .lower()
                    for value in non_empty
                }
            )

            score = 0

            score += (
                len(
                    non_empty
                )
                * 2
            )

            score += (
                text_values
                * 3
            )

            score += (
                unique_values
            )

            score -= (
                numeric_values
                * 2
            )

            if (
                score
                > best_score
            ):
                best_score = score
                best_index = index

        return best_index

    # =========================================================
    # UTILIDADES
    # =========================================================

    def _column_count(
        self,
        rows,
    ):
        if not rows:
            return 0

        return max(
            len(
                row
            )
            for row in rows
        )

    def _remove_empty_trailing_rows(
        self,
        rows,
    ):
        while rows:
            last_row = rows[
                -1
            ]

            if self._row_has_data(
                last_row
            ):
                break

            rows.pop()

        return rows

    def _row_has_data(
        self,
        row,
    ):
        return any(
            not self._is_empty(
                value
            )
            for value in row
        )

    def _is_empty(
        self,
        value,
    ):
        if value is None:
            return True

        if isinstance(
            value,
            str,
        ):
            return (
                value.strip()
                == ""
            )

        return False

    def _serialize_value(
        self,
        value,
    ):
        if value is None:
            return ""

        if isinstance(
            value,
            (
                datetime,
                date,
            ),
        ):
            return value.isoformat()

        if isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ):
            return value

        return str(
            value
        )

    # =========================================================
    # CSV
    # =========================================================

    def _decode_csv(
        self,
        raw_bytes,
    ):
        encodings = [
            "utf-8-sig",
            "utf-8",
            "latin-1",
            "cp1252",
        ]

        for encoding in encodings:
            try:
                return (
                    raw_bytes.decode(
                        encoding
                    )
                )

            except UnicodeDecodeError:
                continue

        raise ValueError(
            "No fue posible determinar "
            "la codificación del archivo CSV."
        )

    def _detect_csv_dialect(
        self,
        text,
    ):
        sample = text[
            :10000
        ]

        try:
            return (
                csv.Sniffer().sniff(
                    sample,
                    delimiters=",;\t|",
                )
            )

        except csv.Error:
            return csv.excel


excel_parser = ExcelParser()