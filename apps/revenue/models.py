"""
El lado del ingreso.

MauleMed reconstruye a mano, día por medio, la apertura por razón social que
sus sistemas deshacen: el sistema clínico individualiza por sucursal y
prestación, y la facturación y la contabilidad la disuelven. Estos modelos
guardan esa apertura en el origen del dato.

Dos magnitudes que no hay que confundir:

    RevenueEntry    lo devengado — el valor de la prestación al atender
    CashCollection  lo percibido — lo que efectivamente entró por caja

La diferencia entre ambas es la deuda institucional, y es la que hoy no
aparece en ningún reporte pese a ser la contraparte de la mayor parte de la
recaudación diaria.
"""

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.organizations.models import LegalEntity, Branch


class Financier(BaseModel):
    """
    Quién paga la prestación: FONASA, una isapre, un convenio institucional o
    el propio paciente.
    """

    TYPE_FONASA = "FONASA"
    TYPE_ISAPRE = "ISAPRE"
    TYPE_AGREEMENT = "CONVENIO"
    TYPE_PRIVATE = "PARTICULAR"
    TYPE_OTHER = "OTRO"

    FINANCIER_TYPE_CHOICES = [
        (TYPE_FONASA, "FONASA"),
        (TYPE_ISAPRE, "Isapre"),
        (TYPE_AGREEMENT, "Convenio institucional"),
        (TYPE_PRIVATE, "Particular"),
        (TYPE_OTHER, "Otro"),
    ]

    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=180)

    financier_type = models.CharField(
        max_length=40,
        choices=FINANCIER_TYPE_CHOICES,
        default=TYPE_OTHER,
    )

    # Sólo los institucionales generan cuenta por cobrar: el particular paga en
    # el mesón y ahí se acaba.
    generates_receivable = models.BooleanField(default=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "financiers"
        verbose_name = "Financier"
        verbose_name_plural = "Financiers"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["financier_type"], name="idx_financier_type"),
        ]

    def __str__(self):
        return self.name


class FinancierAlias(BaseModel):
    """
    Los nombres con que un financiador aparece en las exportaciones.

    En una muestra de 37 filas convivían "MUNICIPALIDAD DE LINARES" y
    "MUNICIP. LINARES" como entidades distintas. Con doce meses de datos eso
    produce doble conteo silencioso en cualquier informe agrupado.
    """

    financier = models.ForeignKey(
        Financier,
        on_delete=models.CASCADE,
        related_name="aliases",
    )

    raw_name = models.CharField(max_length=180, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "financier_aliases"
        verbose_name = "Financier Alias"
        verbose_name_plural = "Financier Aliases"
        indexes = [
            models.Index(fields=["raw_name"], name="idx_financier_alias_raw"),
        ]

    @staticmethod
    def normalize(value):
        if value is None:
            return ""
        return " ".join(str(value).split()).upper()

    def save(self, *args, **kwargs):
        self.raw_name = self.normalize(self.raw_name)
        return super().save(*args, **kwargs)

    @classmethod
    def resolve(cls, raw_value):
        normalized = cls.normalize(raw_value)
        if not normalized:
            return None

        alias = (
            cls.objects.filter(raw_name=normalized, is_active=True)
            .select_related("financier")
            .first()
        )
        return alias.financier if alias else None

    def __str__(self):
        return f"{self.raw_name} → {self.financier}"


class RevenueImportBatch(BaseModel):
    """
    Una carga del reporte de prestaciones.

    Guarda lo que no se pudo mapear en vez de descartarlo en silencio: un lote
    parcial y visible es preferible a un dato mal atribuido, porque la
    atribución por sociedad es justo lo que este módulo existe para conservar.
    """

    STATUS_PREVIEW = "PREVISUALIZADO"
    STATUS_IMPORTED = "IMPORTADO"
    STATUS_FAILED = "FALLIDO"

    STATUS_CHOICES = [
        (STATUS_PREVIEW, "Previsualizado"),
        (STATUS_IMPORTED, "Importado"),
        (STATUS_FAILED, "Fallido"),
    ]

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        related_name="revenue_batches",
        blank=True,
        null=True,
    )

    file_name = models.CharField(max_length=255, blank=True, null=True)

    period_from = models.DateField(blank=True, null=True)
    period_to = models.DateField(blank=True, null=True)

    rows_total = models.PositiveIntegerField(default=0)
    rows_imported = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)

    unmapped_providers = models.JSONField(default=list, blank=True)
    unmapped_financiers = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default=STATUS_PREVIEW,
    )

    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="revenue_import_batches",
        blank=True,
        null=True,
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "revenue_import_batches"
        verbose_name = "Revenue Import Batch"
        verbose_name_plural = "Revenue Import Batches"
        ordering = ["-created_at"]

    @property
    def is_complete(self):
        return self.rows_skipped == 0

    def __str__(self):
        return f"{self.file_name or 'Carga'} - {self.rows_imported}/{self.rows_total}"


