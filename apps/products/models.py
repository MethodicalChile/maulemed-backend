from django.db import models

from apps.common.models import BaseModel
from apps.organizations.models import Branch, CostCenter


class ProductCategory(BaseModel):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "product_categories"

    def __str__(self):
        return self.name


class UnitOfMeasure(BaseModel):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=80)

    class Meta:
        db_table = "units_of_measure"

    def __str__(self):
        return self.code


class Product(BaseModel):
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="products",
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="products",
    )

    name = models.CharField(max_length=180)
    description = models.TextField(blank=True, null=True)
    sku = models.CharField(max_length=100, blank=True, null=True)
    barcode = models.CharField(max_length=100, blank=True, null=True)
    internal_code = models.CharField(max_length=100, unique=True, blank=True, null=True)
    image_path = models.CharField(max_length=500, blank=True, default="")

    requires_lot = models.BooleanField(default=False)
    requires_expiration_date = models.BooleanField(default=False)
    requires_sanitary_resolution = models.BooleanField(default=False)
    is_medication = models.BooleanField(default=False)
    is_controlled = models.BooleanField(default=False)
    quality_rating = models.DecimalField(max_digits=2, decimal_places=1, default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "products"

    def __str__(self):
        return self.name


class BranchProduct(BaseModel):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="branch_products",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="branch_products",
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.SET_NULL,
        related_name="branch_products",
        blank=True,
        null=True,
    )

    min_stock = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    max_stock = models.DecimalField(max_digits=14, decimal_places=3, blank=True, null=True)
    critical_stock = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    usual_monthly_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "branch_products"
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "product"],
                name="uq_branch_product",
            )
        ]

    def __str__(self):
        return f"{self.branch} - {self.product}"
