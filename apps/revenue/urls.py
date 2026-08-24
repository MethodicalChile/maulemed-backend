from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    FinancierViewSet,
    FinancierAliasViewSet,
    RevenueEntryViewSet,
    RevenueImportBatchViewSet,
)


router = DefaultRouter()
router.register("financiers", FinancierViewSet, basename="financiers")
router.register("financier-aliases", FinancierAliasViewSet, basename="financier-aliases")
router.register("revenue-entries", RevenueEntryViewSet, basename="revenue-entries")
router.register("revenue-imports", RevenueImportBatchViewSet, basename="revenue-imports")


urlpatterns = [
    path("", include(router.urls)),
]
