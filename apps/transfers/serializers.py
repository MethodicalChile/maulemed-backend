from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.organizations.serializers import BranchSmallSerializer
from apps.products.serializers import ProductSmallSerializer
from apps.inventory.serializers import InventoryLotSmallSerializer

from .models import StockTransfer, StockTransferItem


class StockTransferSmallSerializer(serializers.ModelSerializer):
    origin_branch_detail = BranchSmallSerializer(source="origin_branch", read_only=True)
    destination_branch_detail = BranchSmallSerializer(source="destination_branch", read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            "uuid",
            "transfer_type",
            "status",
            "origin_branch_detail",
            "destination_branch_detail",
        ]


class StockTransferItemSerializer(serializers.ModelSerializer):
    product_detail = ProductSmallSerializer(source="product", read_only=True)
    lot_detail = InventoryLotSmallSerializer(source="lot", read_only=True)

    class Meta:
        model = StockTransferItem
        exclude = ["id", "deleted_at"]


class StockTransferSerializer(serializers.ModelSerializer):
    origin_branch_detail = BranchSmallSerializer(source="origin_branch", read_only=True)
    destination_branch_detail = BranchSmallSerializer(source="destination_branch", read_only=True)

    requested_by_detail = UserSerializer(source="requested_by", read_only=True)
    approved_by_detail = UserSerializer(source="approved_by", read_only=True)
    sent_by_detail = UserSerializer(source="sent_by", read_only=True)
    received_by_detail = UserSerializer(source="received_by", read_only=True)

    parent_transfer_detail = StockTransferSmallSerializer(source="parent_transfer", read_only=True)

    items = StockTransferItemSerializer(many=True, read_only=True)

    class Meta:
        model = StockTransfer
        exclude = ["id", "deleted_at"]

    def validate(self, attrs):
        origin = attrs.get("origin_branch") or (self.instance and self.instance.origin_branch)
        destination = attrs.get("destination_branch") or (self.instance and self.instance.destination_branch)
        transfer_type = attrs.get("transfer_type") or (self.instance and self.instance.transfer_type)
        parent = attrs.get("parent_transfer") or (self.instance and self.instance.parent_transfer)

        if origin and destination and origin == destination:
            raise serializers.ValidationError(
                "La sucursal de origen y destino no pueden ser iguales."
            )

        if transfer_type == StockTransfer.TRANSFER_TYPE_RETURN and not parent:
            raise serializers.ValidationError(
                "Una devolución debe estar asociada a un préstamo anterior."
            )

        return attrs
