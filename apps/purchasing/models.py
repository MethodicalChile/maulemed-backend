from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from apps.common.models import BaseModel
from apps.organizations.models import Branch, LegalEntity, CostCenter
from apps.products.models import Product
from apps.suppliers.models import Supplier
from apps.inventory.models import Warehouse

from decimal import Decimal


class ApprovalRule(BaseModel):
    """
    Umbral de aprobación por monto.

    El informe documenta que la gerencia aprueba las compras de alto valor,
    pero la regla no está escrita en ninguna parte: opera porque dos personas
    la recuerdan. La Propuesta 1 del capítulo financiero pide precisamente
    "umbrales de aprobación por monto y tipo de compra".

    Los campos opcionales se leen como comodines: sin razón social, la regla
    aplica a todas; sin tipo de compra, a todos. Así se puede partir con una
    sola regla global y refinar después, en vez de tener que declarar la matriz
    completa antes de que el control sirva de algo.
    """

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="approval_rules",
        blank=True,
        null=True,
        help_text="Vacío: aplica a todas las razones sociales.",
    )

    purchase_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Vacío: aplica a todos los tipos de compra.",
    )

    amount_from = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_to = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Vacío: sin tope superior.",
    )

    required_role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        related_name="approval_rules",
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "approval_rules"
        verbose_name = "Approval Rule"
        verbose_name_plural = "Approval Rules"
        ordering = ["amount_from"]
        indexes = [
            models.Index(fields=["legal_entity"], name="idx_approval_rule_entity"),
            models.Index(fields=["is_active"], name="idx_approval_rule_active"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount_from__gte=0),
                name="chk_approval_rule_from_non_negative",
            ),
        ]

    def clean(self):
        if self.amount_to is not None and self.amount_to <= self.amount_from:
            raise ValidationError(
                "El monto superior debe ser mayor al inferior."
            )

    def matches(self, *, amount, purchase_type=None, legal_entity=None):
        """Si esta regla gobierna una compra concreta."""

        if not self.is_active:
            return False

        if self.legal_entity_id and legal_entity is not None:
            if self.legal_entity_id != legal_entity.id:
                return False

        if self.purchase_type and self.purchase_type != purchase_type:
            return False

        if amount < self.amount_from:
            return False

        if self.amount_to is not None and amount > self.amount_to:
            return False

        return True

    def __str__(self):
        tope = self.amount_to if self.amount_to is not None else "∞"
        return f"{self.amount_from} - {tope} → {self.required_role}"


class SupplyRequest(BaseModel):
    STATUS_DRAFT = "BORRADOR"
    STATUS_SUBMITTED = "ENVIADA"
    STATUS_IN_REVIEW = "EN_REVISION"
    STATUS_OBSERVED = "OBSERVADA"
    STATUS_APPROVED = "APROBADA"
    STATUS_REJECTED = "RECHAZADA"
    STATUS_PARTIALLY_APPROVED = "PARCIALMENTE_APROBADA"
    STATUS_CONVERTED_TO_PURCHASE = "CONVERTIDA_EN_COMPRA"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Borrador"),
        (STATUS_SUBMITTED, "Enviada"),
        (STATUS_IN_REVIEW, "En revisión"),
        (STATUS_OBSERVED, "Observada"),
        (STATUS_APPROVED, "Aprobada"),
        (STATUS_REJECTED, "Rechazada"),
        (STATUS_PARTIALLY_APPROVED, "Parcialmente aprobada"),
        (STATUS_CONVERTED_TO_PURCHASE, "Convertida en compra"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="supply_requests",
    )
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.SET_NULL,
        related_name="supply_requests",
        blank=True,
        null=True,
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        related_name="supply_requests",
        blank=True,
        null=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_supply_requests",
        blank=True,
        null=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_supply_requests",
        blank=True,
        null=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_supply_requests",
        blank=True,
        null=True,
    )

    period_year = models.IntegerField()
    period_month = models.IntegerField()

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    comments = models.TextField(blank=True, null=True)

    submitted_at = models.DateTimeField(blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "supply_requests"
        verbose_name = "Supply Request"
        verbose_name_plural = "Supply Requests"
        indexes = [
            models.Index(fields=["branch", "period_year", "period_month"], name="idx_supply_branch_period"),
            models.Index(fields=["status"], name="idx_supply_status"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(period_month__gte=1) & models.Q(period_month__lte=12),
                name="chk_supply_month",
            )
        ]

    def __str__(self):
        return f"{self.branch} - {self.period_month}/{self.period_year}"


class SupplyRequestItem(BaseModel):
    STATUS_PENDING = "PENDIENTE"
    STATUS_APPROVED = "APROBADO"
    STATUS_REJECTED = "RECHAZADO"
    STATUS_OBSERVED = "OBSERVADO"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_APPROVED, "Aprobado"),
        (STATUS_REJECTED, "Rechazado"),
        (STATUS_OBSERVED, "Observado"),
    ]

    supply_request = models.ForeignKey(
        SupplyRequest,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="supply_request_items",
    )

    requested_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    approved_quantity = models.DecimalField(max_digits=14, decimal_places=3, blank=True, null=True)

    usual_quantity = models.DecimalField(max_digits=14, decimal_places=3, blank=True, null=True)
    current_stock_snapshot = models.DecimalField(max_digits=14, decimal_places=3, blank=True, null=True)

    justification = models.TextField(blank=True, null=True)
    review_comment = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    class Meta:
        db_table = "supply_request_items"
        verbose_name = "Supply Request Item"
        verbose_name_plural = "Supply Request Items"
        constraints = [
            models.CheckConstraint(
                check=models.Q(requested_quantity__gt=0),
                name="chk_supply_item_requested_positive",
            )
        ]

    def clean(self):
        if self.approved_quantity is not None and self.approved_quantity < 0:
            raise ValidationError("La cantidad aprobada no puede ser negativa.")

        if self.approved_quantity is not None and self.approved_quantity > self.requested_quantity:
            raise ValidationError("La cantidad aprobada no puede ser mayor a la cantidad solicitada.")

    def __str__(self):
        return f"{self.supply_request} - {self.product}"


