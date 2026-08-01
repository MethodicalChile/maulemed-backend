from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SupplierViewSet,
    SupplierProductViewSet,
    SupplierProductPriceViewSet,
)


router = DefaultRouter()

router.register(
    "suppliers",
    SupplierViewSet,
    basename="suppliers",
)

router.register(
    "supplier-products",
    SupplierProductViewSet,
    basename="supplier-products",
)

router.register(
    "supplier-product-prices",
    SupplierProductPriceViewSet,
    basename="supplier-product-prices",
)


urlpatterns = [
    path("", include(router.urls)),
]