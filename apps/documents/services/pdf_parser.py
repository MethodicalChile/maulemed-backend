import io

import pdfplumber

from rest_framework.exceptions import ValidationError

from .parsers.informe_depositos_parser import (
    informe_depositos_parser,
)


DOCUMENT_TYPE_DETALLE_CAJA = "detalle_caja"


class PDFParser:
    """
    Parser general de archivos PDF.

    Responsabilidades:
    - leer el PDF
    - extraer texto por página
    - construir texto completo
    - validar que el contenido corresponda
      al tipo lógico detectado previamente
    - delegar al parser específico
    - devolver una estructura normalizada

    El tipo principal del documento NO se determina
    aquí por nombre.

    DocumentParser es quien determina inicialmente:

        DETALLE-CAJA.pdf -> detalle_caja

    PDFParser utiliza el contenido como validación
    secundaria.
    """

    def parse(
        self,
        uploaded_file,
        document_type=None,
    ):
        uploaded_file.seek(0)

        try:
            file_bytes = uploaded_file.read()

            pages = []
            full_text_parts = []

            with pdfplumber.open(
                io.BytesIO(file_bytes)
            ) as pdf:

                for index, page in enumerate(
                    pdf.pages
                ):
                    text = (
                        page.extract_text()
                        or ""
                    )

                    pages.append(
                        {
                            "page": index + 1,
                            "text": text,
                        }
                    )

                    if text.strip():
                        full_text_parts.append(
                            text
                        )

            full_text = "\n".join(
                full_text_parts
            )

            if not full_text.strip():
                raise ValidationError(
                    {
                        "file": (
                            "No fue posible extraer "
                            "texto del archivo PDF."
                        )
                    }
                )

            self._validate_document_content(
                document_type=document_type,
                text=full_text,
            )

            extracted_data = (
                self._parse_document(
                    document_type=document_type,
                    text=full_text,
                )
            )

            return {
                "type": "pdf",
                "filename": uploaded_file.name,
                "size": uploaded_file.size,
                "format": "pdf",

                # Tipo lógico detectado por nombre.
                "document_type": document_type,

                "page_count": len(
                    pages
                ),

                # Información estructurada.
                "data": extracted_data,

                # Se mantienen para la subvista
                # "Datos extraídos" y debugging.
                "pages": pages,

                # Texto completo del documento.
                "text": full_text,
            }

        finally:
            uploaded_file.seek(0)

    def _validate_document_content(
        self,
        document_type,
        text,
    ):
        """
        Valida que el contenido físico del PDF
        tenga relación con el tipo detectado por
        el nombre.

        No se utiliza como detector principal.
        """

        normalized_text = self._normalize_text(
            text
        )

        if (
            document_type
            == DOCUMENT_TYPE_DETALLE_CAJA
        ):
            self._validate_detalle_caja(
                normalized_text
            )

    def _validate_detalle_caja(
        self,
        normalized_text,
    ):
        """
        DETALLE-CAJA debe corresponder al
        Informe de Depósitos.

        Se utilizan varias palabras características
        del documento para evitar aceptar un PDF
        completamente distinto que solamente haya
        sido renombrado.
        """

        expected_terms = [
            "INFORME DE DEPOSITOS",
            "PRESTADOR",
            "PARTICULAR",
            "COPAGO",
            "TOTALES",
        ]

        matches = sum(
            1
            for term in expected_terms
            if term in normalized_text
        )

        # No exigimos 100% porque la extracción
        # de texto de un PDF puede variar.
        minimum_matches = 3

        if matches < minimum_matches:
            raise ValidationError(
                {
                    "file": (
                        "El archivo fue identificado "
                        "por nombre como DETALLE-CAJA, "
                        "pero su contenido no coincide "
                        "con la estructura esperada "
                        "del Informe de Depósitos."
                    )
                }
            )

    def _parse_document(
        self,
        document_type,
        text,
    ):
        """
        Selecciona el parser especializado de acuerdo
        al tipo lógico del documento.
        """

        if (
            document_type
            == DOCUMENT_TYPE_DETALLE_CAJA
        ):
            return (
                informe_depositos_parser.parse(
                    text
                )
            )

        return {
            "document_type": (
                document_type
                or "unknown"
            ),
            "raw_text": text,
        }

    def _normalize_text(
        self,
        text,
    ):
        """
        Normalización sencilla para validaciones.

        Ejemplo:

            "Informe de Depósitos"
                ->
            "INFORME DE DEPOSITOS"
        """

        replacements = {
            "Á": "A",
            "É": "E",
            "Í": "I",
            "Ó": "O",
            "Ú": "U",
            "Ü": "U",
            "Ñ": "N",
        }

        normalized = (
            text
            or ""
        ).upper()

        for original, replacement in (
            replacements.items()
        ):
            normalized = normalized.replace(
                original,
                replacement,
            )

        return normalized


pdf_parser = PDFParser()