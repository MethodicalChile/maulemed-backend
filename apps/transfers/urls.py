from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import StockTransferViewSet, StockTransferItemViewSet


router = DefaultRouter()
router.register("stock-transfers", StockTransferViewSet, basename="stock-transfers")
router.register("stock-transfer-items", StockTransferItemViewSet, basename="stock-transfer-items")


urlpatterns = [
    path("", include(router.urls)),
]
