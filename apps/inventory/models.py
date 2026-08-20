from django.db import models
from django.core.exceptions import ValidationError

from apps.common.models import BaseModel
from apps.organizations.models import Branch
from apps.products.models import Product
from apps.suppliers.models import Supplier


class Warehouse(BaseModel):
    WAREHOUSE_TYPE_GENERAL = "GENERAL"
    WAREHOUSE_TYPE_MEDICAL = "INSUMOS_MEDICOS"
    WAREHOUSE_TYPE_OFFICE = "OFICINA"
    WAREHOUSE_TYPE_CLEANING = "ASEO"
    WAREHOUSE_TYPE_MEDICATION = "MEDICAMENTOS"
    WAREHOUSE_TYPE_EMERGENCY_CART = "CARRO_PARO"

    WAREHOUSE_TYPE_CHOICES = [
        (WAREHOUSE_TYPE_GENERAL, "General"),
        (WAREHOUSE_TYPE_MEDICAL, "Insumos médicos"),
        (WAREHOUSE_TYPE_OFFICE, "Oficina"),
        (WAREHOUSE_TYPE_CLEANING, "Aseo"),
        (WAREHOUSE_TYPE_MEDICATION, "Medicamentos"),
        (WAREHOUSE_TYPE_EMERGENCY_CART, "Carro de paro"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="warehouses",
    )
    name = models.CharField(max_length=150)
    warehouse_type = models.CharField(
        max_length=50,
        choices=WAREHOUSE_TYPE_CHOICES,
        default=WAREHOUSE_TYPE_GENERAL,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "warehouses"
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="uq_warehouse_branch_name",
            )
        ]

    def __str__(self):
        return f"{self.branch} - {self.name}"


class InventoryStock(BaseModel):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="stocks",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stocks",
    )

    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    reserved_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    min_level = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    max_level = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    last_count_date = models.DateField(blank=True, null=True)

    class Meta:
        db_table = "inventory_stocks"
        verbose_name = "Inventory Stock"
        verbose_name_plural = "Inventory Stocks"
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "product"],
                name="uq_inventory_stock",
            ),
            models.CheckConstraint(
                check=models.Q(quantity__gte=0),
                name="chk_inventory_quantity_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(reserved_quantity__gte=0),
                name="chk_reserved_quantity_non_negative",
            ),
        ]

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

    def clean(self):
        if self.reserved_quantity > self.quantity:
            raise ValidationError("La cantidad reservada no puede ser mayor al stock total.")

    def __str__(self):
        return f"{self.warehouse} - {self.product} - {self.quantity}"


class InventoryLot(BaseModel):
    STATUS_AVAILABLE = "DISPONIBLE"
    STATUS_RESERVED = "RESERVADO"
    STATUS_EXPIRED = "VENCIDO"
    STATUS_CONSUMED = "CONSUMIDO"
    STATUS_BLOCKED = "BLOQUEADO"

    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Disponible"),
        (STATUS_RESERVED, "Reservado"),
        (STATUS_EXPIRED, "Vencido"),
        (STATUS_CONSUMED, "Consumido"),
        (STATUS_BLOCKED, "Bloqueado"),
    ]

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="lots",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="lots",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        related_name="inventory_lots",
        blank=True,
        null=True,
    )

    lot_number = models.CharField(max_length=120, blank=True, null=True)
    expiration_date = models.DateField(blank=True, null=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_AVAILABLE,
    )

    received_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "inventory_lots"
        verbose_name = "Inventory Lot"
        verbose_name_plural = "Inventory Lots"
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gte=0),
                name="chk_lot_quantity_non_negative",
            )
        ]

    def clean(self):
        if self.product.requires_lot and not self.lot_number:
            raise ValidationError("Este producto requiere número de lote.")

        if self.product.requires_expiration_date and not self.expiration_date:
            raise ValidationError("Este producto requiere fecha de vencimiento.")

    def __str__(self):
        lot = self.lot_number or "Sin lote"
        return f"{self.product} - {lot} - {self.quantity}"


