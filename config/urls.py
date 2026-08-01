from django.contrib import admin
from django.urls import include, path

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from apps.common.health import health, health_db


urlpatterns = [
    path("admin/", admin.site.urls),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.organizations.urls")),
    path("api/", include("apps.products.urls")),
    path("api/", include("apps.suppliers.urls")),
    path("api/", include("apps.inventory.urls")),
    path("api/", include("apps.purchasing.urls")),
    path("api/", include("apps.transfers.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.documents.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.audit.urls")),
    path("api/", include("apps.dashboard.urls")),
    path("api/", include("apps.options.urls")),
    path("api/", include("apps.reports.urls")),
    path("api/", include("apps.evaluations.urls")),

    path("api/health/", health, name="health"),
    path("api/health/db/", health_db, name="health-db"),
]