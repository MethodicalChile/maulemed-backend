"""
apps/evaluations/services/qr_service.py

Genera códigos QR como bytes PNG de forma dinámica.
No almacena archivos — el resultado se sirve directamente como respuesta HTTP.
"""
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


class QRService:
    """Genera imágenes QR en memoria."""

    @staticmethod
    def generate_png(content: str) -> bytes:
        """
        Genera un PNG con el QR del contenido indicado.

        Parameters
        ----------
        content : str
            URL o texto a codificar. No puede estar vacío.

        Returns
        -------
        bytes
            Bytes del PNG listo para servirse o descargarse.

        Raises
        ------
        ValueError
            Si *content* está vacío.
        """
        if not content or not content.strip():
            raise ValueError("El contenido del QR no puede estar vacío.")

        qr = qrcode.QRCode(
            error_correction=ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(content)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
