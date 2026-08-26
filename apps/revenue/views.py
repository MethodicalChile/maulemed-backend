from django.db.models import Count, Sum
from rest_framework.decorators import action

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import CanManageRevenue
from apps.common.responses import api_response
from apps.common.scopes import apply_legal_entity_scope

from .models import (
    AccountReceivable,
    CashCollection,
    Financier,
    FinancierAlias,
    RevenueEntry,
    RevenueImportBatch,
)
from .serializers import (
    AccountReceivableSerializer,
    CashCollectionSerializer,
    FinancierSerializer,
    FinancierAliasSerializer,
    RevenueEntrySerializer,
    RevenueImportBatchSerializer,
)


class FinancierViewSet(BaseModelViewSet):
    queryset = Financier.objects.all()
    serializer_class = FinancierSerializer
    permission_classes = [CanManageRevenue]

    filterset_fields = ["financier_type", "generates_receivable", "is_active"]
    search_fields = ["code", "name"]
    ordering_fields = ["name", "code", "financier_type"]
    ordering = ["name"]


class FinancierAliasViewSet(BaseModelViewSet):
    queryset = FinancierAlias.objects.select_related("financier").all()
    serializer_class = FinancierAliasSerializer
    permission_classes = [CanManageRevenue]

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
    permission_classes = [CanManageRevenue]

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
    permission_classes = [CanManageRevenue]

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


class CashCollectionViewSet(BaseModelViewSet):
    """Recaudación diaria por sociedad — lo percibido."""

    queryset = CashCollection.objects.select_related(
        "legal_entity", "branch"
    ).all()

    serializer_class = CashCollectionSerializer
    permission_classes = [CanManageRevenue]

    filterset_fields = ["legal_entity", "branch", "collection_date"]
    search_fields = ["legal_entity__name"]
    ordering_fields = ["collection_date", "total_amount"]
    ordering = ["-collection_date"]

    def get_queryset(self):
        return apply_legal_entity_scope(
            super().get_queryset(),
            self.request.user,
            legal_entity_field="legal_entity",
        )

    @action(detail=False, methods=["post"], url_path="import")
    def import_file(self, request):
        from .services.import_depositos import (
            analyze_providers,
            import_providers,
            parse_uploaded_depositos,
        )

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="Debes enviar un archivo en el campo 'file'.",
            )

        providers, fecha, file_name = parse_uploaded_depositos(uploaded_file)

        if fecha is None:
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="No se pudo determinar la fecha del informe.",
            )

        analisis = analyze_providers(providers)
        creadas = import_providers(providers, collection_date=fecha)

        mensaje = f"Se cargaron {len(creadas)} sociedades del {fecha}."
        if analisis["unmapped_providers"]:
            mensaje += (
                f" {len(analisis['unmapped_providers'])} no se pudieron "
                "resolver: revisa el RUT en la ficha o crea el alias."
            )

        return api_response(
            data={
                "file_name": file_name,
                "collection_date": str(fecha),
                "imported": len(creadas),
                **analisis,
            },
            message=mensaje,
        )


class AccountReceivableViewSet(BaseModelViewSet):
    """
    Deuda institucional por financiador.

    Es el puente entre lo devengado y lo percibido, que hoy no existe: la única
    fuente de ingresos registra lo devengado y el flujo se construye sobre lo
    percibido.
    """

    queryset = AccountReceivable.objects.select_related(
        "legal_entity", "financier"
    ).all()

    serializer_class = AccountReceivableSerializer
    permission_classes = [CanManageRevenue]

    filterset_fields = [
        "legal_entity",
        "financier",
        "financier__financier_type",
        "period_year",
        "period_month",
        "status",
    ]
    search_fields = ["financier__name", "document_number", "notes"]
    ordering_fields = ["period_year", "period_month", "billed_amount"]
    ordering = ["-period_year", "-period_month"]

    def get_queryset(self):
        return apply_legal_entity_scope(
            super().get_queryset(),
            self.request.user,
            legal_entity_field="legal_entity",
        )

    @action(detail=False, methods=["get"])
    def aging(self, request):
        """Antigüedad de la deuda por financiador, en tramos de 30 días."""
        from .services.receivables import aging_report

        filas = aging_report(self.filter_queryset(self.get_queryset()))

        return api_response(
            data=filas,
            message="Antigüedad de la cobranza obtenida correctamente.",
        )

    @action(detail=False, methods=["post"], url_path="rebuild")
    def rebuild(self, request):
        """
        Reconstruye las cuentas del período desde el libro de ingresos.

        No toca lo ya cobrado: volver a correrlo tras una carga nueva no borra
        el trabajo de cobranza.
        """
        from .services.receivables import build_receivables_from_revenue

        try:
            period_year = int(request.data.get("period_year"))
            period_month = int(request.data.get("period_month"))
        except (TypeError, ValueError):
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="Indica period_year y period_month.",
            )

        creadas = build_receivables_from_revenue(
            period_year=period_year,
            period_month=period_month,
        )

        return api_response(
            data=self.get_serializer(creadas, many=True).data,
            message=f"Se actualizaron {len(creadas)} cuentas por cobrar.",
        )

    @action(detail=True, methods=["post"], url_path="register-collection")
    def register_collection_action(self, request, uuid=None):
        from decimal import Decimal, InvalidOperation

        from .services.receivables import register_collection

        instance = self.get_object()

        try:
            amount = Decimal(str(request.data.get("amount")))
        except (InvalidOperation, TypeError):
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="Indica un monto válido.",
            )

        if amount <= 0:
            return api_response(
                data=None,
                status_code=400,
                status_text="error",
                message="El monto cobrado debe ser mayor a cero.",
            )

        register_collection(
            receivable=instance,
            amount=amount,
            notes=request.data.get("notes"),
        )

        return api_response(
            data=self.get_serializer(instance).data,
            message="Cobro registrado correctamente.",
        )
