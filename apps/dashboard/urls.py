from django.urls import path

from .views import (
    dashboard_summary,
    dashboard_inventory,
    dashboard_purchasing,
    dashboard_finance,
)


urlpatterns = [
    path("dashboard/summary/", dashboard_summary, name="dashboard-summary"),
    path("dashboard/inventory/", dashboard_inventory, name="dashboard-inventory"),
    path("dashboard/purchasing/", dashboard_purchasing, name="dashboard-purchasing"),
    path("dashboard/finance/", dashboard_finance, name="dashboard-finance"),
]
