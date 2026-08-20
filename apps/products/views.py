from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageCatalogs, CanManageProducts
from apps.common.scopes import apply_branch_scope
from django_filters import rest_framework as filters

from .models import ProductCategory, UnitOfMeasure, Product, BranchProduct
from .serializers import (
    ProductCategorySerializer,
    UnitOfMeasureSerializer,
    ProductSerializer,
    BranchProductSerializer,
)


class ProductCategoryViewSet(BaseModelViewSet):
    queryset = ProductCategory.objects.all().order_by("name")
    serializer_class = ProductCategorySerializer
    permission_classes = [CanManageCatalogs]

    filterset_fields = ["is_active"]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at", "updated_at"]
    ordering = ["name"]


class UnitOfMeasureViewSet(BaseModelViewSet):
    queryset = UnitOfMeasure.objects.all().order_by("code")
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [CanManageCatalogs]

    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at", "updated_at"]
    ordering = ["code"]


class ProductViewSet(BaseModelViewSet):
    queryset = Product.objects.select_related("category", "unit").all().order_by("name")
    serializer_class = ProductSerializer
    permission_classes = [CanManageProducts]

    filterset_fields = [
        "category",
        "unit",
        "requires_lot",
        "requires_expiration_date",
        "requires_sanitary_resolution",
        "is_medication",
        "is_controlled",
        "is_active",
    ]
    search_fields = ["name", "description", "sku", "barcode", "internal_code"]
    ordering_fields = ["name", "sku", "internal_code", "created_at", "updated_at"]
    ordering = ["name"]


class BranchProductFilter(filters.FilterSet):
    branch = filters.UUIDFilter(field_name="branch__uuid")
    product = filters.UUIDFilter(field_name="product__uuid")

    class Meta:
        model = BranchProduct
        fields = ["branch", "product", "cost_center"]


class BranchProductViewSet(BaseModelViewSet):
    queryset = BranchProduct.objects.select_related(
        "branch",
        "product",
        "cost_center",
    ).all()
    serializer_class = BranchProductSerializer
    permission_classes = [CanManageCatalogs]
    filterset_class = BranchProductFilter

    search_fields = ["branch__name", "product__name", "product__internal_code"]
    ordering_fields = ["created_at", "updated_at", "min_stock", "critical_stock"]
    ordering = ["branch__name", "product__name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="branch")
