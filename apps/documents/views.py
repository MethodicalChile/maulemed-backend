import uuid as uuid_module

from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageDocuments
from apps.common.responses import api_response
from apps.common.services.supabase_storage import (
    upload_file,
    get_public_url,
    SupabaseStorageError,
)

from .models import Document
from .serializers import DocumentSerializer
from .services.document_parser import document_parser


class DocumentViewSet(BaseModelViewSet):
    queryset = Document.objects.all().order_by(
        "-created_at"
    )

    serializer_class = DocumentSerializer

    permission_classes = [
        CanManageDocuments
    ]

    filterset_fields = [
        "document_type",
        "related_app",
        "related_model",
        "related_uuid",
        "uploaded_by",
    ]

    search_fields = [
        "file_name",
        "related_app",
        "related_model",
        "notes",
    ]

    ordering_fields = [
        "document_type",
        "file_name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-created_at"
    ]

    def perform_create(
        self,
        serializer,
    ):
        serializer.save(
            uploaded_by=self.request.user
        )

    # =========================================================
    # PREVIEW / ANÁLISIS
    # =========================================================

    @action(
        detail=False,
        methods=["post"],
        url_path="preview",
    )
    def preview(
        self,
        request,
    ):
        """
        Recibe un archivo vía multipart/form-data
        y analiza su contenido.

        Este endpoint:

        - NO guarda el archivo en Supabase.
        - NO crea registros Document.
        - NO persiste información.
        - Detecta el tipo de documento.
        - Ejecuta el parser correspondiente.
        - Devuelve datos para dashboard.
        - Devuelve datos originales para inspección.

        Campo esperado:

            file (required)
        """

        uploaded_file = (
            request.FILES.get(
                "file"
            )
        )

        if not uploaded_file:
            return api_response(
                data={
                    "detail": (
                        "El campo 'file' "
                        "es obligatorio."
                    )
                },
                status_code=400,
                status_text="error",
                message=(
                    "No se recibió ningún archivo."
                ),
            )

        try:
            result = document_parser.parse(
                uploaded_file
            )

        except ValidationError as exc:
            return api_response(
                data={
                    "detail": (
                        self._normalize_validation_error(
                            exc
                        )
                    )
                },
                status_code=400,
                status_text="error",
                message=(
                    "El documento no cumple "
                    "con el formato esperado."
                ),
            )

        except ValueError as exc:
            return api_response(
                data={
                    "detail": str(
                        exc
                    )
                },
                status_code=400,
                status_text="error",
                message=(
                    "No se pudo interpretar "
                    "el documento."
                ),
            )

        except Exception as exc:
            return api_response(
                data={
                    "detail": str(
                        exc
                    )
                },
                status_code=500,
                status_text="error",
                message=(
                    "Ocurrió un error inesperado "
                    "al procesar el documento."
                ),
            )

        return api_response(
            data=result,
            status_code=200,
            message=(
                "Documento procesado "
                "correctamente."
            ),
        )

    # =========================================================
    # UPLOAD PERSISTENTE
    # =========================================================

    @action(
        detail=False,
        methods=["post"],
        url_path="upload",
    )
    def upload(
        self,
        request,
    ):
        """
        Recibe un archivo vía multipart/form-data,
        lo sube a Supabase Storage y crea el registro
        Document.

        Este flujo es independiente del endpoint
        preview/análisis.

        Campos esperados:

            file            required
            document_type   optional
            related_model   optional
            related_uuid    optional
            notes           optional
        """

        uploaded_file = (
            request.FILES.get(
                "file"
            )
        )

        if not uploaded_file:
            return api_response(
                data={
                    "detail": (
                        "El campo 'file' "
                        "es obligatorio."
                    )
                },
                status_code=400,
                status_text="error",
                message=(
                    "No se recibió ningún archivo."
                ),
            )

        document_type = (
            request.data.get(
                "document_type",
                Document.TYPE_OTHER,
            )
        )

        related_model = (
            request.data.get(
                "related_model"
            )
            or None
        )

        related_uuid = (
            request.data.get(
                "related_uuid"
            )
            or None
        )

        notes = (
            request.data.get(
                "notes"
            )
            or None
        )

        storage_path = (
            f"documents/"
            f"{uuid_module.uuid4().hex}_"
            f"{uploaded_file.name}"
        )

        try:
            uploaded_file.seek(
                0
            )

            upload_file(
                path=storage_path,
                content=uploaded_file.read(),
                content_type=(
                    uploaded_file.content_type
                    or "application/octet-stream"
                ),
            )

        except SupabaseStorageError as exc:
            return api_response(
                data={
                    "detail": str(
                        exc
                    )
                },
                status_code=500,
                status_text="error",
                message=(
                    "No se pudo subir el archivo "
                    "al almacenamiento."
                ),
            )

        public_url = get_public_url(
            storage_path
        )

        doc = Document.objects.create(
            document_type=document_type,
            file_url=public_url,
            file_name=uploaded_file.name,
            file_size=uploaded_file.size,
            mime_type=uploaded_file.content_type,
            related_model=related_model,
            related_uuid=related_uuid,
            notes=notes,
            uploaded_by=request.user,
        )

        return api_response(
            data=DocumentSerializer(
                doc
            ).data,
            status_code=201,
            message=(
                "Documento subido correctamente."
            ),
        )

    # =========================================================
    # UTILIDADES
    # =========================================================

    def _normalize_validation_error(
        self,
        exc,
    ):
        """
        Convierte ValidationError de DRF en un formato
        simple para que el frontend pueda mostrarlo.
        """

        detail = getattr(
            exc,
            "detail",
            None,
        )

        if detail is None:
            return str(
                exc
            )

        if isinstance(
            detail,
            dict,
        ):
            normalized = {}

            for key, value in detail.items():

                if isinstance(
                    value,
                    (
                        list,
                        tuple,
                    ),
                ):
                    normalized[
                        key
                    ] = " ".join(
                        str(
                            item
                        )
                        for item in value
                    )

                else:
                    normalized[
                        key
                    ] = str(
                        value
                    )

            return normalized

        if isinstance(
            detail,
            (
                list,
                tuple,
            ),
        ):
            return " ".join(
                str(
                    item
                )
                for item in detail
            )

        return str(
            detail
        )