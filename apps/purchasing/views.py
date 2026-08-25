from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.shortcuts import get_object_or_404

from apps.common.viewsets import BaseModelViewSet

from apps.common.permissions import (
    CanAccessSupplyRequests,
    CanAccessPurchaseOrders,
    CanAccessPurchaseReceipts,
    CanAccessSupplierClaims,
    CanCreateSupplyRequest,
    CanApproveSupplyRequest,
    CanApprovePurchaseOrder,
    CanProcessPurchaseReceipt,
)
from apps.common.scopes import apply_branch_scope
from apps.common.responses import api_response
from apps.suppliers.models import Supplier
from apps.audit.services import serialize_instance, audit_action
from apps.notifications.services import (
    notify_supply_request_submitted,
    notify_supply_request_approved,
    notify_supply_request_rejected,
    notify_purchase_order_approved,
    notify_purchase_receipt_processed,
)

from .models import (
    SupplyRequest,
    SupplyRequestItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierClaim,
)
from .action_serializers import ConvertSupplyRequestToPurchaseOrderSerializer
from .serializers import (
    SupplyRequestSerializer,
    SupplyRequestItemSerializer,
    PurchaseOrderSerializer,
    PurchaseOrderItemSerializer,
    PurchaseReceiptSerializer,
    PurchaseReceiptItemSerializer,
    SupplierClaimSerializer,
)


def ensure_action_permission(permission_class, request, view):
    permission = permission_class()
    if not permission.has_permission(request, view):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("No tienes permiso para realizar esta acción.")

