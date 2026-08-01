from rest_framework import serializers


class ConvertSupplyRequestToPurchaseOrderSerializer(serializers.Serializer):
    supplier_uuid = serializers.UUIDField()
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    tax_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        required=False,
        default="0.1900",
    )
