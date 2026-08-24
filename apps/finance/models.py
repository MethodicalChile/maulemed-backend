from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.common.models import BaseModel
from apps.organizations.models import LegalEntity, Branch, CostCenter
from apps.products.models import ProductCategory
from apps.suppliers.models import Supplier
from apps.purchasing.models import PurchaseOrder


class SupplierInvoice(BaseModel):
    STATUS_RECEIVED = "RECIBIDA"
    STATUS_VALIDATED = "VALIDADA"
    STATUS_OBSERVED = "OBSERVADA"
    STATUS_PARTIALLY_PAID = "PARCIALMENTE_PAGADA"
    STATUS_PAID = "PAGADA"
    STATUS_CANCELLED = "ANULADA"

    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Recibida"),
        (STATUS_VALIDATED, "Validada"),
        (STATUS_OBSERVED, "Observada"),
        (STATUS_PARTIALLY_PAID, "Parcialmente pagada"),
        (STATUS_PAID, "Pagada"),
        (STATUS_CANCELLED, "Anulada"),
    ]

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        related_name="invoices",
        blank=True,
        null=True,
    )
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.SET_NULL,
        related_name="supplier_invoices",
        blank=True,
        null=True,
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="supplier_invoices",
        blank=True,
        null=True,
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        related_name="supplier_invoices",
        blank=True,
        null=True,
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        related_name="supplier_invoices",
        blank=True,
        null=True,
    )

    invoice_number = models.CharField(max_length=100)
    issue_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)

    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "supplier_invoices"
        verbose_name = "Supplier Invoice"
        verbose_name_plural = "Supplier Invoices"
        indexes = [
            models.Index(fields=["supplier"], name="idx_invoice_supplier"),
            models.Index(fields=["legal_entity"], name="idx_invoice_legal_entity"),
            models.Index(fields=["branch"], name="idx_invoice_branch"),
            models.Index(fields=["status"], name="idx_invoice_status"),
            models.Index(fields=["invoice_number"], name="idx_invoice_number"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "invoice_number"],
                name="uq_supplier_invoice_number",
            ),
            models.CheckConstraint(
                check=models.Q(net_amount__gte=0),
                name="chk_invoice_net_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(tax_amount__gte=0),
                name="chk_invoice_tax_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(total_amount__gte=0),
                name="chk_invoice_total_non_negative",
            ),
        ]

    def clean(self):
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            raise ValidationError("La fecha de vencimiento no puede ser anterior a la fecha de emisión.")

    def save(self, *args, **kwargs):
        # Vencimiento derivado del plazo pactado con el proveedor. Sólo se
        # calcula cuando viene vacío: si alguien escribió una fecha, esa manda
        # — hay facturas que se pactan fuera de la política general.
        if (
            self.due_date is None
            and self.issue_date is not None
            and self.supplier_id is not None
        ):
            dias = getattr(self.supplier, "payment_terms_days", None)
            if dias:
                self.due_date = self.issue_date + timedelta(days=dias)

        return super().save(*args, **kwargs)

    @property
    def days_to_due(self):
        """Días hasta el vencimiento. Negativo si ya venció."""
        if self.due_date is None:
            return None
        return (self.due_date - timezone.localdate()).days

    @property
    def is_overdue(self):
        if self.due_date is None or self.status == self.STATUS_PAID:
            return False
        return self.due_date < timezone.localdate()

    def __str__(self):
        supplier_name = self.supplier.name if self.supplier else "Sin proveedor"
        return f"{supplier_name} - {self.invoice_number}"