class SupplyRequestViewSet(BaseModelViewSet):
    queryset = SupplyRequest.objects.select_related(
        "branch",
        "legal_entity",
        "cost_center",
        "requested_by",
        "reviewed_by",
        "approved_by",
    ).prefetch_related("items").all()

    serializer_class = SupplyRequestSerializer
    permission_classes = [CanAccessSupplyRequests]

    filterset_fields = [
        "branch",
        "legal_entity",
        "cost_center",
        "status",
        "period_year",
        "period_month",
        "requested_by",
        "reviewed_by",
        "approved_by",
    ]

    search_fields = [
        "branch__name",
        "legal_entity__name",
        "cost_center__name",
        "comments",
    ]

    ordering_fields = [
        "period_year",
        "period_month",
        "status",
        "created_at",
        "submitted_at",
        "approved_at",
    ]

    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()

        return apply_branch_scope(
            qs,
            self.request.user,
            branch_field="branch",
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def submit(self, request, uuid=None):
        ensure_action_permission(
            CanCreateSupplyRequest,
            request,
            self,
        )

        instance = self.get_object()

        if not instance.items.exists():
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="No puedes enviar una solicitud sin ítems.",
            )

        old_data = serialize_instance(instance)

        instance.status = SupplyRequest.STATUS_SUBMITTED
        instance.submitted_at = timezone.now()

        instance.save(
            update_fields=[
                "status",
                "submitted_at",
                "updated_at",
            ]
        )

        audit_action(
            request=request,
            action="SUBMIT_SUPPLY_REQUEST",
            instance=instance,
            old_data=old_data,
            notes="Solicitud de insumos enviada.",
        )

        notify_supply_request_submitted(instance)

        return api_response(
            data=self.get_serializer(instance).data,
            message="Solicitud enviada correctamente.",
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def approve(self, request, uuid=None):
        ensure_action_permission(
            CanApproveSupplyRequest,
            request,
            self,
        )

        instance = self.get_object()

        if not instance.items.exists():
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="No puedes aprobar una solicitud sin ítems.",
            )

        old_data = serialize_instance(instance)

        instance.status = SupplyRequest.STATUS_APPROVED
        instance.approved_by = request.user
        instance.approved_at = timezone.now()

        instance.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        audit_action(
            request=request,
            action="APPROVE_SUPPLY_REQUEST",
            instance=instance,
            old_data=old_data,
            notes="Solicitud de insumos aprobada.",
        )

        notify_supply_request_approved(instance)

        return api_response(
            data=self.get_serializer(instance).data,
            message="Solicitud aprobada correctamente.",
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def reject(self, request, uuid=None):
        ensure_action_permission(
            CanApproveSupplyRequest,
            request,
            self,
        )

        instance = self.get_object()
        old_data = serialize_instance(instance)

        instance.status = SupplyRequest.STATUS_REJECTED
        instance.reviewed_by = request.user
        instance.reviewed_at = timezone.now()
        instance.comments = request.data.get(
            "comments",
            instance.comments,
        )

        instance.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "comments",
                "updated_at",
            ]
        )

        audit_action(
            request=request,
            action="REJECT_SUPPLY_REQUEST",
            instance=instance,
            old_data=old_data,
            notes="Solicitud de insumos rechazada.",
        )

        notify_supply_request_rejected(instance)

        return api_response(
            data=self.get_serializer(instance).data,
            message="Solicitud rechazada correctamente.",
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def observe(self, request, uuid=None):
        ensure_action_permission(
            CanApproveSupplyRequest,
            request,
            self,
        )

        instance = self.get_object()
        old_data = serialize_instance(instance)

        instance.status = SupplyRequest.STATUS_OBSERVED
        instance.reviewed_by = request.user
        instance.reviewed_at = timezone.now()
        instance.comments = request.data.get(
            "comments",
            instance.comments,
        )

        instance.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "comments",
                "updated_at",
            ]
        )

        audit_action(
            request=request,
            action="OBSERVE_SUPPLY_REQUEST",
            instance=instance,
            old_data=old_data,
            notes="Solicitud de insumos observada.",
        )

        return api_response(
            data=self.get_serializer(instance).data,
            message="Solicitud observada correctamente.",
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="convert-to-purchase-order",
    )
    def convert_to_purchase_order(self, request, uuid=None):
        from django.core.exceptions import ValidationError
        from apps.purchasing.services import (
            convert_supply_request_to_purchase_order,
        )

        ensure_action_permission(
            CanApprovePurchaseOrder,
            request,
            self,
        )

        instance = self.get_object()
        old_data = serialize_instance(instance)

        serializer = ConvertSupplyRequestToPurchaseOrderSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        supplier = get_object_or_404(
            Supplier,
            uuid=serializer.validated_data["supplier_uuid"],
        )

        try:
            result = convert_supply_request_to_purchase_order(
                supply_request=instance,
                supplier=supplier,
                user=request.user,
                expected_delivery_date=serializer.validated_data.get(
                    "expected_delivery_date"
                ),
                notes=serializer.validated_data.get(
                    "notes"
                ),
                tax_rate=serializer.validated_data.get(
                    "tax_rate"
                ),
            )

        except ValidationError as exc:
            return api_response(
                data={
                    "detail": str(exc)
                },
                status_code=400,
                status_text="error",
                message=(
                    "No se pudo convertir la solicitud "
                    "en orden de compra."
                ),
            )

        audit_action(
            request=request,
            action="CONVERT_SUPPLY_REQUEST_TO_PURCHASE_ORDER",
            instance=result["supply_request"],
            old_data=old_data,
            new_data={
                "supply_request_uuid": str(
                    result["supply_request"].uuid
                ),
                "purchase_order_uuid": str(
                    result["purchase_order"].uuid
                ),
                "purchase_order_number":
                    result["purchase_order"].order_number,
                "items_count": len(
                    result["purchase_order_items"]
                ),
            },
            notes=(
                "Solicitud convertida en orden de compra."
            ),
        )

        try:
            from apps.notifications.services import notify_roles

            notify_roles(
                role_codes=[
                    "ADMIN",
                    "GERENTE",
                    "ABASTECIMIENTO",
                ],
                branch=result["purchase_order"].branch,
                title=(
                    "Solicitud convertida en orden de compra"
                ),
                message=(
                    f"La solicitud fue convertida en la OC "
                    f"{result['purchase_order'].order_number}."
                ),
                related_app="purchasing",
                related_model="PurchaseOrder",
                related_uuid=result["purchase_order"].uuid,
            )

        except Exception:
            pass

        return api_response(
            data={
                "supply_request": self.get_serializer(
                    result["supply_request"]
                ).data,
                "purchase_order": PurchaseOrderSerializer(
                    result["purchase_order"]
                ).data,
                "items_count": len(
                    result["purchase_order_items"]
                ),
            },
            message=(
                "Solicitud convertida en orden de compra correctamente."
            ),
        )

