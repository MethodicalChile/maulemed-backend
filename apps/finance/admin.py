from django.contrib import admin

from .models import SupplierInvoice, Payment, Budget


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "supplier",
        "invoice_number",
        "legal_entity",
        "branch",
        "status",
        "total_amount",
        "issue_date",
        "due_date",
    )
    search_fields = (
        "uuid",
        "supplier__name",
        "supplier__rut",
        "invoice_number",
        "legal_entity__name",
        "branch__name",
    )
    list_filter = (
        "status",
        "supplier",
        "legal_entity",
        "branch",
        "issue_date",
        "due_date",
    )
    inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "supplier_invoice",
        "legal_entity",
        "payment_method",
        "amount",
        "status",
        "payment_date",
        "created_by",
    )
    search_fields = (
        "uuid",
        "supplier_invoice__invoice_number",
        "transaction_reference",
        "check_number",
    )
    list_filter = (
        "payment_method",
        "status",
        "legal_entity",
        "payment_date",
    )


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "legal_entity",
        "branch",
        "cost_center",
        "category",
        "period_month",
        "period_year",
        "budget_amount",
        "consumed_amount",
        "available_amount",
    )
    search_fields = (
        "uuid",
        "legal_entity__name",
        "branch__name",
        "cost_center__name",
        "category__name",
    )
    list_filter = (
        "legal_entity",
        "branch",
        "cost_center",
        "category",
        "period_year",
        "period_month",
    )
