import uuid as uuid_module
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status as http_status

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageDocuments
from apps.common.responses import api_response
from apps.common.services.supabase_storage import upload_file, get_public_url, SupabaseStorageError

from .models import Document
from .serializers import DocumentSerializer


class DocumentViewSet(BaseModelViewSet):
    queryset = Document.objects.all().order_by("-created_at")
    serializer_class = DocumentSerializer
    permission_classes = [CanManageDocuments]

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
    ordering = ["-created_at"]

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request):
        """
        Recibe un archivo via multipart/form-data, lo sube a Supabase Storage
        y crea el registro Document con la URL pública resultante.

        Campos esperados:
          - file            (required) — el archivo
          - document_type   (required) — código del tipo
          - related_model   (optional)
          - related_uuid    (optional)
          - notes           (optional)
        """
        file = request.FILES.get("file")
        if not file:
            return api_response(
                data={"detail": "El campo 'file' es obligatorio."},
                status_code=400,
                status_text="error",
                message="No se recibió ningún archivo.",
            )

        document_type = request.data.get("document_type", Document.TYPE_OTHER)
        related_model = request.data.get("related_model") or None
        related_uuid  = request.data.get("related_uuid")  or None
        notes         = request.data.get("notes")         or None

        # Ruta en Supabase: documents/<uuid>_<filename>
        storage_path = f"documents/{uuid_module.uuid4().hex}_{file.name}"

        try:
            upload_file(
                path=storage_path,
                content=file.read(),
                content_type=file.content_type or "application/octet-stream",
            )
        except SupabaseStorageError as exc:
            return api_response(
                data={"detail": str(exc)},
                status_code=500,
                status_text="error",
                message="No se pudo subir el archivo al almacenamiento.",
            )

        public_url = get_public_url(storage_path)

        doc = Document.objects.create(
            document_type=document_type,
            file_url=public_url,
            file_name=file.name,
            file_size=file.size,
            mime_type=file.content_type,
            related_model=related_model,
            related_uuid=related_uuid,
            notes=notes,
            uploaded_by=request.user,
        )

        return api_response(
            data=DocumentSerializer(doc).data,
            status_code=201,
            message="Documento subido correctamente.",
        )
