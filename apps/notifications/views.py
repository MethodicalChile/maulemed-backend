from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed

from apps.common.viewsets import BaseModelViewSet
from apps.common.responses import api_response

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(BaseModelViewSet):
    serializer_class = NotificationSerializer
    enable_audit = False

    filterset_fields = [
        "notification_type",
        "is_read",
        "related_app",
        "related_model",
        "related_uuid",
    ]
    search_fields = [
        "title",
        "message",
        "related_app",
        "related_model",
    ]
    ordering_fields = [
        "is_read",
        "notification_type",
        "created_at",
        "read_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="Las notificaciones se crean automáticamente por el sistema.")

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT", detail="No se permite actualizar notificaciones manualmente.")

    def partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PATCH", detail="No se permite actualizar notificaciones manualmente.")

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE", detail="No se permite eliminar notificaciones manualmente.")

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = self.get_queryset().filter(is_read=False).count()

        return api_response(
            data={
                "unread_count": count,
            },
            message="Cantidad de notificaciones no leídas obtenida correctamente.",
        )

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        limit = int(request.GET.get("limit", 10))

        if limit > 50:
            limit = 50

        qs = self.get_queryset().order_by("-created_at")[:limit]
        serializer = self.get_serializer(qs, many=True)

        return api_response(
            data=serializer.data,
            message="Últimas notificaciones obtenidas correctamente.",
        )

    @action(detail=True, methods=["post"])
    def mark_as_read(self, request, uuid=None):
        instance = self.get_object()
        instance.is_read = True
        instance.read_at = timezone.now()
        instance.save(update_fields=["is_read", "read_at", "updated_at"])

        return api_response(
            data=self.get_serializer(instance).data,
            message="Notificación marcada como leída.",
        )

    @action(detail=False, methods=["post"])
    def mark_all_as_read(self, request):
        self.get_queryset().filter(is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )

        return api_response(
            data=None,
            message="Todas las notificaciones fueron marcadas como leídas.",
        )
