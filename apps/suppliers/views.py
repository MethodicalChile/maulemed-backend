from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageSuppliers

from .models import Supplier, SupplierProduct, SupplierProductPrice, SupplierProductPriceHistory
from .serializers import (
    SupplierSerializer,
    SupplierProductSerializer,
    SupplierProductPriceSerializer,
    SupplierProductPriceHistorySerializer
)

from django_filters import rest_framework as filters

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.products.models import Product

class SupplierViewSet(BaseModelViewSet):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [CanManageSuppliers]

    filterset_fields = ["is_active", "allows_credit"] if hasattr(Supplier, "allows_credit") else ["is_active"]
    search_fields = ["name", "rut", "contact_name", "email", "phone"]
    ordering_fields = ["name", "rut", "created_at", "updated_at"]
    ordering = ["name"]

class SupplierProductFilter(filters.FilterSet):
    supplier = filters.UUIDFilter(
        field_name="supplier__uuid",
    )

    product = filters.UUIDFilter(
        field_name="product__uuid",
    )

    class Meta:
        model = SupplierProduct
        fields = [
            "supplier",
            "product",
            "currency",
            "requires_purchase_order",
            "allows_credit",
            "allows_cash_purchase",
            "is_active",
        ]

class SupplierProductViewSet(BaseModelViewSet):
    queryset = (
        SupplierProduct.objects
        .select_related(
            "supplier",
            "product",
        )
        .all()
    )

    serializer_class = SupplierProductSerializer
    permission_classes = [CanManageSuppliers]
    filterset_class = SupplierProductFilter

    search_fields = [
        "supplier__name",
        "product__name",
        "supplier_sku",
    ]

    ordering_fields = [
        "last_price",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "supplier__name",
        "product__name",
    ]

    @action(
        detail=False,
        methods=["get"],
        url_path=r"product/(?P<product_uuid>[^/.]+)/price-history",
    )
    def product_price_history(
        self,
        request,
        product_uuid=None,
    ):
        try:
            product = Product.objects.get(
                uuid=product_uuid,
            )
        except Product.DoesNotExist:
            return Response(
                {
                    "detail": "Producto no encontrado.",
                },
                status=404,
            )

        supplier_products = (
            SupplierProduct.objects
            .filter(
                product=product,
                is_active=True,
            )
            .select_related(
                "supplier",
                "product",
            )
            .prefetch_related(
                "prices",
            )
            .order_by(
                "supplier__name",
            )
        )

        series = []

        for supplier_product in supplier_products:
            history = (
                supplier_product.prices
                .all()
                .order_by(
                    "effective_date",
                    "created_at",
                )
            )

            points = []

            for price_record in history:
                points.append({
                    "date": price_record.effective_date,
                    "price": price_record.price,
                    "currency": price_record.currency,
                })

            # Si no hay historial, usamos el precio actual como punto inicial.
            if not points and supplier_product.last_price is not None:
                points.append({
                    "date": supplier_product.created_at,
                    "price": supplier_product.last_price,
                    "currency": supplier_product.currency,
                })

            # Extendemos el último precio hasta hoy.
            if points:
                last_point = points[-1]

                points.append({
                    "date": timezone.now(),
                    "price": last_point["price"],
                    "currency": last_point["currency"],
                    "is_projection": True,
                })

            series.append({
                "supplier_product_uuid": supplier_product.uuid,
                "supplier_uuid": supplier_product.supplier.uuid,
                "supplier_name": supplier_product.supplier.name,
                "supplier_sku": supplier_product.supplier_sku,
                "current_price": supplier_product.last_price,
                "currency": supplier_product.currency,
                "points": points,
            })

        return Response({
            "data": {
                "product": {
                    "uuid": product.uuid,
                    "name": product.name,
                    "sku": product.sku,
                    "internal_code": product.internal_code,
                },
                "series": series,
            },
            "status": "success",
            "message": "Historial de precios obtenido correctamente.",
        })

class SupplierProductPriceViewSet(BaseModelViewSet):
    queryset = SupplierProductPrice.objects.select_related("supplier_product").all()
    serializer_class = SupplierProductPriceSerializer
    permission_classes = [CanManageSuppliers]

    filterset_fields = ["supplier_product", "currency", "valid_from", "valid_to"]
    search_fields = [
        "supplier_product__supplier__name",
        "supplier_product__product__name",
        "source",
    ]
    ordering_fields = ["price", "valid_from", "valid_to", "created_at"]
    ordering = ["-valid_from"]

class SupplierProductPriceHistoryFilter(filters.FilterSet):
    supplier_product = filters.UUIDFilter(
        field_name="supplier_product__uuid",
    )

    product = filters.UUIDFilter(
        field_name="supplier_product__product__uuid",
    )

    supplier = filters.UUIDFilter(
        field_name="supplier_product__supplier__uuid",
    )

    class Meta:
        model = SupplierProductPriceHistory
        fields = [
            "supplier_product",
            "product",
            "supplier",
            "currency",
            "source",
        ]

class SupplierProductPriceHistoryViewSet(BaseModelViewSet):
    queryset = (
        SupplierProductPriceHistory.objects
        .select_related(
            "supplier_product",
            "supplier_product__supplier",
            "supplier_product__product",
            "changed_by",
        )
        .all()
    )

    serializer_class = SupplierProductPriceHistorySerializer
    permission_classes = [CanManageSuppliers]

    filterset_class = SupplierProductPriceHistoryFilter

    ordering_fields = [
        "effective_date",
        "price",
        "created_at",
    ]

    ordering = [
        "-effective_date",
    ]