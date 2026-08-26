from rest_framework import serializers


class StockAdjustSerializer(serializers.Serializer):
    warehouse_uuid = serializers.UUIDField()
    product_uuid = serializers.UUIDField()

    quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
    )

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    lot_number = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    expiration_date = serializers.DateField(
        required=False,
        allow_null=True,
    )

    supplier_uuid = serializers.UUIDField(
        required=False,
        allow_null=True,
    )


class StockReserveSerializer(serializers.Serializer):
    warehouse_uuid = serializers.UUIDField()
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class StockReleaseSerializer(serializers.Serializer):
    warehouse_uuid = serializers.UUIDField()
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class StockIncreaseSerializer(serializers.Serializer):
    warehouse_uuid = serializers.UUIDField()
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    lot_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    expiration_date = serializers.DateField(required=False, allow_null=True)
    supplier_uuid = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class StockDecreaseSerializer(serializers.Serializer):
    warehouse_uuid = serializers.UUIDField()
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    lot_uuid = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True)
