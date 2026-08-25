from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    FinancierViewSet,
    FinancierAliasViewSet,
    RevenueEntryViewSet,
    RevenueImportBatchViewSet,
    CashCollectionViewSet,
    AccountReceivableViewSet,
)


router = DefaultRouter()
router.register("financiers", FinancierViewSet, basename="financiers")
router.register("financier-aliases", FinancierAliasViewSet, basename="financier-aliases")
router.register("revenue-entries", RevenueEntryViewSet, basename="revenue-entries")
router.register("revenue-imports", RevenueImportBatchViewSet, basename="revenue-imports")
router.register("cash-collections", CashCollectionViewSet, basename="cash-collections")
router.register("receivables", AccountReceivableViewSet, basename="receivables")


urlpatterns = [
    path("", include(router.urls)),
]
