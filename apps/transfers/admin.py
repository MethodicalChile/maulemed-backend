from django.contrib import admin

from .models import StockTransfer, StockTransferItem


class StockTransferItemInline(admin.TabularInline):
    model = StockTransferItem
    extra = 0


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "transfer_type",
        "origin_branch",
        "destination_branch",
        "status",
        "requested_by",
        "approved_by",
        "created_at",
    )
    search_fields = (
        "uuid",
        "origin_branch__name",
        "destination_branch__name",
        "dispatch_guide_number",
        "internal_guide_number",
    )
    list_filter = (
        "transfer_type",
        "status",
        "origin_branch",
        "destination_branch",
    )
    inlines = [StockTransferItemInline]


@admin.register(StockTransferItem)
class StockTransferItemAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "stock_transfer",
        "product",
        "requested_quantity",
        "approved_quantity",
        "sent_quantity",
        "received_quantity",
        "returned_quantity",
    )
    search_fields = (
        "uuid",
        "product__name",
        "stock_transfer__origin_branch__name",
        "stock_transfer__destination_branch__name",
    )
    list_filter = (
        "product__category",
        "stock_transfer__transfer_type",
        "stock_transfer__status",
    )