class PurchaseOrder(BaseModel):
    STATUS_DRAFT = "BORRADOR"
    STATUS_PENDING_APPROVAL = "EN_APROBACION"
    STATUS_APPROVED = "APROBADA"
    STATUS_SENT_TO_SUPPLIER = "ENVIADA_PROVEEDOR"
    STATUS_ACCEPTED_BY_SUPPLIER = "ACEPTADA_PROVEEDOR"
    STATUS_REJECTED_BY_SUPPLIER = "RECHAZADA_PROVEEDOR"
    STATUS_PARTIALLY_RECEIVED = "PARCIALMENTE_RECIBIDA"
    STATUS_RECEIVED = "RECIBIDA"
    STATUS_CANCELLED = "CANCELADA"
    STATUS_CLOSED = "CERRADA"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Borrador"),
        (STATUS_PENDING_APPROVAL, "En aprobación"),
        (STATUS_APPROVED, "Aprobada"),
        (STATUS_SENT_TO_SUPPLIER, "Enviada a proveedor"),
        (STATUS_ACCEPTED_BY_SUPPLIER, "Aceptada por proveedor"),
        (STATUS_REJECTED_BY_SUPPLIER, "Rechazada por proveedor"),
        (STATUS_PARTIALLY_RECEIVED, "Parcialmente recibida"),
        (STATUS_RECEIVED, "Recibida"),
        (STATUS_CANCELLED, "Cancelada"),
        (STATUS_CLOSED, "Cerrada"),
    ]

    PURCHASE_TYPE_PURCHASE_ORDER = "ORDEN_COMPRA"
    PURCHASE_TYPE_WEB = "COMPRA_WEB"
    PURCHASE_TYPE_EMAIL = "COMPRA_CORREO"
    PURCHASE_TYPE_MINOR = "COMPRA_MENOR"
    PURCHASE_TYPE_URGENT = "COMPRA_URGENTE"
    PURCHASE_TYPE_MANAGEMENT = "COMPRA_GERENCIA"

    PURCHASE_TYPE_CHOICES = [
        (PURCHASE_TYPE_PURCHASE_ORDER, "Orden de compra"),
        (PURCHASE_TYPE_WEB, "Compra web"),
        (PURCHASE_TYPE_EMAIL, "Compra por correo"),
        (PURCHASE_TYPE_MINOR, "Compra menor"),
        (PURCHASE_TYPE_URGENT, "Compra urgente"),
        (PURCHASE_TYPE_MANAGEMENT, "Compra gerencia"),
    ]

    order_number = models.CharField(max_length=80, unique=True)

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
        blank=True,
        null=True,
    )
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
        blank=True,
        null=True,
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
        blank=True,
        null=True,
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
        blank=True,
        null=True,
    )
    supply_request = models.ForeignKey(
        SupplyRequest,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
        blank=True,
        null=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_purchase_orders",
        blank=True,
        null=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_purchase_orders",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    purchase_type = models.CharField(
        max_length=50,
        choices=PURCHASE_TYPE_CHOICES,
        default=PURCHASE_TYPE_PURCHASE_ORDER,
    )
    payment_type = models.CharField(max_length=50, blank=True, null=True)

    expected_delivery_date = models.DateField(blank=True, null=True)

    subtotal_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Cuánto de esta orden sigue comprometido contra el presupuesto. Se llena al
    # aprobar y se descuenta al facturar, cancelar o cerrar. Sin este dato, una
    # orden facturada y luego cerrada liberaría dos veces el mismo monto, y la
    # segunda liberación se comería el compromiso de otra orden.
    budget_committed_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    notes = models.TextField(blank=True, null=True)

    approved_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "purchase_orders"
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        indexes = [
            models.Index(fields=["supplier"], name="idx_po_supplier"),
            models.Index(fields=["status"], name="idx_po_status"),
            models.Index(fields=["branch"], name="idx_po_branch"),
        ]

    def __str__(self):
        return self.order_number


