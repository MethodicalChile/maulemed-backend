from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.organizations.models import Branch, CostCenter, LegalEntity
from apps.organizations.serializers import (
    BranchSmallSerializer,
    CostCenterSmallSerializer,
    LegalEntitySmallSerializer,
)
from apps.products.models import ProductCategory
from apps.products.serializers import (
    ProductCategorySmallSerializer,
    ProductSmallSerializer,
)
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.serializers import PurchaseOrderSmallSerializer
from apps.suppliers.models import Supplier
from apps.suppliers.serializers import SupplierSmallSerializer

from .models import (
    Budget,
    BudgetCategory,
    Payment,
    SupplierInvoice,
    SupplierInvoiceItem,
)


# Querysets mínimos para validación de relaciones por PK.
BRANCH_PK_QS = Branch.objects.only("id")
COST_CENTER_PK_QS = CostCenter.objects.only("id")
PRODUCT_CATEGORY_PK_QS = ProductCategory.objects.only("id")
BUDGET_CATEGORY_PK_QS = BudgetCategory.objects.only("id")


class SupplierInvoiceItemSerializer(serializers.ModelSerializer):
    product_detail = ProductSmallSerializer(
        source="product",
        read_only=True,
    )
    cost_center_detail = CostCenterSmallSerializer(
        source="cost_center",
        read_only=True,
    )
    category_detail = ProductCategorySmallSerializer(
        source="category",
        read_only=True,
    )

    class Meta:
        model = SupplierInvoiceItem
        exclude = ["id", "deleted_at"]
        read_only_fields = ["total_amount"]

    def validate(self, attrs):
        product = attrs.get("product")
        if product is None and self.instance:
            product = getattr(self.instance, "product", None)

        description = attrs.get("description")
        if description is None and self.instance:
            description = getattr(
                self.instance,
                "description",
                None,
            )

        if product is None and not description:
            raise serializers.ValidationError(
                "Indica un producto o una descripción para el ítem."
            )

        return attrs


class SupplierInvoiceSmallSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSmallSerializer(
        source="supplier",
        read_only=True,
    )

    class Meta:
        model = SupplierInvoice
        fields = [
            "uuid",
            "invoice_number",
            "status",
            "total_amount",
            "supplier_detail",
        ]


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    supplier = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Supplier.objects.all(),
        required=False,
        allow_null=True,
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
        required=False,
        allow_null=True,
    )
    cost_center = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )
    purchase_order = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=PurchaseOrder.objects.all(),
        required=False,
        allow_null=True,
    )
    supplier_detail = SupplierSmallSerializer(
        source="supplier",
        read_only=True,
    )
    legal_entity_detail = LegalEntitySmallSerializer(
        source="legal_entity",
        read_only=True,
    )
    branch_detail = BranchSmallSerializer(
        source="branch",
        read_only=True,
    )
    cost_center_detail = CostCenterSmallSerializer(
        source="cost_center",
        read_only=True,
    )
    purchase_order_detail = PurchaseOrderSmallSerializer(
        source="purchase_order",
        read_only=True,
    )

    items = SupplierInvoiceItemSerializer(
        many=True,
        read_only=True,
    )

    items_total_amount = serializers.SerializerMethodField()
    items_match_total = serializers.SerializerMethodField()

    days_to_due = serializers.IntegerField(
        read_only=True,
    )
    is_overdue = serializers.BooleanField(
        read_only=True,
    )

    class Meta:
        model = SupplierInvoice
        exclude = ["id", "deleted_at"]

    def _get_items_check(self, obj):
        """
        Calcula una sola vez la validación de detalle por factura.

        Antes items_total_amount e items_match_total llamaban cada uno al
        servicio, por lo que el mismo cálculo podía ejecutarse dos veces.
        """
        cache_attr = "_serializer_items_check_cache"

        if hasattr(obj, cache_attr):
            return getattr(obj, cache_attr)

        from .services import invoice_items_match_total

        result = invoice_items_match_total(obj)
        setattr(obj, cache_attr, result)

        return result

    @staticmethod
    def _has_items(obj):
        """
        Usa la caché de prefetch cuando está disponible, evitando un EXISTS
        adicional por factura.
        """
        prefetched = getattr(
            obj,
            "_prefetched_objects_cache",
            {},
        ).get("items")

        if prefetched is not None:
            return bool(prefetched)

        return obj.items.exists()

    def get_items_total_amount(self, obj):
        return self._get_items_check(obj)[1]

    def get_items_match_total(self, obj):
        if not self._has_items(obj):
            return None

        return self._get_items_check(obj)[0]


class PaymentSerializer(serializers.ModelSerializer):
    supplier_invoice = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=SupplierInvoice.objects.all(),
        required=False,
        allow_null=True,
    )
    legal_entity = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=LegalEntity.objects.all(),
        required=False,
        allow_null=True,
    )
    supplier_invoice_detail = SupplierInvoiceSmallSerializer(
        source="supplier_invoice",
        read_only=True,
    )
    legal_entity_detail = LegalEntitySmallSerializer(
        source="legal_entity",
        read_only=True,
    )
    created_by_detail = UserSerializer(
        source="created_by",
        read_only=True,
    )

    class Meta:
        model = Payment
        exclude = ["id", "deleted_at"]


class BudgetCategorySmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = BudgetCategory
        fields = [
            "uuid",
            "code",
            "name",
            "block",
            "sign",
        ]


class BudgetCategorySerializer(serializers.ModelSerializer):
    block_label = serializers.CharField(
        source="get_block_display",
        read_only=True,
    )
    is_inflow = serializers.BooleanField(
        read_only=True,
    )

    class Meta:
        model = BudgetCategory
        exclude = ["id", "deleted_at"]


class BudgetSerializer(serializers.ModelSerializer):
    legal_entity_detail = LegalEntitySmallSerializer(
        source="legal_entity",
        read_only=True,
    )
    branch_detail = BranchSmallSerializer(
        source="branch",
        read_only=True,
    )
    cost_center_detail = CostCenterSmallSerializer(
        source="cost_center",
        read_only=True,
    )
    category_detail = ProductCategorySmallSerializer(
        source="category",
        read_only=True,
    )
    budget_category_detail = BudgetCategorySmallSerializer(
        source="budget_category",
        read_only=True,
    )

    legal_entity = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=LegalEntity.objects.all(),
        required=False,
        allow_null=True,
    )
    legal_entity = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=LegalEntity.objects.all(),
        required=True,
        allow_null=False,
    )
    branch = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Branch.objects.all(),
        required=False,
        allow_null=True,
    )
    cost_center = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )
    category = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=ProductCategory.objects.all(),
        required=False,
        allow_null=True,
    )
    budget_category = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=BudgetCategory.objects.all(),
        required=False,
        allow_null=True,
    )

    available_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    used_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    deviation_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    is_overrun = serializers.BooleanField(
        read_only=True,
    )

    class Meta:
        model = Budget
        exclude = ["id", "deleted_at"]

    def validate(self, attrs):
        legal_entity = attrs.get("legal_entity")
        if legal_entity is None and self.instance:
            legal_entity = self.instance.legal_entity

        branch = attrs.get("branch")
        if branch is None and self.instance:
            branch = getattr(
                self.instance,
                "branch",
                None,
            )

        cost_center = attrs.get("cost_center")
        if cost_center is None and self.instance:
            cost_center = getattr(
                self.instance,
                "cost_center",
                None,
            )

        category = attrs.get("category")
        if category is None and self.instance:
            category = getattr(
                self.instance,
                "category",
                None,
            )

        budget_category = attrs.get("budget_category")
        if budget_category is None and self.instance:
            budget_category = getattr(
                self.instance,
                "budget_category",
                None,
            )

        period_year = attrs.get("period_year")
        if period_year is None and self.instance:
            period_year = self.instance.period_year

        period_month = attrs.get("period_month")
        if period_month is None and self.instance:
            period_month = self.instance.period_month

        qs = Budget.objects.filter(
            legal_entity=legal_entity,
            branch=branch,
            cost_center=cost_center,
            budget_category=budget_category,
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


# from rest_framework import serializers

# from apps.accounts.serializers import UserSerializer
# from apps.organizations.models import Branch, CostCenter
# from apps.organizations.serializers import (
#     LegalEntitySmallSerializer,
#     BranchSmallSerializer,
#     CostCenterSmallSerializer,
# )
# from apps.products.models import ProductCategory
# from apps.products.serializers import ProductCategorySmallSerializer
# from apps.suppliers.serializers import SupplierSmallSerializer
# from apps.purchasing.serializers import PurchaseOrderSmallSerializer

# from .models import (
#     SupplierInvoice,
#     SupplierInvoiceItem,
#     Payment,
#     Budget,
#     BudgetCategory,
# )


# class SupplierInvoiceItemSerializer(serializers.ModelSerializer):
#     product_detail = serializers.SerializerMethodField()
#     cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)
#     category_detail = ProductCategorySmallSerializer(source="category", read_only=True)

#     class Meta:
#         model = SupplierInvoiceItem
#         exclude = ["id", "deleted_at"]
#         read_only_fields = ["total_amount"]

#     def get_product_detail(self, obj):
#         if obj.product is None:
#             return None
#         from apps.products.serializers import ProductSmallSerializer

#         return ProductSmallSerializer(obj.product).data

#     def validate(self, attrs):
#         product = attrs.get("product") or (
#             self.instance and getattr(self.instance, "product", None)
#         )
#         description = attrs.get("description") or (
#             self.instance and getattr(self.instance, "description", None)
#         )

#         # Un ítem sin producto ni descripción no se puede leer en un reporte.
#         if product is None and not description:
#             raise serializers.ValidationError(
#                 "Indica un producto o una descripción para el ítem."
#             )

#         return attrs


# class SupplierInvoiceSmallSerializer(serializers.ModelSerializer):
#     supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)

#     class Meta:
#         model = SupplierInvoice
#         fields = ["uuid", "invoice_number", "status", "total_amount", "supplier_detail"]


# class SupplierInvoiceSerializer(serializers.ModelSerializer):
#     supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)
#     legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
#     branch_detail = BranchSmallSerializer(source="branch", read_only=True)
#     cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)
#     purchase_order_detail = PurchaseOrderSmallSerializer(source="purchase_order", read_only=True)
#     items = SupplierInvoiceItemSerializer(many=True, read_only=True)
#     items_total_amount = serializers.SerializerMethodField()
#     items_match_total = serializers.SerializerMethodField()
#     days_to_due = serializers.IntegerField(read_only=True)
#     is_overdue = serializers.BooleanField(read_only=True)

#     class Meta:
#         model = SupplierInvoice
#         exclude = ["id", "deleted_at"]

#     def _items_check(self, obj):
#         from .services import invoice_items_match_total

#         return invoice_items_match_total(obj)

#     def get_items_total_amount(self, obj):
#         return self._items_check(obj)[1]

#     def get_items_match_total(self, obj):
#         # None cuando no hay detalle: no es que no cuadre, es que no se detalló.
#         if not obj.items.exists():
#             return None
#         return self._items_check(obj)[0]


# class PaymentSerializer(serializers.ModelSerializer):
#     supplier_invoice_detail = SupplierInvoiceSmallSerializer(source="supplier_invoice", read_only=True)
#     legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
#     created_by_detail = UserSerializer(source="created_by", read_only=True)

#     class Meta:
#         model = Payment
#         exclude = ["id", "deleted_at"]


# class BudgetCategorySmallSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = BudgetCategory
#         fields = ["uuid", "code", "name", "block", "sign"]


# class BudgetCategorySerializer(serializers.ModelSerializer):
#     block_label = serializers.CharField(source="get_block_display", read_only=True)
#     is_inflow = serializers.BooleanField(read_only=True)

#     class Meta:
#         model = BudgetCategory
#         exclude = ["id", "deleted_at"]


# class BudgetSerializer(serializers.ModelSerializer):
#     legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
#     branch_detail = BranchSmallSerializer(source="branch", read_only=True)
#     cost_center_detail = CostCenterSmallSerializer(source="cost_center", read_only=True)
#     category_detail = ProductCategorySmallSerializer(source="category", read_only=True)
#     budget_category_detail = BudgetCategorySmallSerializer(
#         source="budget_category", read_only=True
#     )

#     # branch, cost_center y category son FK nullable en el modelo.
#     # DRF los marca como required a menos que declaremos allow_null=True explícitamente.
#     branch = serializers.PrimaryKeyRelatedField(
#         queryset=Branch.objects.all(),
#         required=False,
#         allow_null=True,
#     )
#     cost_center = serializers.PrimaryKeyRelatedField(
#         queryset=CostCenter.objects.all(),
#         required=False,
#         allow_null=True,
#     )
#     category = serializers.PrimaryKeyRelatedField(
#         queryset=ProductCategory.objects.all(),
#         required=False,
#         allow_null=True,
#     )
#     budget_category = serializers.PrimaryKeyRelatedField(
#         queryset=BudgetCategory.objects.all(),
#         required=False,
#         allow_null=True,
#     )

#     available_amount = serializers.DecimalField(
#         max_digits=14,
#         decimal_places=2,
#         read_only=True,
#     )
#     used_amount = serializers.DecimalField(
#         max_digits=14,
#         decimal_places=2,
#         read_only=True,
#     )
#     deviation_amount = serializers.DecimalField(
#         max_digits=14,
#         decimal_places=2,
#         read_only=True,
#     )
#     is_overrun = serializers.BooleanField(read_only=True)

#     class Meta:
#         model = Budget
#         exclude = ["id", "deleted_at"]

#     def validate(self, attrs):
#         legal_entity = attrs.get("legal_entity") or (self.instance and self.instance.legal_entity)
#         branch = attrs.get("branch") or (self.instance and getattr(self.instance, "branch", None))
#         cost_center = attrs.get("cost_center") or (self.instance and getattr(self.instance, "cost_center", None))
#         category = attrs.get("category") or (self.instance and getattr(self.instance, "category", None))
#         budget_category = attrs.get("budget_category") or (
#             self.instance and getattr(self.instance, "budget_category", None)
#         )
#         period_year = attrs.get("period_year") or (self.instance and self.instance.period_year)
#         period_month = attrs.get("period_month") or (self.instance and self.instance.period_month)

#         qs = Budget.objects.filter(
#             legal_entity=legal_entity,
#             branch=branch,
#             cost_center=cost_center,
#             budget_category=budget_category,
#             category=category,
#             period_year=period_year,
#             period_month=period_month,
#         )

#         if self.instance:
#             qs = qs.exclude(pk=self.instance.pk)

#         if qs.exists():
#             raise serializers.ValidationError(
#                 "Ya existe un presupuesto para este período y alcance."
#             )

#         return attrs