class SupplierInvoiceItem(BaseModel):
    """
    Detalle de la factura de proveedor.

    La cabecera ya llevaba razón social, sucursal y centro de costo, pero una
    factura que mezcla ítems de dos centros de costo quedaba atribuida entera a
    uno solo. Eso es justo el filtrado manual que la Jefatura pidió eliminar:
    "que las facturas de compra también se pudiesen ir registrando y ojalá
    filtrando por ítem en forma automática".

    Resuelve la carencia del sistema contable —que no está separado por centro
    de costo— sin tocar la contabilidad.
    """

    supplier_invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="supplier_invoice_items",
        blank=True,
        null=True,
        help_text="Vacío para gastos sin producto de catálogo.",
    )
    description = models.CharField(max_length=255, blank=True, null=True)

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        related_name="supplier_invoice_items",
        blank=True,
        null=True,
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        related_name="supplier_invoice_items",
        blank=True,
        null=True,
    )
    budget_category = models.ForeignKey(
        "finance.BudgetCategory",
        on_delete=models.PROTECT,
        related_name="supplier_invoice_items",
        blank=True,
        null=True,
    )

    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = "supplier_invoice_items"
        verbose_name = "Supplier Invoice Item"
        verbose_name_plural = "Supplier Invoice Items"
        indexes = [
            models.Index(
                fields=["supplier_invoice"], name="idx_invoice_item_invoice"
            ),
            models.Index(
                fields=["cost_center"], name="idx_invoice_item_cost_center"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name="chk_invoice_item_quantity_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        # El total del ítem se deriva y no se pide: dejarlo editable a mano
        # abriría la puerta a que el detalle no sume la factura.
        if not self.net_amount:
            self.net_amount = (self.quantity or 0) * (self.unit_price or 0)

        self.total_amount = (self.net_amount or 0) + (self.tax_amount or 0)

        # Heredar la categoría del producto cuando no se indicó otra.
        if self.category_id is None and self.product_id is not None:
            self.category_id = self.product.category_id

        return super().save(*args, **kwargs)

    def __str__(self):
        etiqueta = self.description or (self.product.name if self.product else "Ítem")
        return f"{self.supplier_invoice.invoice_number} - {etiqueta}"


class Payment(BaseModel):
    METHOD_TRANSFER = "TRANSFERENCIA"
    METHOD_CHECK = "CHEQUE"
    METHOD_CASH = "EFECTIVO"
    METHOD_CARD = "TARJETA"
    METHOD_OTHER = "OTRO"

    METHOD_CHOICES = [
        (METHOD_TRANSFER, "Transferencia"),
        (METHOD_CHECK, "Cheque"),
        (METHOD_CASH, "Efectivo"),
        (METHOD_CARD, "Tarjeta"),
        (METHOD_OTHER, "Otro"),
    ]

    STATUS_PENDING = "PENDIENTE"
    STATUS_PAID = "PAGADO"
    STATUS_CANCELLED = "ANULADO"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_PAID, "Pagado"),
        (STATUS_CANCELLED, "Anulado"),
    ]

    supplier_invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.SET_NULL,
        related_name="payments",
        blank=True,
        null=True,
    )
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.SET_NULL,
        related_name="payments",
        blank=True,
        null=True,
    )

    payment_method = models.CharField(
        max_length=50,
        choices=METHOD_CHOICES,
        default=METHOD_TRANSFER,
    )
    payment_date = models.DateField(blank=True, null=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    check_number = models.CharField(max_length=100, blank=True, null=True)
    bank_account = models.CharField(max_length=100, blank=True, null=True)
    transaction_reference = models.CharField(max_length=150, blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_payments",
        blank=True,
        null=True,
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "payments"
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        indexes = [
            models.Index(fields=["supplier_invoice"], name="idx_payment_invoice"),
            models.Index(fields=["legal_entity"], name="idx_payment_legal_entity"),
            models.Index(fields=["status"], name="idx_payment_status"),
            models.Index(fields=["payment_date"], name="idx_payment_date"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="chk_payment_amount_positive",
            )
        ]

    def clean(self):
        if self.payment_method == self.METHOD_CHECK and not self.check_number:
            raise ValidationError("El pago por cheque requiere número de cheque.")

    def __str__(self):
        return f"{self.payment_method} - {self.amount}"


class BudgetCategory(BaseModel):
    """
    Categoría del presupuesto de caja.

    No es la categoría de producto: son las líneas de la planilla de flujo con
    las que la Jefatura de Administración y Finanzas arma el presupuesto anual,
    agrupadas en los cuatro bloques del estado de flujo de efectivo. Una compra
    de insumos se imputa a "Insumos clínicos" aquí y, si hace falta el detalle,
    a una ProductCategory dentro de esa línea.

    Los cinco bloques y sus 34 categorías son los de la planilla, en su mismo
    orden, para que el presupuesto cargado aquí sea reconocible por quien hoy lo
    llena a mano.
    """

    BLOCK_OPERATING_REVENUE = "OPERACION_INGRESO"
    BLOCK_OPERATING_EXPENSE = "OPERACION_EGRESO"
    BLOCK_INVESTMENT_EXPENSE = "INVERSION_EGRESO"
    BLOCK_FINANCING_REVENUE = "FINANCIAMIENTO_INGRESO"
    BLOCK_FINANCING_EXPENSE = "FINANCIAMIENTO_EGRESO"

    BLOCK_CHOICES = [
        (BLOCK_OPERATING_REVENUE, "Operación - Ingreso"),
        (BLOCK_OPERATING_EXPENSE, "Operación - Egreso"),
        (BLOCK_INVESTMENT_EXPENSE, "Inversión - Egreso"),
        (BLOCK_FINANCING_REVENUE, "Financiamiento - Ingreso"),
        (BLOCK_FINANCING_EXPENSE, "Financiamiento - Egreso"),
    ]

    SIGN_INFLOW = 1
    SIGN_OUTFLOW = -1

    SIGN_CHOICES = [
        (SIGN_INFLOW, "Entrada de caja"),
        (SIGN_OUTFLOW, "Salida de caja"),
    ]

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=180)

    block = models.CharField(
        max_length=40,
        choices=BLOCK_CHOICES,
    )
    sign = models.SmallIntegerField(
        choices=SIGN_CHOICES,
        default=SIGN_OUTFLOW,
    )

    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "budget_categories"
        verbose_name = "Budget Category"
        verbose_name_plural = "Budget Categories"
        ordering = ["display_order", "code"]
        indexes = [
            models.Index(fields=["block"], name="idx_budget_category_block"),
        ]

    @property
    def is_inflow(self):
        return self.sign == self.SIGN_INFLOW

    def __str__(self):
        return f"{self.code} - {self.name}"


class Budget(BaseModel):
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="budgets",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="budgets",
        blank=True,
        null=True,
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.CASCADE,
        related_name="budgets",
        blank=True,
        null=True,
    )
    budget_category = models.ForeignKey(
        BudgetCategory,
        on_delete=models.PROTECT,
        related_name="budgets",
        blank=True,
        null=True,
        help_text="Línea del presupuesto de caja a la que pertenece este monto.",
    )

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        related_name="budgets",
        blank=True,
        null=True,
        help_text="Desglose opcional por categoría de producto dentro de la línea.",
    )

    period_year = models.IntegerField()
    period_month = models.IntegerField()

    budget_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Comprometido: aprobado en una orden de compra pero todavía sin factura.
    # Consumido: ya facturado. Separarlos permite que el saldo disponible
    # descuente la compra desde que se autoriza y no recién cuando llega el
    # documento, que es cuando hoy se entera el presupuesto.
    committed_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    consumed_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "budgets"
        verbose_name = "Budget"
        verbose_name_plural = "Budgets"
        indexes = [
            models.Index(fields=["legal_entity"], name="idx_budget_legal_entity"),
            models.Index(fields=["branch"], name="idx_budget_branch"),
            models.Index(fields=["period_year", "period_month"], name="idx_budget_period"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(period_month__gte=1) & models.Q(period_month__lte=12),
                name="chk_budget_month",
            ),
            models.CheckConstraint(
                check=models.Q(budget_amount__gte=0),
                name="chk_budget_amount_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(consumed_amount__gte=0),
                name="chk_budget_consumed_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(committed_amount__gte=0),
                name="chk_budget_committed_non_negative",
            ),
            models.UniqueConstraint(
                fields=[
                    "legal_entity",
                    "branch",
                    "cost_center",
                    "budget_category",
                    "category",
                    "period_year",
                    "period_month",
                ],
                name="uq_budget_scope",
            ),
        ]

    @property
    def used_amount(self):
        return self.committed_amount + self.consumed_amount

    @property
    def available_amount(self):
        return self.budget_amount - self.used_amount

    @property
    def is_overrun(self):
        return self.available_amount < 0

    @property
    def deviation_amount(self):
        """Positivo cuando se gastó de más. Es lo que reporta la desviación."""
        return self.used_amount - self.budget_amount

    def clean(self):
        # El sobregiro NO es un error de validación: tiene que poder registrarse
        # y verse. Bloquearlo aquí impediría aprobar una compra legítima cuando
        # el presupuesto está recién cargado o mal imputado, y dejaría el gasto
        # real fuera del sistema, que es peor que verlo desviado.
        return None

    def __str__(self):
        return f"{self.legal_entity} - {self.period_month}/{self.period_year}"
