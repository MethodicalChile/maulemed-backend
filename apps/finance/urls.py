from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SupplierInvoiceViewSet,
    PaymentViewSet,
    BudgetViewSet,
    BudgetCategoryViewSet,
    SupplierInvoiceItemViewSet,
)


router = DefaultRouter()
router.register("supplier-invoices", SupplierInvoiceViewSet, basename="supplier-invoices")
router.register(
    "supplier-invoice-items",
    SupplierInvoiceItemViewSet,
    basename="supplier-invoice-items",
)
router.register("payments", PaymentViewSet, basename="payments")
router.register("budgets", BudgetViewSet, basename="budgets")
router.register(
    "budget-categories", BudgetCategoryViewSet, basename="budget-categories"
)


urlpatterns = [
    path("", include(router.urls)),
]