class SupplyRequestItemViewSet(BaseModelViewSet):
    queryset = SupplyRequestItem.objects.select_related(
        "supply_request",
        "supply_request__branch",
        "product",
    ).all()
    serializer_class = SupplyRequestItemSerializer
    permission_classes = [CanAccessSupplyRequests]

    filterset_fields = [
        "supply_request",
        "product",
        "status",
        "supply_request__branch",
    ]
    search_fields = [
        "product__name",
        "product__internal_code",
        "justification",
        "review_comment",
        "supply_request__branch__name",
    ]
    ordering_fields = [
        "requested_quantity",
        "approved_quantity",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="supply_request__branch")


class PurchaseOrderViewSet(BaseModelViewSet):
    queryset = PurchaseOrder.objects.select_related(
        "supplier",
        "legal_entity",
        "branch",
        "cost_center",
        "supply_request",
        "requested_by",
        "approved_by",
    ).prefetch_related("items").all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [CanAccessPurchaseOrders]

    filterset_fields = [
        "supplier",
        "legal_entity",
        "branch",
        "cost_center",
        "supply_request",
        "status",
        "purchase_type",
        "requested_by",
        "approved_by",
    ]
    search_fields = [
        "order_number",
        "supplier__name",
        "supplier__rut",
        "branch__name",
        "legal_entity__name",
        "notes",
    ]
    ordering_fields = [
        "order_number",
        "status",
        "purchase_type",
        "expected_delivery_date",
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "created_at",
        "approved_at",
        "sent_at",
        "received_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="branch")

    @action(detail=True, methods=["post"])
    def approve(self, request, uuid=None):
        ensure_action_permission(CanApprovePurchaseOrder, request, self)
        instance = self.get_object()

        if not instance.items.exists():
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="No puedes aprobar una orden de compra sin ítems.",
            )

        old_data = serialize_instance(instance)

        instance.status = PurchaseOrder.STATUS_APPROVED
        instance.approved_by = request.user
        instance.approved_at = timezone.now()
        instance.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

        audit_action(
            request=request,
            action="APPROVE_PURCHASE_ORDER",
            instance=instance,
            old_data=old_data,
            notes="Orden de compra aprobada.",
        )

        notify_purchase_order_approved(instance)

        return api_response(
            data=self.get_serializer(instance).data,
            message="Orden de compra aprobada correctamente.",
        )

    @action(detail=True, methods=["post"])
    def send(self, request, uuid=None):
        ensure_action_permission(CanApprovePurchaseOrder, request, self)
        instance = self.get_object()
        old_data = serialize_instance(instance)

        instance.status = PurchaseOrder.STATUS_SENT_TO_SUPPLIER
        instance.sent_at = timezone.now()
        instance.save(update_fields=["status", "sent_at", "updated_at"])

        audit_action(
            request=request,
            action="SEND_PURCHASE_ORDER",
            instance=instance,
            old_data=old_data,
            notes="Orden de compra enviada al proveedor.",
        )

        return api_response(
            data=self.get_serializer(instance).data,
            message="Orden de compra enviada al proveedor correctamente.",
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, uuid=None):
        ensure_action_permission(CanApprovePurchaseOrder, request, self)
        instance = self.get_object()
        old_data = serialize_instance(instance)

        instance.status = PurchaseOrder.STATUS_CANCELLED
        instance.cancelled_at = timezone.now()
        instance.save(update_fields=["status", "cancelled_at", "updated_at"])

        audit_action(
            request=request,
            action="CANCEL_PURCHASE_ORDER",
            instance=instance,
            old_data=old_data,
            notes="Orden de compra cancelada.",
        )

        return api_response(
            data=self.get_serializer(instance).data,
            message="Orden de compra cancelada correctamente.",
        )

    @action(detail=True, methods=["post"])
    def close(self, request, uuid=None):
        ensure_action_permission(CanApprovePurchaseOrder, request, self)
        instance = self.get_object()
        old_data = serialize_instance(instance)

        instance.status = PurchaseOrder.STATUS_CLOSED
        instance.save(update_fields=["status", "updated_at"])

        audit_action(
            request=request,
            action="CLOSE_PURCHASE_ORDER",
            instance=instance,
            old_data=old_data,
            notes="Orden de compra cerrada.",
        )

        return api_response(
            data=self.get_serializer(instance).data,
            message="Orden de compra cerrada correctamente.",
        )


