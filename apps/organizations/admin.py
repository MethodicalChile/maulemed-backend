from django.contrib import admin
from .models import Organization, LegalEntity, Branch, CostCenter


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "rut", "is_active", "created_at")
    search_fields = ("name", "rut")
    list_filter = ("is_active",)


@admin.register(LegalEntity)
class LegalEntityAdmin(admin.ModelAdmin):
    list_display = ("name", "rut", "organization", "is_active")
    search_fields = ("name", "rut")
    list_filter = ("organization", "is_active")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "legal_entity", "is_main_branch", "is_active")
    search_fields = ("name", "code", "city")
    list_filter = ("organization", "legal_entity", "is_active")


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "legal_entity", "branch", "is_active")
    search_fields = ("code", "name")
    list_filter = ("legal_entity", "branch", "is_active")
