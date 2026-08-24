from pathlib import Path
import re
import unicodedata

from rest_framework.exceptions import ValidationError

from .pdf_parser import pdf_parser
from .excel_parser import excel_parser


MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
}


DOCUMENT_TYPE_DETALLE_CAJA = "detalle_caja"
DOCUMENT_TYPE_FLUJO_CAJA_PPTO = "flujo_caja_ppto"
DOCUMENT_TYPE_LOGS = "logs"
DOCUMENT_TYPE_REPORTE = "reporte"
DOCUMENT_TYPE_UNKNOWN = "unknown"


class DocumentParser:

    def parse(self, uploaded_file):
        self._validate_file(uploaded_file)

        extension = self._get_extension(
            uploaded_file.name
        )

        document_type = self._detect_document_type(
            uploaded_file.name
        )

        if document_type == DOCUMENT_TYPE_UNKNOWN:
            raise ValidationError(
                {
                    "file": (
                        "No se pudo identificar el tipo de documento. "
                        "Los nombres soportados actualmente son: "
                        "DETALLE-CAJA, FLUJO-CAJA-PPTO, LOGS y REPORTE."
                    )
                }
            )

        if extension == ".pdf":
            parsed_data = self._parse_pdf(
                uploaded_file,
                document_type,
            )

        elif extension in {
            ".xlsx",
            ".xls",
            ".csv",
        }:
            parsed_data = self._parse_spreadsheet(
                uploaded_file,
                document_type,
            )

        else:
            raise ValidationError(
                {
                    "file": (
                        "El tipo de archivo "
                        "no está soportado."
                    )
                }
            )

        return self._build_response(
            uploaded_file=uploaded_file,
            extension=extension,
            document_type=document_type,
            parsed_data=parsed_data,
        )

    def _validate_file(
        self,
        uploaded_file,
    ):
        if not uploaded_file:
            raise ValidationError(
                {
                    "file": (
                        "Debes enviar un archivo."
                    )
                }
            )

        if not getattr(
            uploaded_file,
            "name",
            None,
        ):
            raise ValidationError(
                {
                    "file": (
                        "El archivo no tiene "
                        "un nombre válido."
                    )
                }
            )

        if uploaded_file.size == 0:
            raise ValidationError(
                {
                    "file": (
                        "El archivo está vacío."
                    )
                }
            )

        if uploaded_file.size > MAX_FILE_SIZE:
            raise ValidationError(
                {
                    "file": (
                        "El archivo supera el "
                        "tamaño máximo permitido "
                        "de 50 MB."
                    )
                }
            )

        extension = self._get_extension(
            uploaded_file.name
        )

        if extension not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                {
                    "file": (
                        "Formato no soportado. "
                        "Los formatos permitidos "
                        "son PDF, XLSX, XLS y CSV."
                    )
                }
            )

        self._validate_document_extension(
            uploaded_file.name,
            extension,
        )

    def _get_extension(
        self,
        filename,
    ):
        return Path(
            filename
        ).suffix.lower()

    def _normalize_filename(
        self,
        filename,
    ):
        """
        Normaliza nombres como:

        DETALLE-CAJA.pdf
        detalle_caja.pdf
        DETALLE CAJA.pdf
        DETALLE-CAJA (1).pdf
        DETALLE-CAJA-2026.pdf
        """

        stem = Path(
            filename
        ).stem

        stem = unicodedata.normalize(
            "NFKD",
            stem,
        )

        stem = "".join(
            char
            for char in stem
            if not unicodedata.combining(char)
        )

        stem = stem.upper()

        stem = re.sub(
            r"\(\d+\)",
            "",
            stem,
        )

        stem = re.sub(
            r"[\s_]+",
            "-",
            stem,
        )

        stem = re.sub(
            r"-+",
            "-",
            stem,
        )

        return stem.strip("-")

    def _detect_document_type(
        self,
        filename,
    ):
        normalized_name = self._normalize_filename(
            filename
        )

        if normalized_name.startswith(
            "DETALLE-CAJA"
        ):
            return DOCUMENT_TYPE_DETALLE_CAJA

        if normalized_name.startswith(
            "FLUJO-CAJA-PPTO"
        ):
            return DOCUMENT_TYPE_FLUJO_CAJA_PPTO

        if normalized_name.startswith(
            "LOGS"
        ):
            return DOCUMENT_TYPE_LOGS

        if normalized_name.startswith(
            "REPORTE"
        ):
            return DOCUMENT_TYPE_REPORTE

        return DOCUMENT_TYPE_UNKNOWN

    def _validate_document_extension(
        self,
        filename,
        extension,
    ):
        document_type = self._detect_document_type(
            filename
        )

        expected_extensions = {
            DOCUMENT_TYPE_DETALLE_CAJA: {
                ".pdf",
            },
            DOCUMENT_TYPE_FLUJO_CAJA_PPTO: {
                ".xlsx",
                ".xls",
            },
            DOCUMENT_TYPE_LOGS: {
                ".xlsx",
                ".xls",
            },
            DOCUMENT_TYPE_REPORTE: {
                ".xlsx",
                ".xls",
            },
        }

        allowed = expected_extensions.get(
            document_type
        )

        if not allowed:
            return

        if extension not in allowed:
            readable_extensions = ", ".join(
                sorted(
                    ext.upper().replace(".", "")
                    for ext in allowed
                )
            )

            raise ValidationError(
                {
                    "file": (
                        f"El documento '{filename}' "
                        f"debe tener formato "
                        f"{readable_extensions}."
                    )
                }
            )

    def _parse_pdf(
        self,
        uploaded_file,
        document_type,
    ):
        return pdf_parser.parse(
            uploaded_file,
            document_type=document_type,
        )

    def _parse_spreadsheet(
        self,
        uploaded_file,
        document_type,
    ):
        extension = self._get_extension(
            uploaded_file.name
        )

        return excel_parser.parse(
            uploaded_file,
            extension,
            document_type=document_type,
        )

    def _build_response(
        self,
        uploaded_file,
        extension,
        document_type,
        parsed_data,
    ):
        labels = {
            DOCUMENT_TYPE_DETALLE_CAJA: (
                "Detalle de caja"
            ),
            DOCUMENT_TYPE_FLUJO_CAJA_PPTO: (
                "Flujo de caja y presupuesto"
            ),
            DOCUMENT_TYPE_LOGS: (
                "Logs"
            ),
            DOCUMENT_TYPE_REPORTE: (
                "Reporte"
            ),
        }

        return {
            "file_name": uploaded_file.name,
            "extension": extension,
            "document_type": document_type,
            "document_type_label": labels.get(
                document_type,
                "Documento",
            ),
            "data": parsed_data,
        }


document_parser = DocumentParser()