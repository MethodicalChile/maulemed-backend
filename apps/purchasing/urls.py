from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SupplyRequestViewSet,
    SupplyRequestItemViewSet,
    PurchaseOrderViewSet,
    PurchaseOrderItemViewSet,
    PurchaseReceiptViewSet,
    PurchaseReceiptItemViewSet,
    SupplierClaimViewSet,
    ApprovalRuleViewSet,
)


router = DefaultRouter()
router.register("supply-requests", SupplyRequestViewSet, basename="supply-requests")
router.register("supply-request-items", SupplyRequestItemViewSet, basename="supply-request-items")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-orders")
router.register("purchase-order-items", PurchaseOrderItemViewSet, basename="purchase-order-items")
router.register("purchase-receipts", PurchaseReceiptViewSet, basename="purchase-receipts")
router.register("purchase-receipt-items", PurchaseReceiptItemViewSet, basename="purchase-receipt-items")
router.register("supplier-claims", SupplierClaimViewSet, basename="supplier-claims")
router.register("approval-rules", ApprovalRuleViewSet, basename="approval-rules")


urlpatterns = [
    path("", include(router.urls)),
]
