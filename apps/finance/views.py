from rest_framework.decorators import action

from apps.common.viewsets import BaseModelViewSet
from apps.common.responses import api_response
from apps.common.permissions import CanManageFinance
from apps.common.scopes import apply_legal_entity_scope

from .models import (
    SupplierInvoice,
    SupplierInvoiceItem,
    Payment,
    Budget,
    BudgetCategory,
)
from .serializers import (
    SupplierInvoiceSerializer,
    PaymentSerializer,
    BudgetSerializer,
    BudgetCategorySerializer,
    SupplierInvoiceItemSerializer,
)


class SupplierInvoiceViewSet(BaseModelViewSet):
    queryset = SupplierInvoice.objects.select_related(
        "supplier",
        "legal_entity",
        "branch",
        "cost_center",
        "purchase_order",
    ).prefetch_related("items__cost_center", "items__category").all()

    serializer_class = SupplierInvoiceSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = [
        "supplier",
        "legal_entity",
        "branch",
        "cost_center",
        "purchase_order",
        "status",
        "issue_date",
        "due_date",
    ]

    search_fields = [
        "supplier__name",
        "supplier__rut",
        "legal_entity__name",
        "branch__name",
        "cost_center__name",
        "invoice_number",
        "notes",
    ]

    ordering_fields = [
        "invoice_number",
        "issue_date",
        "due_date",
        "net_amount",
        "tax_amount",
        "total_amount",
        "status",
        "created_at",
        "updated_at",
    ]

    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()

        return apply_legal_entity_scope(
            qs,
            self.request.user,
            legal_entity_field="legal_entity",
        )

    @action(detail=True, methods=["post"], url_path="prefill-items")
    def prefill_items(self, request, uuid=None):
        """
        Precarga el detalle desde la orden de compra que originó la factura.

        Quien registra corrige los ítems que van a otro centro de costo, en vez
        de tipear el detalle completo.
        """
        from .services import build_items_from_purchase_order

        instance = self.get_object()

        if instance.purchase_order is None:
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="La factura no proviene de una orden de compra.",
            )

        if instance.items.exists():
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="La factura ya tiene detalle cargado.",
            )

        creados = build_items_from_purchase_order(instance)

        return api_response(
            data=self.get_serializer(instance).data,
            message=f"Se precargaron {len(creados)} ítems desde la orden.",
        )

    def perform_create(self, serializer):
        """
        Al registrar la factura, imputarla al presupuesto.

        Es el segundo momento del ciclo: la orden comprometió el monto al
        aprobarse; la factura lo convierte en gasto efectivo y libera el
        compromiso equivalente.
        """
        from .services import register_supplier_invoice

        super().perform_create(serializer)
        register_supplier_invoice(serializer.instance)


class PaymentViewSet(BaseModelViewSet):
    queryset = Payment.objects.select_related(
        "supplier_invoice",
        "legal_entity",
        "created_by",
    ).all()

    serializer_class = PaymentSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = [
        "supplier_invoice",
        "legal_entity",
        "payment_method",
        "status",
        "payment_date",
        "created_by",
    ]

    search_fields = [
        "supplier_invoice__invoice_number",
        "transaction_reference",
        "check_number",
        "bank_account",
        "notes",
    ]

    ordering_fields = [
        "payment_date",
        "amount",
        "status",
        "created_at",
        "updated_at",
    ]

    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset()

        return apply_legal_entity_scope(
            qs,
            self.request.user,
            legal_entity_field="legal_entity",
        )


class BudgetCategoryViewSet(BaseModelViewSet):
    """
    Catálogo de líneas del presupuesto de caja.

    No lleva scope por sociedad: las 34 categorías son las mismas para todas
    las razones sociales — lo que cambia por sociedad es el monto, que vive en
    Budget.
    """

    queryset = BudgetCategory.objects.all()
    serializer_class = BudgetCategorySerializer
    permission_classes = [CanManageFinance]

    filterset_fields = ["block", "sign", "is_active"]
    search_fields = ["code", "name"]
    ordering_fields = ["display_order", "code", "name", "block"]
    ordering = ["display_order", "code"]


class BudgetViewSet(BaseModelViewSet):
    queryset = Budget.objects.select_related(
        "legal_entity",
        "branch",
        "cost_center",
        "category",
        "budget_category",
    ).all()

    serializer_class = BudgetSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = [
        "legal_entity",
        "branch",
        "cost_center",
        "category",
        "budget_category",
        "budget_category__block",
        "period_year",
        "period_month",
    ]

    search_fields = [
        "legal_entity__name",
        "branch__name",
        "cost_center__name",
        "category__name",
        "budget_category__name",
        "budget_category__code",
        "notes",
    ]

    ordering_fields = [
        "period_year",
        "period_month",
        "budget_amount",
        "committed_amount",
        "consumed_amount",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-period_year",
        "-period_month",
    ]

    def get_queryset(self):
        qs = super().get_queryset()

        return apply_legal_entity_scope(
            qs,
            self.request.user,
            legal_entity_field="legal_entity",
        )

class SupplierInvoiceItemViewSet(BaseModelViewSet):
    queryset = SupplierInvoiceItem.objects.select_related(
        "supplier_invoice",
        "product",
        "category",
        "cost_center",
        "budget_category",
    ).all()

    serializer_class = SupplierInvoiceItemSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = [
        "supplier_invoice",
        "product",
        "category",
        "cost_center",
        "budget_category",
    ]
    search_fields = ["description", "product__name", "supplier_invoice__invoice_number"]
    ordering_fields = ["created_at", "total_amount"]
    ordering = ["created_at"]

    def get_queryset(self):
        qs = super().get_queryset()

        return apply_legal_entity_scope(
            qs,
            self.request.user,
            legal_entity_field="supplier_invoice__legal_entity",
        )
