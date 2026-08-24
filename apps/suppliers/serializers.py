from rest_framework import serializers

from apps.products.serializers import ProductSmallSerializer
from apps.products.models import Product
from .models import Supplier, SupplierProduct, SupplierProductPrice, SupplierProductPriceHistory

from django.db import transaction



class SupplierSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["uuid", "name", "rut", "email", "phone"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        exclude = ["id", "deleted_at"]


class SupplierProductSerializer(serializers.ModelSerializer):
    supplier = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Supplier.objects.all(),
    )
    product = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Product.objects.all(),
    )
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)
    product_detail = ProductSmallSerializer(source="product", read_only=True)

    class Meta:
        model = SupplierProduct
        exclude = ["id", "deleted_at"]

    def get_request_user(self):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return request.user
        return None

    @transaction.atomic
    def create(self, validated_data):
        supplier_product = super().create(validated_data)

        if supplier_product.last_price is not None:
            SupplierProductPriceHistory.objects.create(
                supplier_product=supplier_product,
                price=supplier_product.last_price,
                currency=supplier_product.currency,
                previous_price=None,
                source="INITIAL",
                changed_by=self.get_request_user(),
            )

        return supplier_product

    @transaction.atomic
    def update(self, instance, validated_data):
        previous_price    = instance.last_price
        previous_currency = instance.currency

        supplier_product = super().update(instance, validated_data)

        price_changed = (
            supplier_product.last_price != previous_price
            or supplier_product.currency != previous_currency
        )

        if price_changed and supplier_product.last_price is not None:
            from django.utils import timezone as tz
            previous_record = (
                SupplierProductPriceHistory.objects
                .filter(supplier_product=supplier_product, valid_until__isnull=True)
                .order_by("-effective_date")
                .first()
            )
            if previous_record:
                previous_record.valid_until = tz.now()
                previous_record.save(update_fields=["valid_until", "updated_at"])

            SupplierProductPriceHistory.objects.create(
                supplier_product=supplier_product,
                price=supplier_product.last_price,
                currency=supplier_product.currency,
                previous_price=previous_price,
                source="MANUAL",
                changed_by=self.get_request_user(),
            )

        return supplier_product


class SupplierProductSmallSerializer(serializers.ModelSerializer):
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)
    product_detail = ProductSmallSerializer(source="product", read_only=True)

    def get_request_user(self):
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            return request.user

        return None

    @transaction.atomic
    def create(self, validated_data):
        supplier_product = super().create(validated_data)

        if supplier_product.last_price is not None:
            SupplierProductPriceHistory.objects.create(
                supplier_product=supplier_product,
                price=supplier_product.last_price,
                currency=supplier_product.currency,
                previous_price=None,
                source="INITIAL",
                changed_by=self.get_request_user(),
            )

        return supplier_product

    @transaction.atomic
    def update(self, instance, validated_data):
        previous_price = instance.last_price
        previous_currency = instance.currency

        supplier_product = super().update(
            instance,
            validated_data,
        )

        price_changed = (
            supplier_product.last_price != previous_price
            or supplier_product.currency != previous_currency
        )

        if price_changed and supplier_product.last_price is not None:
            previous_record = (
                SupplierProductPriceHistory.objects
                .filter(
                    supplier_product=supplier_product,
                    valid_until__isnull=True,
                )
                .order_by("-effective_date")
                .first()
            )

            if previous_record:
                from django.utils import timezone

                previous_record.valid_until = timezone.now()
                previous_record.save(
                    update_fields=[
                        "valid_until",
                        "updated_at",
                    ]
                )

            SupplierProductPriceHistory.objects.create(
                supplier_product=supplier_product,
                price=supplier_product.last_price,
                currency=supplier_product.currency,
                previous_price=previous_price,
                source="MANUAL",
                changed_by=self.get_request_user(),
            )

        return supplier_product

    class Meta:
        model = SupplierProduct
        fields = [
            "uuid",
            "supplier_detail",
            "product_detail",
            "supplier_sku",
            "last_price",
            "currency",
        ]


class SupplierProductPriceSerializer(serializers.ModelSerializer):
    supplier_product = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=SupplierProduct.objects.all(),
    )
    supplier_product_detail = SupplierProductSmallSerializer(source="supplier_product", read_only=True)

    class Meta:
        model = SupplierProductPrice
        exclude = ["id", "deleted_at"]

class SupplierProductPriceHistorySerializer(
    serializers.ModelSerializer
):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SupplierProductPriceHistory
        exclude = [
            "id",
            "deleted_at",
        ]

        read_only_fields = [
            "supplier_product",
            "price",
            "currency",
            "previous_price",
            "effective_date",
            "valid_until",
            "source",
            "changed_by",
        ]

    def get_changed_by_name(self, obj):
        if not obj.changed_by:
            return None

        full_name = obj.changed_by.get_full_name()

        return full_name or obj.changed_by.username
