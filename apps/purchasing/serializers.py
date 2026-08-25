from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.organizations.serializers import (
    BranchSmallSerializer,
    LegalEntitySmallSerializer,
    CostCenterSmallSerializer,
)
from apps.organizations.models import Branch, LegalEntity, CostCenter
from apps.products.serializers import ProductSmallSerializer
from apps.products.models import Product
from apps.suppliers.serializers import SupplierSmallSerializer
from apps.suppliers.models import Supplier
from apps.inventory.serializers import WarehouseSmallSerializer
from apps.inventory.models import Warehouse

from .models import (
    ApprovalRule,
    SupplyRequest,
    SupplyRequestItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierClaim,
)


class SupplyRequestSmallSerializer(serializers.ModelSerializer):
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)

    class Meta:
        model = SupplyRequest
        fields = ["uuid", "status", "period_year", "period_month", "branch_detail"]


class PurchaseOrderSmallSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = ["uuid", "order_number", "status", "total_amount", "supplier_detail"]


class PurchaseReceiptSmallSerializer(serializers.ModelSerializer):
    purchase_order_detail = PurchaseOrderSmallSerializer(source="purchase_order", read_only=True)

    class Meta:
        model = PurchaseReceipt
        fields = ["uuid", "status", "received_at", "purchase_order_detail"]


class SupplyRequestItemSerializer(serializers.ModelSerializer):
    supply_request = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=SupplyRequest.objects.all(),
    )
    product = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Product.objects.all(),
    )
    product_detail = ProductSmallSerializer(source="product", read_only=True)

    class Meta:
        model = SupplyRequestItem
        exclude = ["id", "deleted_at"]


class SupplyRequestSerializer(serializers.ModelSerializer):
    branch = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Branch.objects.all(),
    )
    legal_entity = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=LegalEntity.objects.all(),
        required=False,
        allow_null=True,
    )
    cost_center = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)

    requested_by_detail = UserSerializer(source="requested_by", read_only=True)
    reviewed_by_detail = UserSerializer(source="reviewed_by", read_only=True)
    approved_by_detail = UserSerializer(source="approved_by", read_only=True)

    items = SupplyRequestItemSerializer(many=True, read_only=True)

    class Meta:
        model = SupplyRequest
        exclude = ["id", "deleted_at"]


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    purchase_order = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=PurchaseOrder.objects.all(),
    )
    product = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Product.objects.all(),
    )
    product_detail = ProductSmallSerializer(source="product", read_only=True)

    pending_quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        read_only=True,
    )

    class Meta:
        model = PurchaseOrderItem
        exclude = ["id", "deleted_at"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Supplier.objects.all(),
    )
    legal_entity = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=LegalEntity.objects.all(),
        required=False,
        allow_null=True,
    )
    branch = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Branch.objects.all(),
    )
    cost_center = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )
    supply_request = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=SupplyRequest.objects.all(),
        required=False,
        allow_null=True,
    )
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)
    cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)
    supply_request_detail = SupplyRequestSmallSerializer(source="supply_request", read_only=True)

    requested_by_detail = UserSerializer(source="requested_by", read_only=True)
    approved_by_detail = UserSerializer(source="approved_by", read_only=True)

    items = PurchaseOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        exclude = ["id", "deleted_at"]


class PurchaseReceiptItemSerializer(serializers.ModelSerializer):
    purchase_receipt = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=PurchaseReceipt.objects.all(),
    )
    product = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Product.objects.all(),
    )
    product_detail = ProductSmallSerializer(source="product", read_only=True)

    class Meta:
        model = PurchaseReceiptItem
        exclude = ["id", "deleted_at"]


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    purchase_order = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=PurchaseOrder.objects.all(),
    )
    branch = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Branch.objects.all(),
    )
    warehouse = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Warehouse.objects.all(),
    )
    purchase_order_detail = PurchaseOrderSmallSerializer(source="purchase_order", read_only=True)
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)
    warehouse_detail = WarehouseSmallSerializer(source="warehouse", read_only=True)
    received_by_detail = UserSerializer(source="received_by", read_only=True)

    items = PurchaseReceiptItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseReceipt
        exclude = ["id", "deleted_at"]


class SupplierClaimSerializer(serializers.ModelSerializer):
    purchase_receipt = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=PurchaseReceipt.objects.all(),
        required=False,
        allow_null=True,
    )
    supplier = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Supplier.objects.all(),
        required=False,
        allow_null=True,
    )
    purchase_receipt_detail = PurchaseReceiptSmallSerializer(source="purchase_receipt", read_only=True)
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)
    created_by_detail = UserSerializer(source="created_by", read_only=True)

    class Meta:
        model = SupplierClaim
        exclude = ["id", "deleted_at"]


class ApprovalRuleSerializer(serializers.ModelSerializer):
    legal_entity_detail = LegalEntitySmallSerializer(
        source="legal_entity", read_only=True
    )
    required_role_code = serializers.CharField(
        source="required_role.code", read_only=True
    )
    required_role_name = serializers.CharField(
        source="required_role.name", read_only=True
    )

    class Meta:
        model = ApprovalRule
        exclude = ["id", "deleted_at"]

    def validate(self, attrs):
        amount_from = attrs.get("amount_from")
        if amount_from is None and self.instance:
            amount_from = self.instance.amount_from

        amount_to = attrs.get("amount_to")
        if amount_to is None and self.instance and "amount_to" not in attrs:
            amount_to = self.instance.amount_to

        if amount_to is not None and amount_from is not None:
            if amount_to <= amount_from:
                raise serializers.ValidationError(
                    "El monto superior debe ser mayor al inferior."
                )

        return attrs
