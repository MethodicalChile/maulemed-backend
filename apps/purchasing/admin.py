from django.contrib import admin

from .models import (
    SupplyRequest,
    SupplyRequestItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierClaim,
)


class SupplyRequestItemInline(admin.TabularInline):
    model = SupplyRequestItem
    extra = 0


@admin.register(SupplyRequest)
class SupplyRequestAdmin(admin.ModelAdmin):
    list_display = ("uuid", "branch", "period_month", "period_year", "status", "requested_by", "created_at")
    search_fields = ("uuid", "branch__name", "comments")
    list_filter = ("status", "branch", "period_year", "period_month")
    inlines = [SupplyRequestItemInline]


@admin.register(SupplyRequestItem)
class SupplyRequestItemAdmin(admin.ModelAdmin):
    list_display = ("uuid", "supply_request", "product", "requested_quantity", "approved_quantity", "status")
    search_fields = ("uuid", "product__name", "supply_request__branch__name")
    list_filter = ("status", "product__category")


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("uuid", "order_number", "supplier", "branch", "status", "purchase_type", "total_amount", "created_at")
    search_fields = ("uuid", "order_number", "supplier__name", "branch__name")
    list_filter = ("status", "purchase_type", "supplier", "branch")
    inlines = [PurchaseOrderItemInline]


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
    list_display = ("uuid", "purchase_order", "product", "quantity", "received_quantity", "pending_quantity", "total_amount")
    search_fields = ("uuid", "purchase_order__order_number", "product__name")
    list_filter = ("product__category",)


class PurchaseReceiptItemInline(admin.TabularInline):
    model = PurchaseReceiptItem
    extra = 0


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(admin.ModelAdmin):
    list_display = ("uuid", "purchase_order", "branch", "warehouse", "status", "received_by", "received_at")
    search_fields = ("uuid", "purchase_order__order_number", "branch__name")
    list_filter = ("status", "branch", "warehouse")
    inlines = [PurchaseReceiptItemInline]


@admin.register(PurchaseReceiptItem)
class PurchaseReceiptItemAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "purchase_receipt",
        "product",
        "received_quantity",
        "accepted_quantity",
        "rejected_quantity",
        "incident_type",
    )
    search_fields = ("uuid", "product__name", "lot_number")
    list_filter = ("incident_type", "product__category")


@admin.register(SupplierClaim)
class SupplierClaimAdmin(admin.ModelAdmin):
    list_display = ("uuid", "supplier", "claim_type", "status", "credit_note_number", "created_at", "resolved_at")
    search_fields = ("uuid", "supplier__name", "description", "credit_note_number")
    list_filter = ("claim_type", "status", "supplier")
