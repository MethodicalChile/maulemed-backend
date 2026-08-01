from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.organizations.models import Branch, CostCenter
from apps.organizations.serializers import (
    LegalEntitySmallSerializer,
    BranchSmallSerializer,
    CostCenterSmallSerializer,
)
from apps.products.models import ProductCategory
from apps.products.serializers import ProductCategorySmallSerializer
from apps.suppliers.serializers import SupplierSmallSerializer
from apps.purchasing.serializers import PurchaseOrderSmallSerializer

from .models import SupplierInvoice, Payment, Budget


class SupplierInvoiceSmallSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)

    class Meta:
        model = SupplierInvoice
        fields = ["uuid", "invoice_number", "status", "total_amount", "supplier_detail"]


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)
    cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)
    purchase_order_detail = PurchaseOrderSmallSerializer(source="purchase_order", read_only=True)

    class Meta:
        model = SupplierInvoice
        exclude = ["id", "deleted_at"]


class PaymentSerializer(serializers.ModelSerializer):
    supplier_invoice_detail = SupplierInvoiceSmallSerializer(source="supplier_invoice", read_only=True)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    created_by_detail = UserSerializer(source="created_by", read_only=True)

    class Meta:
        model = Payment
        exclude = ["id", "deleted_at"]


class BudgetSerializer(serializers.ModelSerializer):
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)
    cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)
    category_detail = ProductCategorySmallSerializer(source="category", read_only=True)

    # branch, cost_center y category son FK nullable en el modelo.
    # DRF los marca como required a menos que declaremos allow_null=True explícitamente.
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(),
        required=False,
        allow_null=True,
    )
    cost_center = serializers.PrimaryKeyRelatedField(
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=ProductCategory.objects.all(),
        required=False,
        allow_null=True,
    )

    available_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Budget
        exclude = ["id", "deleted_at"]

    def validate(self, attrs):
        legal_entity = attrs.get("legal_entity") or (self.instance and self.instance.legal_entity)
        branch = attrs.get("branch") or (self.instance and getattr(self.instance, "branch", None))
        cost_center = attrs.get("cost_center") or (self.instance and getattr(self.instance, "cost_center", None))
        category = attrs.get("category") or (self.instance and getattr(self.instance, "category", None))
        period_year = attrs.get("period_year") or (self.instance and self.instance.period_year)
        period_month = attrs.get("period_month") or (self.instance and self.instance.period_month)

        qs = Budget.objects.filter(
            legal_entity=legal_entity,
            branch=branch,
            cost_center=cost_center,
            category=category,
            period_year=period_year,
            period_month=period_month,
        )

        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError(
                "Ya existe un presupuesto para este período y alcance."
            )

        return attrs