class PurchaseOrderItemViewSet(BaseModelViewSet):
    queryset = PurchaseOrderItem.objects.select_related(
        "purchase_order",
        "purchase_order__branch",
        "product",
    ).all()
    serializer_class = PurchaseOrderItemSerializer
    permission_classes = [CanAccessPurchaseOrders]

    filterset_fields = [
        "purchase_order",
        "product",
        "purchase_order__branch",
    ]
    search_fields = [
        "purchase_order__order_number",
        "product__name",
        "product__internal_code",
    ]
    ordering_fields = [
        "quantity",
        "unit_price",
        "total_amount",
        "received_quantity",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="purchase_order__branch")


class PurchaseReceiptViewSet(BaseModelViewSet):
    queryset = PurchaseReceipt.objects.select_related(
        "purchase_order",
        "branch",
        "warehouse",
        "received_by",
    ).prefetch_related("items").all()
    serializer_class = PurchaseReceiptSerializer
    permission_classes = [CanAccessPurchaseReceipts]

    filterset_fields = [
        "purchase_order",
        "branch",
        "warehouse",
        "received_by",
        "status",
    ]
    search_fields = [
        "purchase_order__order_number",
        "branch__name",
        "warehouse__name",
        "comments",
    ]
    ordering_fields = [
        "received_at",
        "created_at",
        "updated_at",
        "status",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="branch")

    @action(detail=True, methods=["post"])
    def process(self, request, uuid=None):
        ensure_action_permission(CanProcessPurchaseReceipt, request, self)
        from django.core.exceptions import ValidationError
        from apps.purchasing.services import process_purchase_receipt

        instance = self.get_object()

        try:
            result = process_purchase_receipt(
                purchase_receipt=instance,
                user=request.user,
            )
        except ValidationError as exc:
            return api_response(
                data={"detail": str(exc)},
                status_code=400,
                status_text="error",
                message=str(exc),
            )

        audit_action(
            request=request,
            action="PROCESS_PURCHASE_RECEIPT",
            instance=result["purchase_receipt"],
            new_data={
                "purchase_receipt_uuid": str(result["purchase_receipt"].uuid),
                "processed_items": result["processed_items"],
            },
            notes="Recepción de compra procesada y stock actualizado.",
        )

        notify_purchase_receipt_processed(result["purchase_receipt"])

        return api_response(
            data={
                "purchase_receipt": self.get_serializer(result["purchase_receipt"]).data,
                "processed_items": result["processed_items"],
            },
            message="Recepción procesada correctamente.",
        )


class PurchaseReceiptItemViewSet(BaseModelViewSet):
    queryset = PurchaseReceiptItem.objects.select_related(
        "purchase_receipt",
        "purchase_receipt__branch",
        "product",
    ).all()
    serializer_class = PurchaseReceiptItemSerializer
    permission_classes = [CanAccessPurchaseReceipts]

    filterset_fields = [
        "purchase_receipt",
        "product",
        "incident_type",
        "expiration_date",
    ]
    search_fields = [
        "product__name",
        "product__internal_code",
        "lot_number",
        "comments",
    ]
    ordering_fields = [
        "received_quantity",
        "accepted_quantity",
        "rejected_quantity",
        "expiration_date",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="purchase_receipt__branch")


class SupplierClaimViewSet(BaseModelViewSet):
    queryset = SupplierClaim.objects.select_related(
        "purchase_receipt",
        "purchase_receipt__branch",
        "supplier",
        "created_by",
    ).all()
    serializer_class = SupplierClaimSerializer
    permission_classes = [CanAccessSupplierClaims]

    filterset_fields = [
        "purchase_receipt",
        "supplier",
        "claim_type",
        "status",
        "created_by",
    ]
    search_fields = [
        "supplier__name",
        "description",
        "requested_solution",
        "resolution",
        "credit_note_number",
    ]
    ordering_fields = [
        "status",
        "claim_type",
        "created_at",
        "resolved_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        # Permitir ver reclamos globales (sin receipt o sin branch) incluso con scope
        return apply_branch_scope(qs, self.request.user, branch_field="purchase_receipt__branch") | \
               SupplierClaim.objects.filter(purchase_receipt__isnull=True)