class PurchaseOrderItem(BaseModel):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="purchase_order_items",
    )

    supplier_product = models.ForeignKey(
        "suppliers.SupplierProduct",
        on_delete=models.PROTECT,
        related_name="purchase_order_items",
        null=True,
        blank=True,
    )

    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
    )

    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    currency = models.CharField(
        max_length=10,
        default="CLP",
    )

    discount_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    tax_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    received_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=0,
    )

    class Meta:
        db_table = "purchase_order_items"
        verbose_name = "Purchase Order Item"
        verbose_name_plural = "Purchase Order Items"

        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name="chk_po_item_quantity_positive",
            ),
            models.CheckConstraint(
                check=models.Q(received_quantity__gte=0),
                name="chk_po_item_received_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(unit_price__gte=0),
                name="chk_po_item_unit_price_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(discount_amount__gte=0),
                name="chk_po_item_discount_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(tax_amount__gte=0),
                name="chk_po_item_tax_non_negative",
            ),
        ]

    @property
    def pending_quantity(self):
        return self.quantity - self.received_quantity

    @property
    def subtotal_amount(self):
        quantity = self.quantity or Decimal("0")
        unit_price = self.unit_price or Decimal("0")
        result = quantity * unit_price
        return result.quantize(Decimal("0.01"))

    def calculate_total_amount(self):
        subtotal = self.subtotal_amount
        discount = self.discount_amount or Decimal("0")
        tax = self.tax_amount or Decimal("0")
        result = subtotal - discount + tax
        # Redondear a 2 decimales para cumplir con el campo DecimalField(decimal_places=2)
        return result.quantize(Decimal("0.01"))

    def clean(self):
        super().clean()

        if self.received_quantity > self.quantity:
            raise ValidationError(
                "La cantidad recibida no puede ser mayor "
                "a la cantidad comprada."
            )

        if (
            self.supplier_product
            and self.supplier_product.product_id != self.product_id
        ):
            raise ValidationError({
                "supplier_product": (
                    "El producto asociado al proveedor no coincide "
                    "con el producto de la línea."
                ),
            })

        if self.discount_amount > self.subtotal_amount:
            raise ValidationError({
                "discount_amount": (
                    "El descuento no puede ser mayor al subtotal."
                ),
            })

    def save(self, *args, **kwargs):
        self.total_amount = self.calculate_total_amount()

        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.purchase_order} - {self.product}"


class PurchaseReceipt(BaseModel):
    STATUS_OK = "RECIBIDO_OK"
    STATUS_PARTIAL = "RECIBIDO_PARCIAL"
    STATUS_WITH_INCIDENT = "CON_INCIDENCIA"
    STATUS_REJECTED = "RECHAZADO"

    STATUS_CHOICES = [
        (STATUS_OK, "Recibido OK"),
        (STATUS_PARTIAL, "Recibido parcial"),
        (STATUS_WITH_INCIDENT, "Con incidencia"),
        (STATUS_REJECTED, "Rechazado"),
    ]

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        related_name="receipts",
        blank=True,
        null=True,
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="purchase_receipts",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        related_name="purchase_receipts",
        blank=True,
        null=True,
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="purchase_receipts",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_OK,
    )
    received_at = models.DateTimeField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "purchase_receipts"
        verbose_name = "Purchase Receipt"
        verbose_name_plural = "Purchase Receipts"
        indexes = [
            models.Index(fields=["purchase_order"], name="idx_receipt_order"),
        ]

    def __str__(self):
        return f"Recepción {self.uuid}"


