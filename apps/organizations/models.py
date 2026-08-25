from django.db import models
from apps.common.models import BaseModel


class Organization(BaseModel):
    name = models.CharField(max_length=150)
    rut = models.CharField(max_length=20, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "organizations"

    def __str__(self):
        return self.name


class LegalEntity(BaseModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="legal_entities",
    )
    name = models.CharField(max_length=180)
    rut = models.CharField(max_length=20, unique=True)
    business_activity = models.CharField(max_length=255, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "legal_entities"

    def __str__(self):
        return f"{self.name} - {self.rut}"


class LegalEntityAlias(BaseModel):
    """
    Nombres alternativos con que una razón social aparece en las fuentes.

    El maestro que hoy no existe. El reporte de prestaciones del sistema
    clínico abre por código de prestador —IRAMA, IRAL, SODIAGMA— y el informe
    de depósitos abre por RUT; nada relaciona ambos. Sin esta tabla, ningún
    dato de ingreso se puede atribuir a una sociedad.

    Sirve además para la normalización que el informe pide: la misma entidad
    escrita de dos formas deja de contarse dos veces.
    """

    TYPE_PROVIDER_CODE = "CODIGO_PRESTADOR"
    TYPE_NAME = "NOMBRE"

    ALIAS_TYPE_CHOICES = [
        (TYPE_PROVIDER_CODE, "Código de prestador"),
        (TYPE_NAME, "Nombre alternativo"),
    ]

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="aliases",
    )

    alias_type = models.CharField(
        max_length=40,
        choices=ALIAS_TYPE_CHOICES,
        default=TYPE_PROVIDER_CODE,
    )

    # Se guarda normalizado (mayúsculas, sin espacios sobrantes) para que la
    # resolución no dependa de cómo venga escrito en cada exportación.
    value = models.CharField(max_length=180, unique=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "legal_entity_aliases"
        verbose_name = "Legal Entity Alias"
        verbose_name_plural = "Legal Entity Aliases"
        indexes = [
            models.Index(fields=["value"], name="idx_le_alias_value"),
        ]

    @staticmethod
    def normalize(value):
        if value is None:
            return ""
        return " ".join(str(value).split()).upper()

    def save(self, *args, **kwargs):
        self.value = self.normalize(self.value)
        return super().save(*args, **kwargs)

    @classmethod
    def resolve(cls, raw_value):
        """Devuelve la razón social para un valor crudo, o None."""
        normalized = cls.normalize(raw_value)
        if not normalized:
            return None

        alias = (
            cls.objects.filter(value=normalized, is_active=True)
            .select_related("legal_entity")
            .first()
        )
        return alias.legal_entity if alias else None

    def __str__(self):
        return f"{self.value} → {self.legal_entity}"


class Branch(BaseModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="branches",
    )
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.SET_NULL,
        related_name="branches",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(max_length=150, blank=True, null=True)
    is_main_branch = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "branches"

    def __str__(self):
        return self.name


class CostCenter(BaseModel):
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="cost_centers",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="cost_centers",
        blank=True,
        null=True,
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cost_centers"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "code"],
                name="uq_cost_center_code_entity",
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"
