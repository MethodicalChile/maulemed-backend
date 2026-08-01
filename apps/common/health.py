from django.db import connections
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from apps.common.responses import api_response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return api_response(
        data={
            "status": "ok",
            "service": "MauleMed API",
        },
        message="Servicio disponible.",
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def health_db(request):
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        database_status = "connected"
        status_text = "success"
        message = "Base de datos conectada correctamente."
        status_code = 200

    except Exception as exc:
        database_status = "disconnected"
        status_text = "error"
        message = "No fue posible conectar con la base de datos."
        status_code = 503

    return api_response(
        data={
            "status": database_status,
            "database": "default",
        },
        status_code=status_code,
        status_text=status_text,
        message=message,
    )