class InventoryMovement(BaseModel):
    TYPE_PURCHASE_IN = "INGRESO_COMPRA"
    TYPE_CONSUMPTION_OUT = "EGRESO_CONSUMO"
    TYPE_ADJUSTMENT_IN = "AJUSTE_POSITIVO"
    TYPE_ADJUSTMENT_OUT = "AJUSTE_NEGATIVO"
    TYPE_TRANSFER = "TRASPASO"
    TYPE_BRANCH_LOAN = "PRESTAMO_SUCURSAL"
    TYPE_BRANCH_LOAN_RETURN = "DEVOLUCION_PRESTAMO"
    TYPE_LOSS = "MERMA"
    TYPE_EXPIRATION = "VENCIMIENTO"

    MOVEMENT_TYPE_CHOICES = [
        (TYPE_PURCHASE_IN, "Ingreso por compra"),
        (TYPE_CONSUMPTION_OUT, "Egreso por consumo"),
        (TYPE_ADJUSTMENT_IN, "Ajuste positivo"),
        (TYPE_ADJUSTMENT_OUT, "Ajuste negativo"),
        (TYPE_TRANSFER, "Traspaso"),
        (TYPE_BRANCH_LOAN, "Préstamo entre sucursales"),
        (TYPE_BRANCH_LOAN_RETURN, "Devolución de préstamo"),
        (TYPE_LOSS, "Merma"),
        (TYPE_EXPIRATION, "Vencimiento"),
    ]

    movement_type = models.CharField(
        max_length=50,
        choices=MOVEMENT_TYPE_CHOICES,
    )

    warehouse_origin = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        related_name="outgoing_movements",
        blank=True,
        null=True,
    )
    warehouse_destination = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        related_name="incoming_movements",
        blank=True,
        null=True,
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory_movements",
    )
    lot = models.ForeignKey(
        InventoryLot,
        on_delete=models.SET_NULL,
        related_name="movements",
        blank=True,
        null=True,
    )

    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.TextField(blank=True, null=True)

    reference_type = models.CharField(max_length=80, blank=True, null=True)
    reference_uuid = models.UUIDField(blank=True, null=True)

    created_by_uuid = models.UUIDField(blank=True, null=True)
    approved_by_uuid = models.UUIDField(blank=True, null=True)

    class Meta:
        db_table = "inventory_movements"
        verbose_name = "Inventory Movement"
        verbose_name_plural = "Inventory Movements"
        indexes = [
            models.Index(fields=["product"], name="idx_inv_mov_product"),
            models.Index(fields=["created_at"], name="idx_inv_mov_created_at"),
            models.Index(fields=["reference_type", "reference_uuid"], name="idx_inv_mov_reference"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name="chk_movement_quantity_positive",
            )
        ]

    def clean(self):
        outgoing_types = [
            self.TYPE_CONSUMPTION_OUT,
            self.TYPE_ADJUSTMENT_OUT,
            self.TYPE_TRANSFER,
            self.TYPE_BRANCH_LOAN,
            self.TYPE_LOSS,
            self.TYPE_EXPIRATION,
        ]

        incoming_types = [
            self.TYPE_PURCHASE_IN,
            self.TYPE_ADJUSTMENT_IN,
            self.TYPE_TRANSFER,
            self.TYPE_BRANCH_LOAN_RETURN,
        ]

        if self.movement_type in outgoing_types and not self.warehouse_origin:
            raise ValidationError("Este tipo de movimiento requiere bodega de origen.")

        if self.movement_type in incoming_types and not self.warehouse_destination:
            raise ValidationError("Este tipo de movimiento requiere bodega de destino.")

        if self.movement_type in [self.TYPE_TRANSFER, self.TYPE_BRANCH_LOAN]:
            if self.warehouse_origin == self.warehouse_destination:
                raise ValidationError("La bodega de origen y destino no pueden ser iguales.")

    def __str__(self):
        return f"{self.movement_type} - {self.product} - {self.quantity}"
