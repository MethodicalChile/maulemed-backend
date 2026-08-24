from django.db.models import Count, Sum
from rest_framework.decorators import action

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageFinance
from apps.common.responses import api_response
from apps.common.scopes import apply_legal_entity_scope

from .models import (
    Financier,
    FinancierAlias,
    RevenueEntry,
    RevenueImportBatch,
)
from .serializers import (
    FinancierSerializer,
    FinancierAliasSerializer,
    RevenueEntrySerializer,
    RevenueImportBatchSerializer,
)


class FinancierViewSet(BaseModelViewSet):
    queryset = Financier.objects.all()
    serializer_class = FinancierSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = ["financier_type", "generates_receivable", "is_active"]
    search_fields = ["code", "name"]
    ordering_fields = ["name", "code", "financier_type"]
    ordering = ["name"]


class FinancierAliasViewSet(BaseModelViewSet):
    queryset = FinancierAlias.objects.select_related("financier").all()
    serializer_class = FinancierAliasSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = ["financier", "is_active"]
    search_fields = ["raw_name", "financier__name"]
    ordering_fields = ["raw_name", "created_at"]
    ordering = ["raw_name"]


class RevenueEntryViewSet(BaseModelViewSet):
    """
    Libro de ingresos: una fila por prestación, con su razón social.

    Sustituye la descarga de un reporte y su filtrado manual posterior en una
    planilla, que es la actividad que hoy consume el tiempo de la Jefatura.
    """

    queryset = RevenueEntry.objects.select_related(
        "legal_entity",
        "branch",
        "financier",
    ).all()

    serializer_class = RevenueEntrySerializer
    permission_classes = [CanManageFinance]

    filterset_fields = [
        "legal_entity",
        "branch",
        "financier",
        "financier__financier_type",
        "service_date",
        "import_batch",
    ]
    search_fields = ["procedure_name", "procedure_code", "appointment_ref"]
    ordering_fields = ["service_date", "net_amount", "created_at"]
    ordering = ["-service_date"]

    def get_queryset(self):
        return apply_legal_entity_scope(
            super().get_queryset(),
            self.request.user,
            legal_entity_field="legal_entity",
        )

    @action(detail=False, methods=["get"], url_path="by-legal-entity")
    def by_legal_entity(self, request):
        """Ingreso devengado por sociedad — la apertura que hoy se rehace a mano."""

        rows = (
            self.filter_queryset(self.get_queryset())
            .values("legal_entity__uuid", "legal_entity__name", "legal_entity__rut")
            .annotate(
                entries=Count("id"),
                appointments=Count("appointment_ref", distinct=True),
                gross_amount=Sum("gross_amount"),
                discount_amount=Sum("discount_amount"),
                net_amount=Sum("net_amount"),
            )
            .order_by("-net_amount")
        )

        return api_response(
            data=list(rows),
            message="Ingreso por razón social obtenido correctamente.",
        )

    @action(detail=False, methods=["get"], url_path="by-financier")
    def by_financier(self, request):
        rows = (
            self.filter_queryset(self.get_queryset())
            .values(
                "financier__uuid",
                "financier__name",
                "financier__financier_type",
            )
            .annotate(
                entries=Count("id"),
                net_amount=Sum("net_amount"),
            )
            .order_by("-net_amount")
        )

        return api_response(
            data=list(rows),
            message="Ingreso por financiador obtenido correctamente.",
        )


class RevenueImportBatchViewSet(BaseModelViewSet):
    queryset = RevenueImportBatch.objects.select_related(
        "document", "imported_by"
    ).all()

    serializer_class = RevenueImportBatchSerializer
    permission_classes = [CanManageFinance]

    filterset_fields = ["status", "imported_by"]
    search_fields = ["file_name", "notes"]
    ordering_fields = ["created_at", "rows_imported"]
    ordering = ["-created_at"]

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """
        Qué entraría si se confirma, y qué alias faltan. No escribe nada.

        Es deliberado que el usuario vea los prestadores y financiadores sin
        mapear antes de cargar: una vez importado con la atribución equivocada,
        el error es invisible.
        """
        from .services.import_reporte import analyze_records, parse_uploaded_reporte

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="Debes enviar un archivo en el campo 'file'.",
            )

        records, file_name = parse_uploaded_reporte(uploaded_file)
        analysis = analyze_records(records)

        return api_response(
            data={"file_name": file_name, **analysis},
            message="Previsualización generada correctamente.",
        )

    @action(detail=False, methods=["post"], url_path="import")
    def import_file(self, request):
        from .services.import_reporte import import_records, parse_uploaded_reporte

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="Debes enviar un archivo en el campo 'file'.",
            )

        records, file_name = parse_uploaded_reporte(uploaded_file)

        batch = import_records(
            records,
            file_name=file_name,
            user=request.user,
        )

        mensaje = f"Se importaron {batch.rows_imported} de {batch.rows_total} filas."
        if batch.rows_skipped:
            mensaje += (
                f" {batch.rows_skipped} quedaron fuera por falta de alias: "
                "créalos y vuelve a cargar el archivo."
            )

        return api_response(
            data=self.get_serializer(batch).data,
            message=mensaje,
        )