class RevenueEntry(BaseModel):
    """
    Una prestación realizada, con su valor y su atribución societaria.

    Es lo devengado. No guarda identificación del paciente: para el control
    financiero basta la referencia de la cita, y persistir RUT y nombre metería
    datos personales de salud donde no hacen falta.
    """

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.PROTECT,
        related_name="revenue_entries",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="revenue_entries",
        blank=True,
        null=True,
    )
    financier = models.ForeignKey(
        Financier,
        on_delete=models.PROTECT,
        related_name="revenue_entries",
    )

    service_date = models.DateField()

    # Referencia de la cita en el sistema de origen. No identifica al paciente:
    # sirve para agrupar los procedimientos de una misma atención, porque una
    # cita puede tener varios y contar filas sobreestima pacientes.
    appointment_ref = models.CharField(max_length=80, blank=True, null=True)

    procedure_code = models.CharField(max_length=80, blank=True, null=True)
    procedure_name = models.CharField(max_length=255, blank=True, null=True)
    modality = models.CharField(max_length=80, blank=True, null=True)
    room = models.CharField(max_length=120, blank=True, null=True)
    status = models.CharField(max_length=80, blank=True, null=True)

    gross_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    import_batch = models.ForeignKey(
        RevenueImportBatch,
        on_delete=models.CASCADE,
        related_name="entries",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "revenue_entries"
        verbose_name = "Revenue Entry"
        verbose_name_plural = "Revenue Entries"
        ordering = ["-service_date"]
        indexes = [
            models.Index(
                fields=["legal_entity", "service_date"],
                name="idx_revenue_entity_date",
            ),
            models.Index(
                fields=["financier", "service_date"],
                name="idx_revenue_financier_date",
            ),
            models.Index(fields=["branch"], name="idx_revenue_branch"),
        ]
        constraints = [
            # Reimportar el mismo archivo no puede duplicar el ingreso.
            models.UniqueConstraint(
                fields=["import_batch", "appointment_ref", "procedure_code"],
                name="uq_revenue_entry_source",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.net_amount:
            self.net_amount = (self.gross_amount or 0) - (self.discount_amount or 0)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_date} - {self.legal_entity} - {self.net_amount}"


class CashCollection(BaseModel):
    """
    Lo percibido: la recaudación de una jornada por sociedad.

    Sale del informe de depósitos, que es el único documento que ya viene
    abierto por razón social. Es la contraparte de RevenueEntry: aquella
    registra lo devengado al atender, ésta lo que efectivamente entró.
    """

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.PROTECT,
        related_name="cash_collections",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="cash_collections",
        blank=True,
        null=True,
        help_text="Vacío cuando el informe consolida varias sucursales.",
    )

    collection_date = models.DateField()

    # El copago es la parte que paga el paciente con previsión; su contraparte
    # es la bonificación que queda por cobrar al financiador. En la muestra
    # analizada el copago fue el 61,6 % de la caja del día.
    particular_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    copay_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    withdrawal_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    cash_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    debit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    check_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    source_document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        related_name="cash_collections",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "cash_collections"
        verbose_name = "Cash Collection"
        verbose_name_plural = "Cash Collections"
        ordering = ["-collection_date"]
        indexes = [
            models.Index(
                fields=["legal_entity", "collection_date"],
                name="idx_collection_entity_date",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "branch", "collection_date"],
                name="uq_cash_collection_day",
            ),
        ]

    @property
    def card_amount(self):
        """Débito más crédito: lo que llega con comisión y desfase de abono."""
        return (self.debit_amount or 0) + (self.credit_amount or 0)

    def __str__(self):
        return f"{self.collection_date} - {self.legal_entity} - {self.total_amount}"


