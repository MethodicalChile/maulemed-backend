from rest_framework import serializers

from apps.organizations.serializers import BranchSmallSerializer
from apps.products.serializers import ProductSmallSerializer
from apps.suppliers.serializers import SupplierSmallSerializer
from .models import Warehouse, InventoryStock, InventoryLot, InventoryMovement


class WarehouseSmallSerializer(serializers.ModelSerializer):
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)

    class Meta:
        model = Warehouse
        fields = ["uuid", "name", "warehouse_type", "branch_detail"]


class InventoryLotSmallSerializer(serializers.ModelSerializer):
    product_detail = ProductSmallSerializer(source="product", read_only=True)

    class Meta:
        model = InventoryLot
        fields = [
            "uuid",
            "lot_number",
            "expiration_date",
            "quantity",
            "status",
            "product_detail",
        ]


class WarehouseSerializer(serializers.ModelSerializer):
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)

    class Meta:
        model = Warehouse
        exclude = ["id", "deleted_at"]


class InventoryStockSerializer(serializers.ModelSerializer):
    warehouse_detail = WarehouseSmallSerializer(source="warehouse", read_only=True)
    product_detail = ProductSmallSerializer(source="product", read_only=True)
    available_quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        read_only=True,
    )

    class Meta:
        model = InventoryStock
        exclude = ["id", "deleted_at"]


class InventoryLotSerializer(serializers.ModelSerializer):
    warehouse_detail = WarehouseSmallSerializer(source="warehouse", read_only=True)
    product_detail = ProductSmallSerializer(source="product", read_only=True)
    supplier_detail = SupplierSmallSerializer(source="supplier", read_only=True)

    class Meta:
        model = InventoryLot
        exclude = ["id", "deleted_at"]


class InventoryMovementSerializer(serializers.ModelSerializer):
    warehouse_origin_detail = WarehouseSmallSerializer(source="warehouse_origin", read_only=True)
    warehouse_destination_detail = WarehouseSmallSerializer(source="warehouse_destination", read_only=True)
    product_detail = ProductSmallSerializer(source="product", read_only=True)
    lot_detail = InventoryLotSmallSerializer(source="lot", read_only=True)

    class Meta:
        model = InventoryMovement
        exclude = ["id", "deleted_at"]
