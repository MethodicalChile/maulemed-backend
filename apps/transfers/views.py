from django.core.exceptions import ValidationError
from rest_framework.decorators import action

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import (
    CanManageTransfers,
    CanApproveTransfer,
)
from apps.common.responses import api_response
from apps.common.scopes import apply_branch_scope
from apps.audit.services import serialize_instance, audit_action
from apps.notifications.services import (
    notify_stock_transfer_approved,
    notify_stock_transfer_sent,
    notify_stock_transfer_received,
)

from .models import StockTransfer, StockTransferItem
from .serializers import StockTransferSerializer, StockTransferItemSerializer
from .services import (
    approve_stock_transfer,
    send_stock_transfer,
    receive_stock_transfer,
    close_stock_transfer,
)


def ensure_action_permission(permission_class, request, view):
    permission = permission_class()
    if not permission.has_permission(request, view):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("No tienes permiso para realizar esta acción.")


class StockTransferViewSet(BaseModelViewSet):
    queryset = StockTransfer.objects.select_related(
        "origin_branch",
        "destination_branch",
        "requested_by",
        "approved_by",
        "sent_by",
        "received_by",
        "parent_transfer",
    ).prefetch_related("items").all()
    serializer_class = StockTransferSerializer
    permission_classes = [CanManageTransfers]

    filterset_fields = [
        "origin_branch",
        "destination_branch",
        "transfer_type",
        "status",
        "requested_by",
        "approved_by",
        "sent_by",
        "received_by",
        "parent_transfer",
    ]
    search_fields = [
        "origin_branch__name",
        "destination_branch__name",
        "reason",
        "rejection_reason",
        "dispatch_guide_number",
        "internal_guide_number",
    ]
    ordering_fields = [
        "status",
        "transfer_type",
        "created_at",
        "requested_at",
        "approved_at",
        "sent_at",
        "received_at",
        "closed_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="origin_branch")

    def _validation_error_response(self, exc):
        return api_response(
            data={"detail": str(exc)},
            status_code=400,
            status_text="error",
            message="No se pudo procesar el traspaso.",
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, uuid=None):
        ensure_action_permission(CanApproveTransfer, request, self)
        instance = self.get_object()

        old_data = serialize_instance(instance)

        try:
            stock_transfer = approve_stock_transfer(
                stock_transfer=instance,
                user=request.user,
            )
        except ValidationError as exc:
            return self._validation_error_response(exc)

        audit_action(
            request=request,
            action="APPROVE_STOCK_TRANSFER",
            instance=stock_transfer,
            old_data=old_data,
            notes="Traspaso aprobado.",
        )

        notify_stock_transfer_approved(stock_transfer)

        return api_response(
            data=self.get_serializer(stock_transfer).data,
            message="Traspaso aprobado correctamente.",
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, uuid=None):
        ensure_action_permission(CanApproveTransfer, request, self)
        instance = self.get_object()
        old_data = serialize_instance(instance)

        instance.status = StockTransfer.STATUS_REJECTED
        instance.rejection_reason = request.data.get("rejection_reason")
        instance.save(update_fields=["status", "rejection_reason", "updated_at"])

        audit_action(
            request=request,
            action="REJECT_STOCK_TRANSFER",
            instance=instance,
            old_data=old_data,
            notes="Traspaso rechazado.",
        )

        return api_response(
            data=self.get_serializer(instance).data,
            message="Traspaso rechazado correctamente.",
        )

    @action(detail=True, methods=["post"])
    def send(self, request, uuid=None):
        ensure_action_permission(CanManageTransfers, request, self)
        instance = self.get_object()

        old_data = serialize_instance(instance)

        try:
            result = send_stock_transfer(
                stock_transfer=instance,
                user=request.user,
            )
        except ValidationError as exc:
            return self._validation_error_response(exc)

        audit_action(
            request=request,
            action="SEND_STOCK_TRANSFER",
            instance=result["stock_transfer"],
            old_data=old_data,
            new_data={
                "stock_transfer_uuid": str(result["stock_transfer"].uuid),
                "processed_items": result["processed_items"],
            },
            notes="Traspaso enviado y stock descontado.",
        )

        notify_stock_transfer_sent(result["stock_transfer"])

        return api_response(
            data={
                "stock_transfer": self.get_serializer(result["stock_transfer"]).data,
                "processed_items": result["processed_items"],
            },
            message="Traspaso enviado y stock descontado correctamente.",
        )

    @action(detail=True, methods=["post"])
    def receive(self, request, uuid=None):
        ensure_action_permission(CanManageTransfers, request, self)
        instance = self.get_object()

        old_data = serialize_instance(instance)

        try:
            result = receive_stock_transfer(
                stock_transfer=instance,
                user=request.user,
            )
        except ValidationError as exc:
            return self._validation_error_response(exc)

        audit_action(
            request=request,
            action="RECEIVE_STOCK_TRANSFER",
            instance=result["stock_transfer"],
            old_data=old_data,
            new_data={
                "stock_transfer_uuid": str(result["stock_transfer"].uuid),
                "processed_items": result["processed_items"],
            },
            notes="Traspaso recibido y stock ingresado.",
        )

        notify_stock_transfer_received(result["stock_transfer"])

        return api_response(
            data={
                "stock_transfer": self.get_serializer(result["stock_transfer"]).data,
                "processed_items": result["processed_items"],
            },
            message="Traspaso recibido y stock ingresado correctamente.",
        )

    @action(detail=True, methods=["post"])
    def close(self, request, uuid=None):
        ensure_action_permission(CanManageTransfers, request, self)
        instance = self.get_object()

        old_data = serialize_instance(instance)

        try:
            stock_transfer = close_stock_transfer(
                stock_transfer=instance,
                user=request.user,
            )
        except ValidationError as exc:
            return self._validation_error_response(exc)

        audit_action(
            request=request,
            action="CLOSE_STOCK_TRANSFER",
            instance=stock_transfer,
            old_data=old_data,
            notes="Traspaso cerrado.",
        )

        return api_response(
            data=self.get_serializer(stock_transfer).data,
            message="Traspaso cerrado correctamente.",
        )


class StockTransferItemViewSet(BaseModelViewSet):
    queryset = StockTransferItem.objects.select_related(
        "stock_transfer",
        "stock_transfer__origin_branch",
        "stock_transfer__destination_branch",
        "product",
        "lot",
    ).all()
    serializer_class = StockTransferItemSerializer
    permission_classes = [CanManageTransfers]

    filterset_fields = [
        "stock_transfer",
        "product",
        "lot",
        "stock_transfer__origin_branch",
        "stock_transfer__destination_branch",
    ]
    search_fields = [
        "product__name",
        "product__internal_code",
        "comments",
        "stock_transfer__origin_branch__name",
        "stock_transfer__destination_branch__name",
    ]
    ordering_fields = [
        "requested_quantity",
        "approved_quantity",
        "sent_quantity",
        "received_quantity",
        "returned_quantity",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="stock_transfer__origin_branch")
