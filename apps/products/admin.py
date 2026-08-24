from django.contrib import admin
from .models import ProductCategory, UnitOfMeasure, Product, BranchProduct


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    search_fields = ("name",)
    list_filter = ("is_active",)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "internal_code",
        "category",
        "unit",
        "requires_lot",
        "requires_expiration_date",
        "is_medication",
        "is_active",
    )
    search_fields = ("name", "sku", "barcode", "internal_code")
    list_filter = (
        "category",
        "unit",
        "requires_lot",
        "requires_expiration_date",
        "is_medication",
        "is_active",
    )


@admin.register(BranchProduct)
class BranchProductAdmin(admin.ModelAdmin):
    list_display = (
        "branch",
        "product",
        "cost_center",
        "min_stock",
        "critical_stock",
        "usual_monthly_quantity",
    )
    search_fields = ("branch__name", "product__name")
    list_filter = ("branch", "cost_center")
