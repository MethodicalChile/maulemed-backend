import logging

from rest_framework.views import exception_handler


logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    view = context.get("view")
    request = context.get("request")

    view_name = view.__class__.__name__ if view else "UnknownView"
    path = request.path if request else "UnknownPath"

    if response is not None:
        # Solo loguear traceback completo para errores de servidor (5xx).
        # Los 4xx son errores esperados (validaciones, not found) — basta con WARNING.
        if response.status_code >= 500:
            logger.exception(f"Error 5xx en {view_name} path={path}: {exc}")
        else:
            logger.warning(f"Error {response.status_code} en {view_name} path={path}: {exc}")

        # Preservar el mensaje original de DRF si está disponible;
        # solo usar el genérico como fallback para respuestas sin mensaje legible.
        original = response.data
        if isinstance(original, dict) and "detail" in original:
            message = str(original["detail"])
        elif isinstance(original, list) and original:
            message = str(original[0])
        elif isinstance(original, str):
            message = original
        else:
            message = "Ocurrió un error al procesar la solicitud."

        response.data = {
            "data": original,
            "status": "error",
            "message": message,
        }
    else:
        # Excepción no manejada por DRF — siempre loguear con traceback
        logger.exception(f"Excepción no manejada en {view_name} path={path}: {exc}")

    return response