class PurchaseReceiptItem(BaseModel):
    INCIDENT_MISSING = "FALTANTE"
    INCIDENT_CHANGED_PRODUCT = "PRODUCTO_CAMBIADO"
    INCIDENT_EXPIRED_PRODUCT = "PRODUCTO_VENCIDO"
    INCIDENT_DAMAGED_PRODUCT = "PRODUCTO_DANADO"
    INCIDENT_WRONG_BRANCH = "LLEGO_A_OTRA_SUCURSAL"
    INCIDENT_WRONG_QUANTITY = "CANTIDAD_INCORRECTA"

    INCIDENT_CHOICES = [
        (INCIDENT_MISSING, "Faltante"),
        (INCIDENT_CHANGED_PRODUCT, "Producto cambiado"),
        (INCIDENT_EXPIRED_PRODUCT, "Producto vencido"),
        (INCIDENT_DAMAGED_PRODUCT, "Producto dañado"),
        (INCIDENT_WRONG_BRANCH, "Llegó a otra sucursal"),
        (INCIDENT_WRONG_QUANTITY, "Cantidad incorrecta"),
    ]

    purchase_receipt = models.ForeignKey(
        PurchaseReceipt,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="purchase_receipt_items",
    )

    lot_number = models.CharField(max_length=120, blank=True, null=True)
    expiration_date = models.DateField(blank=True, null=True)

    ordered_quantity = models.DecimalField(max_digits=14, decimal_places=3, blank=True, null=True)
    received_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    accepted_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    rejected_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    incident_type = models.CharField(
        max_length=80,
        choices=INCIDENT_CHOICES,
        blank=True,
        null=True,
    )
    comments = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "purchase_receipt_items"
        verbose_name = "Purchase Receipt Item"
        verbose_name_plural = "Purchase Receipt Items"
        constraints = [
            models.CheckConstraint(
                check=models.Q(received_quantity__gte=0),
                name="chk_receipt_received_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(accepted_quantity__gte=0),
                name="chk_receipt_accepted_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(rejected_quantity__gte=0),
                name="chk_receipt_rejected_non_negative",
            ),
        ]

    def clean(self):
        if self.accepted_quantity + self.rejected_quantity > self.received_quantity:
            raise ValidationError("La cantidad aceptada más rechazada no puede superar la cantidad recibida.")

    def __str__(self):
        return f"{self.purchase_receipt} - {self.product}"


class SupplierClaim(BaseModel):
    CLAIM_RETURN = "DEVOLUCION_PRODUCTO"
    CLAIM_CREDIT_NOTE = "NOTA_CREDITO"
    CLAIM_REPLACEMENT = "REPOSICION"
    CLAIM_PRODUCT_CHANGE = "CAMBIO_PRODUCTO"

    CLAIM_TYPE_CHOICES = [
        (CLAIM_RETURN, "Devolución de producto"),
        (CLAIM_CREDIT_NOTE, "Nota de crédito"),
        (CLAIM_REPLACEMENT, "Reposición"),
        (CLAIM_PRODUCT_CHANGE, "Cambio de producto"),
    ]

    STATUS_OPEN = "ABIERTO"
    STATUS_IN_PROGRESS = "EN_GESTION"
    STATUS_RESOLVED = "RESUELTO"
    STATUS_CANCELLED = "CANCELADO"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Abierto"),
        (STATUS_IN_PROGRESS, "En gestión"),
        (STATUS_RESOLVED, "Resuelto"),
        (STATUS_CANCELLED, "Cancelado"),
    ]

    purchase_receipt = models.ForeignKey(
        PurchaseReceipt,
        on_delete=models.SET_NULL,
        related_name="supplier_claims",
        blank=True,
        null=True,
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        related_name="claims",
        blank=True,
        null=True,
    )

    claim_type = models.CharField(max_length=80, choices=CLAIM_TYPE_CHOICES)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_OPEN)

    description = models.TextField(blank=True, null=True)
    requested_solution = models.TextField(blank=True, null=True)
    resolution = models.TextField(blank=True, null=True)

    credit_note_number = models.CharField(max_length=100, blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="supplier_claims",
        blank=True,
        null=True,
    )

    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "supplier_claims"
        verbose_name = "Supplier Claim"
        verbose_name_plural = "Supplier Claims"

    def __str__(self):
        return f"{self.claim_type} - {self.supplier}"