class AccountReceivable(BaseModel):
    """
    Deuda de un financiador institucional con una sociedad.

    Es la funcionalidad que hace visible la contraparte institucional del
    copago. Hoy no aparece en ningún reporte pese a ser la contraparte de la
    mayor parte de la recaudación diaria.
    """

    STATUS_OPEN = "PENDIENTE"
    STATUS_PARTIAL = "PARCIAL"
    STATUS_COLLECTED = "COBRADA"
    STATUS_WRITTEN_OFF = "CASTIGADA"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Pendiente"),
        (STATUS_PARTIAL, "Cobro parcial"),
        (STATUS_COLLECTED, "Cobrada"),
        (STATUS_WRITTEN_OFF, "Castigada"),
    ]

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.PROTECT,
        related_name="receivables",
    )
    financier = models.ForeignKey(
        Financier,
        on_delete=models.PROTECT,
        related_name="receivables",
    )

    period_year = models.IntegerField()
    period_month = models.IntegerField()

    document_number = models.CharField(max_length=100, blank=True, null=True)
    issue_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)

    billed_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    collected_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounts_receivable"
        verbose_name = "Account Receivable"
        verbose_name_plural = "Accounts Receivable"
        ordering = ["-period_year", "-period_month"]
        indexes = [
            models.Index(
                fields=["legal_entity", "financier"],
                name="idx_receivable_entity_fin",
            ),
            models.Index(fields=["status"], name="idx_receivable_status"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(period_month__gte=1) & models.Q(period_month__lte=12),
                name="chk_receivable_month",
            ),
            models.UniqueConstraint(
                fields=[
                    "legal_entity",
                    "financier",
                    "period_year",
                    "period_month",
                ],
                name="uq_receivable_period",
            ),
        ]

    @property
    def pending_amount(self):
        return (self.billed_amount or 0) - (self.collected_amount or 0)

    @property
    def aging_days(self):
        """Días desde el vencimiento. None si no hay fecha comprometida."""
        from django.utils import timezone

        if self.due_date is None:
            return None
        return (timezone.localdate() - self.due_date).days

    @property
    def aging_bucket(self):
        """
        Tramo de antigüedad. "Sin vencer" y "Sin fecha" son distintos: la
        segunda es deuda que nadie sabe cuándo debía cobrarse, y esconderla
        dentro de un tramo la haría desaparecer del análisis.
        """
        if self.pending_amount <= 0:
            return "Sin deuda"

        dias = self.aging_days
        if dias is None:
            return "Sin fecha"
        if dias <= 0:
            return "Sin vencer"
        if dias <= 30:
            return "1-30"
        if dias <= 60:
            return "31-60"
        if dias <= 90:
            return "61-90"
        return "90+"

    def recalculate_status(self):
        if self.collected_amount <= 0:
            self.status = self.STATUS_OPEN
        elif self.pending_amount <= 0:
            self.status = self.STATUS_COLLECTED
        else:
            self.status = self.STATUS_PARTIAL
        return self.status

    def __str__(self):
        return f"{self.financier} → {self.legal_entity} ({self.period_month}/{self.period_year})"


class AccountReceivableItem(BaseModel):
    """
    Las prestaciones que cobra una cuenta por cobrar.

    Es lo que permite desagregar la factura cruzada aunque no pueda emitirse
    separada: una factura puede incluir varias sociedades y sucursales, y con
    bono electrónico llega una sola liquidación por todas.
    """

    account_receivable = models.ForeignKey(
        AccountReceivable,
        on_delete=models.CASCADE,
        related_name="items",
    )
    revenue_entry = models.ForeignKey(
        RevenueEntry,
        on_delete=models.CASCADE,
        related_name="receivable_items",
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = "accounts_receivable_items"
        verbose_name = "Account Receivable Item"
        verbose_name_plural = "Account Receivable Items"
        constraints = [
            models.UniqueConstraint(
                fields=["account_receivable", "revenue_entry"],
                name="uq_receivable_item",
            ),
        ]

    def __str__(self):
        return f"{self.account_receivable} - {self.amount}"
