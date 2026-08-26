from datetime import timedelta
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import action

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageInventory, CanManageWarehouses
from apps.common.scopes import apply_branch_scope
from apps.common.responses import api_response
from apps.audit.services import audit_action

from apps.products.models import Product
from apps.suppliers.models import Supplier

from .models import Warehouse, InventoryStock, InventoryLot, InventoryMovement
from .serializers import (
    WarehouseSerializer,
    InventoryStockSerializer,
    InventoryLotSerializer,
    InventoryMovementSerializer,
)
from .action_serializers import (
    StockAdjustSerializer,
    StockReserveSerializer,
    StockReleaseSerializer,
    StockIncreaseSerializer,
    StockDecreaseSerializer,
)
from .services import (
    increase_stock,
    decrease_stock,
    adjust_stock,
    reserve_stock,
    release_reserved_stock,
)


class WarehouseViewSet(BaseModelViewSet):
    queryset = Warehouse.objects.select_related("branch").all().order_by("name")
    serializer_class = WarehouseSerializer
    permission_classes = [CanManageWarehouses]

    filterset_fields = ["branch", "warehouse_type", "is_active"]
    search_fields = ["name", "branch__name"]
    ordering_fields = ["name", "created_at", "updated_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="branch")


class InventoryStockViewSet(BaseModelViewSet):
    queryset = InventoryStock.objects.select_related("warehouse", "warehouse__branch", "product").all()
    serializer_class = InventoryStockSerializer
    permission_classes = [CanManageInventory]

    filterset_fields = ["warehouse", "product", "warehouse__branch"]
    search_fields = ["warehouse__name", "warehouse__branch__name", "product__name", "product__internal_code"]
    ordering_fields = ["quantity", "reserved_quantity", "updated_at", "created_at"]
    ordering = ["warehouse__branch__name", "product__name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="warehouse__branch")

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        from apps.products.models import BranchProduct

        qs = self.get_queryset()

        # Cargar todos los BranchProduct relevantes en una sola query — evita N+1
        branch_ids  = qs.values_list("warehouse__branch_id", flat=True).distinct()
        product_ids = qs.values_list("product_id", flat=True).distinct()

        branch_products = {
            (bp.product_id, bp.branch_id): bp
            for bp in BranchProduct.objects.filter(
                branch_id__in=branch_ids,
                product_id__in=product_ids,
                is_active=True,
            )
        }

        low_stock_items = []
        for stock in qs.select_related("warehouse__branch", "product"):
            bp = branch_products.get((stock.product_id, stock.warehouse.branch_id))
            if not bp:
                continue
            threshold = bp.critical_stock or bp.min_stock
            if threshold is None:
                continue
            if stock.available_quantity <= threshold:
                low_stock_items.append(stock)

        serializer = self.get_serializer(low_stock_items, many=True)

        return api_response(
            data=serializer.data,
            message="Stock crítico obtenido correctamente.",
        )


class InventoryLotViewSet(BaseModelViewSet):
    queryset = InventoryLot.objects.select_related("warehouse", "warehouse__branch", "product", "supplier").all()
    serializer_class = InventoryLotSerializer
    permission_classes = [CanManageInventory]

    filterset_fields = ["warehouse", "product", "supplier", "status", "expiration_date"]
    search_fields = ["product__name", "product__internal_code", "lot_number", "supplier__name"]
    ordering_fields = ["expiration_date", "quantity", "created_at", "updated_at"]
    ordering = ["expiration_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return apply_branch_scope(qs, self.request.user, branch_field="warehouse__branch")

    @action(detail=False, methods=["get"])
    def expiring_soon(self, request):
        days = int(request.GET.get("days", 30))
        today = timezone.now().date()
        limit_date = today + timedelta(days=days)

        qs = self.get_queryset().filter(
            expiration_date__isnull=False,
            expiration_date__gte=today,
            expiration_date__lte=limit_date,
        ).order_by("expiration_date")

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs, many=True)
        return api_response(
            data=serializer.data,
            message="Lotes próximos a vencer obtenidos correctamente.",
        )

    @action(detail=False, methods=["get"])
    def expired(self, request):
        today = timezone.now().date()

        qs = self.get_queryset().filter(
            expiration_date__isnull=False,
            expiration_date__lt=today,
        ).order_by("expiration_date")

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs, many=True)
        return api_response(
            data=serializer.data,
            message="Lotes vencidos obtenidos correctamente.",
        )


class InventoryMovementViewSet(BaseModelViewSet):
    queryset = InventoryMovement.objects.select_related(
        "warehouse_origin",
        "warehouse_origin__branch",
        "warehouse_destination",
        "warehouse_destination__branch",
        "product",
        "lot",
    ).all()
    serializer_class = InventoryMovementSerializer
    permission_classes = [CanManageInventory]

    filterset_fields = ["movement_type", "product", "warehouse_origin", "warehouse_destination"]
    search_fields = ["product__name", "product__internal_code", "reason", "reference_type"]
    ordering_fields = ["created_at", "quantity"]
    ordering = ["-created_at"]

    def get_queryset(self):
        from django.db.models import Q
        from apps.organizations.models import Branch

        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs

        allowed_branches = apply_branch_scope(Branch.objects.all(), self.request.user, branch_field="self")
        branch_ids = allowed_branches.values_list("id", flat=True)

        return qs.filter(
            Q(warehouse_origin__branch_id__in=branch_ids) |
            Q(warehouse_destination__branch_id__in=branch_ids)
        )

    def _get_warehouse(self, warehouse_uuid):
        return get_object_or_404(Warehouse, uuid=warehouse_uuid)

    def _get_product(self, product_uuid):
        return get_object_or_404(Product, uuid=product_uuid)

    def _get_supplier(self, supplier_uuid):
        if not supplier_uuid:
            return None
        return get_object_or_404(Supplier, uuid=supplier_uuid)

    def _get_lot(self, lot_uuid):
        if not lot_uuid:
            return None
        return get_object_or_404(InventoryLot, uuid=lot_uuid)

    def _handle_validation_error(self, exc):
        return api_response(
            data={"detail": str(exc)},
            status_code=400,
            status_text="error",
            message="No se pudo realizar la operación de inventario.",
        )

    @action(detail=False, methods=["post"])
    def increase(self, request):
        serializer = StockIncreaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            result = increase_stock(
                warehouse=self._get_warehouse(data["warehouse_uuid"]),
                product=self._get_product(data["product_uuid"]),
                quantity=data["quantity"],
                lot_number=data.get("lot_number"),
                expiration_date=data.get("expiration_date"),
                supplier=self._get_supplier(data.get("supplier_uuid")),
                reason=data.get("reason") or "Ingreso manual de stock",
                reference_type="INGRESO_MANUAL",
                created_by_uuid=request.user.profile.uuid if hasattr(request.user, "profile") else None,
            )
        except ValidationError as exc:
            return self._handle_validation_error(exc)

        audit_action(
            request=request,
            action="INCREASE_STOCK",
            instance=result["stock"],
            new_data={
                "stock_uuid": str(result["stock"].uuid),
                "lot_uuid": str(result["lot"].uuid) if result["lot"] else None,
                "movement_uuid": str(result["movement"].uuid),
            },
            notes="Ingreso manual de stock.",
        )

        return api_response(
            data={
                "stock": InventoryStockSerializer(result["stock"]).data,
                "lot": InventoryLotSerializer(result["lot"]).data if result["lot"] else None,
                "movement": InventoryMovementSerializer(result["movement"]).data,
            },
            message="Stock ingresado correctamente.",
        )

    @action(detail=False, methods=["post"])
    def decrease(self, request):
        serializer = StockDecreaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            result = decrease_stock(
                warehouse=self._get_warehouse(data["warehouse_uuid"]),
                product=self._get_product(data["product_uuid"]),
                quantity=data["quantity"],
                lot=self._get_lot(data.get("lot_uuid")),
                movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
                reason=data.get("reason") or "Egreso manual de stock",
                reference_type="EGRESO_MANUAL",
                created_by_uuid=request.user.profile.uuid if hasattr(request.user, "profile") else None,
            )
        except ValidationError as exc:
            return self._handle_validation_error(exc)

        audit_action(
            request=request,
            action="DECREASE_STOCK",
            instance=result["stock"],
            new_data={
                "stock_uuid": str(result["stock"].uuid),
                "lot_uuid": str(result["lot"].uuid) if result["lot"] else None,
                "movement_uuid": str(result["movement"].uuid),
            },
            notes="Egreso manual de stock.",
        )

        return api_response(
            data={
                "stock": InventoryStockSerializer(result["stock"]).data,
                "lot": InventoryLotSerializer(result["lot"]).data if result["lot"] else None,
                "movement": InventoryMovementSerializer(result["movement"]).data,
            },
            message="Stock descontado correctamente.",
        )

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        serializer = StockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            result = adjust_stock(
                warehouse=self._get_warehouse(
                    data["warehouse_uuid"]
                ),
                product=self._get_product(
                    data["product_uuid"]
                ),
                quantity=data["quantity"],
                reason=data.get("reason"),
                lot_number=data.get("lot_number"),
                expiration_date=data.get("expiration_date"),
                supplier=self._get_supplier(
                    data.get("supplier_uuid")
                ),
                created_by_uuid=(
                    request.user.profile.uuid
                    if hasattr(request.user, "profile")
                    else None
                ),
            )
        except ValidationError as exc:
            return self._handle_validation_error(exc)

        audit_action(
            request=request,
            action="ADJUST_STOCK",
            instance=result["stock"],
            new_data={
                "stock_uuid": str(result["stock"].uuid),
                "lot_uuid": str(result["lot"].uuid) if result["lot"] else None,
                "movement_uuid": str(result["movement"].uuid),
            },
            notes="Ajuste manual de stock.",
        )

        return api_response(
            data={
                "stock": InventoryStockSerializer(result["stock"]).data,
                "lot": InventoryLotSerializer(result["lot"]).data if result["lot"] else None,
                "movement": InventoryMovementSerializer(result["movement"]).data,
            },
            message="Stock ajustado correctamente.",
        )

    @action(detail=False, methods=["post"])
    def reserve(self, request):
        serializer = StockReserveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            stock = reserve_stock(
                warehouse=self._get_warehouse(data["warehouse_uuid"]),
                product=self._get_product(data["product_uuid"]),
                quantity=data["quantity"],
            )
        except ValidationError as exc:
            return self._handle_validation_error(exc)

        audit_action(
            request=request,
            action="RESERVE_STOCK",
            instance=stock,
            notes="Reserva manual de stock.",
        )

        return api_response(
            data=InventoryStockSerializer(stock).data,
            message="Stock reservado correctamente.",
        )

    @action(detail=False, methods=["post"])
    def release(self, request):
        serializer = StockReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            stock = release_reserved_stock(
                warehouse=self._get_warehouse(data["warehouse_uuid"]),
                product=self._get_product(data["product_uuid"]),
                quantity=data["quantity"],
            )
        except ValidationError as exc:
            return self._handle_validation_error(exc)

        audit_action(
            request=request,
            action="RELEASE_RESERVED_STOCK",
            instance=stock,
            notes="Liberación de stock reservado.",
        )

        return api_response(
            data=InventoryStockSerializer(stock).data,
            message="Stock reservado liberado correctamente.",
        )
