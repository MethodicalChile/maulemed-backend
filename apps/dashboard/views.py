from datetime import timedelta

from django.db.models import Sum, Count, F
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from apps.common.responses import api_response
from apps.common.permissions import user_has_permission_key
from apps.common.scopes import (
    apply_branch_scope,
    apply_legal_entity_scope,
)

from apps.inventory.models import InventoryStock, InventoryLot
from apps.purchasing.models import (
    SupplyRequest,
    PurchaseOrder,
    PurchaseReceipt,
)
from apps.finance.models import (
    SupplierInvoice,
    Payment,
    Budget,
)
from apps.notifications.models import Notification


# ============================================================================
# PERMISOS
# ============================================================================

def _can_view_inventory(user):
    return user_has_permission_key(
        user,
        "can_view_inventory",
    )


def _can_view_supply_requests(user):
    return user_has_permission_key(
        user,
        "can_view_supply_requests",
    )


def _can_view_purchase_orders(user):
    return user_has_permission_key(
        user,
        "can_view_purchase_orders",
    )


def _can_view_purchasing(user):
    return (
        _can_view_supply_requests(user)
        or _can_view_purchase_orders(user)
    )


def _can_view_finance(user):
    return user_has_permission_key(
        user,
        "can_view_finance",
    )


# ============================================================================
# DASHBOARD GENERAL
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    """
    Dashboard principal.

    Todo usuario autenticado puede acceder al dashboard.

    El contenido que recibe depende de los permisos configurados
    para su rol.
    """

    user = request.user

    # ------------------------------------------------------------------------
    # Permisos del usuario
    # ------------------------------------------------------------------------

    can_inventory = _can_view_inventory(user)
    can_supply_requests = _can_view_supply_requests(user)
    can_purchase_orders = _can_view_purchase_orders(user)
    can_purchasing = (
        can_supply_requests
        or can_purchase_orders
    )
    can_finance = _can_view_finance(user)

    # ------------------------------------------------------------------------
    # Información común a todos los usuarios
    # ------------------------------------------------------------------------

    unread_notifications = Notification.objects.filter(
        user=user,
        is_read=False,
    ).count()

    data = {
        "access": {
            "inventory": can_inventory,
            "purchasing": can_purchasing,
            "supply_requests": can_supply_requests,
            "purchase_orders": can_purchase_orders,
            "finance": can_finance,
        },

        "general": {
            "unread_notifications": unread_notifications,
        },

        "inventory": None,
        "purchasing": None,
        "finance": None,
    }

    # =========================================================================
    # INVENTARIO
    # =========================================================================

    if can_inventory:
        from apps.products.models import BranchProduct

        stocks_qs = (
            InventoryStock.objects
            .select_related(
                "warehouse",
                "warehouse__branch",
                "product",
            )
            .all()
        )

        stocks_qs = apply_branch_scope(
            stocks_qs,
            user,
            branch_field="warehouse__branch",
        )

        # ---------------------------------------------------------------------
        # Calcular stock bajo
        # ---------------------------------------------------------------------

        branch_ids = (
            stocks_qs
            .values_list(
                "warehouse__branch_id",
                flat=True,
            )
            .distinct()
        )

        product_ids = (
            stocks_qs
            .values_list(
                "product_id",
                flat=True,
            )
            .distinct()
        )

        branch_products = {
            (bp.product_id, bp.branch_id): bp
            for bp in BranchProduct.objects.filter(
                branch_id__in=branch_ids,
                product_id__in=product_ids,
                product__is_active=True,
            )
        }

        low_stock_count = 0

        for stock in stocks_qs:
            bp = branch_products.get(
                (
                    stock.product_id,
                    stock.warehouse.branch_id,
                )
            )

            if not bp:
                continue

            threshold = (
                bp.critical_stock
                or bp.min_stock
            )

            if (
                threshold is not None
                and stock.available_quantity <= threshold
            ):
                low_stock_count += 1

        # ---------------------------------------------------------------------
        # Lotes próximos a vencer
        # ---------------------------------------------------------------------

        today = timezone.now().date()
        expiring_limit = today + timedelta(days=30)

        lots_qs = (
            InventoryLot.objects
            .select_related(
                "warehouse",
                "warehouse__branch",
                "product",
            )
            .all()
        )

        lots_qs = apply_branch_scope(
            lots_qs,
            user,
            branch_field="warehouse__branch",
        )

        expiring_soon_count = lots_qs.filter(
            expiration_date__isnull=False,
            expiration_date__gte=today,
            expiration_date__lte=expiring_limit,
        ).count()

        expired_count = lots_qs.filter(
            expiration_date__isnull=False,
            expiration_date__lt=today,
        ).count()

        # ---------------------------------------------------------------------
        # Resumen inventario
        # ---------------------------------------------------------------------

        total_quantity = (
            stocks_qs.aggregate(
                total=Sum("quantity")
            )["total"]
            or 0
        )

        available_quantity = (
            stocks_qs.aggregate(
                total=Sum(F("quantity") - F("reserved_quantity"))
            )["total"]
            or 0
        )

        reserved_quantity = (
            stocks_qs.aggregate(
                total=Sum("reserved_quantity")
            )["total"]
            or 0
        )

        data["inventory"] = {
            "stock_items": stocks_qs.count(),

            "total_quantity": total_quantity,

            "available_quantity": available_quantity,

            "reserved_quantity": reserved_quantity,

            "low_stock_count": low_stock_count,

            "lots_total": lots_qs.count(),

            "expiring_soon_count": expiring_soon_count,

            "expired_count": expired_count,
        }

    # =========================================================================
    # COMPRAS
    # =========================================================================

    if can_purchasing:
        purchasing_data = {}

        # ---------------------------------------------------------------------
        # Solicitudes de compra
        # ---------------------------------------------------------------------

        if can_supply_requests:
            supply_qs = (
                SupplyRequest.objects
                .select_related("branch")
                .all()
            )

            supply_qs = apply_branch_scope(
                supply_qs,
                user,
                branch_field="branch",
            )

            purchasing_data.update({
                "supply_requests_total":
                    supply_qs.count(),

                "supply_requests_pending":
                    supply_qs.exclude(
                        status__in=[
                            "APROBADA",
                            "RECHAZADA",
                            "CERRADA",
                            "CANCELADA",
                        ]
                    ).count(),
            })

        # ---------------------------------------------------------------------
        # Órdenes de compra
        # ---------------------------------------------------------------------

        if can_purchase_orders:
            po_qs = (
                PurchaseOrder.objects
                .select_related(
                    "branch",
                    "supplier",
                )
                .all()
            )

            po_qs = apply_branch_scope(
                po_qs,
                user,
                branch_field="branch",
            )

            receipt_qs = (
                PurchaseReceipt.objects
                .select_related("branch")
                .all()
            )

            receipt_qs = apply_branch_scope(
                receipt_qs,
                user,
                branch_field="branch",
            )

            purchase_orders_total_amount = (
                po_qs.aggregate(
                    total=Sum("total_amount")
                )["total"]
                or 0
            )

            purchasing_data.update({
                "purchase_orders_total":
                    po_qs.count(),

                "purchase_orders_pending":
                    po_qs.exclude(
                        status__in=[
                            "RECIBIDA",
                            "CERRADA",
                            "CANCELADA",
                        ]
                    ).count(),

                "purchase_orders_total_amount":
                    purchase_orders_total_amount,

                "pending_receipts":
                    receipt_qs.exclude(
                        status__in=[
                            "PROCESADA",
                            "COMPLETADA",
                            "CERRADA",
                        ]
                    ).count(),
            })

        data["purchasing"] = purchasing_data

    # =========================================================================
    # FINANZAS
    # =========================================================================

    if can_finance:
        invoices_qs = (
            SupplierInvoice.objects
            .select_related("legal_entity")
            .all()
        )

        invoices_qs = apply_legal_entity_scope(
            invoices_qs,
            user,
            legal_entity_field="legal_entity",
        )

        payments_qs = (
            Payment.objects
            .select_related("legal_entity")
            .all()
        )

        payments_qs = apply_legal_entity_scope(
            payments_qs,
            user,
            legal_entity_field="legal_entity",
        )

        budgets_qs = (
            Budget.objects
            .select_related("legal_entity")
            .all()
        )

        budgets_qs = apply_legal_entity_scope(
            budgets_qs,
            user,
            legal_entity_field="legal_entity",
        )

        total_invoiced_amount = (
            invoices_qs.aggregate(
                total=Sum("total_amount")
            )["total"]
            or 0
        )

        total_paid_amount = (
            payments_qs.aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

        budget_amount_total = (
            budgets_qs.aggregate(
                total=Sum("budget_amount")
            )["total"]
            or 0
        )

        budget_consumed_total = (
            budgets_qs.aggregate(
                total=Sum("consumed_amount")
            )["total"]
            or 0
        )

        budget_available_total = (
            budget_amount_total
            - budget_consumed_total
        )

        data["finance"] = {
            "supplier_invoices_total":
                invoices_qs.count(),

            "supplier_invoices_pending":
                invoices_qs.exclude(
                    status__in=[
                        "PAGADA",
                        "ANULADA",
                        "CANCELADA",
                    ]
                ).count(),

            "total_invoiced_amount":
                total_invoiced_amount,

            "total_paid_amount":
                total_paid_amount,

            "budgets_total":
                budgets_qs.count(),

            "budget_amount_total":
                budget_amount_total,

            "budget_consumed_total":
                budget_consumed_total,

            "budget_available_total":
                budget_available_total,
        }

    return api_response(
        data=data,
        message="Resumen de dashboard obtenido correctamente.",
    )


# ============================================================================
# DASHBOARD INVENTARIO
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_inventory(request):
    user = request.user

    if not _can_view_inventory(user):
        raise PermissionDenied(
            "No tienes permiso para ver información de inventario."
        )

    stocks_qs = (
        InventoryStock.objects
        .select_related(
            "warehouse",
            "warehouse__branch",
            "product",
        )
        .all()
    )

    stocks_qs = apply_branch_scope(
        stocks_qs,
        user,
        branch_field="warehouse__branch",
    )

    lots_qs = (
        InventoryLot.objects
        .select_related(
            "warehouse",
            "warehouse__branch",
            "product",
        )
        .all()
    )

    lots_qs = apply_branch_scope(
        lots_qs,
        user,
        branch_field="warehouse__branch",
    )

    today = timezone.now().date()
    expiring_limit = today + timedelta(days=30)

    data = {
        "stock_items":
            stocks_qs.count(),

        "total_quantity":
            stocks_qs.aggregate(
                total=Sum("quantity")
            )["total"]
            or 0,

        "available_quantity":
            stocks_qs.aggregate(
                total=Sum(F("quantity") - F("reserved_quantity"))
            )["total"]
            or 0,

        "total_reserved_quantity":
            stocks_qs.aggregate(
                total=Sum("reserved_quantity")
            )["total"]
            or 0,

        "lots_total":
            lots_qs.count(),

        "lots_expiring_soon":
            lots_qs.filter(
                expiration_date__isnull=False,
                expiration_date__gte=today,
                expiration_date__lte=expiring_limit,
            ).count(),

        "lots_expired":
            lots_qs.filter(
                expiration_date__isnull=False,
                expiration_date__lt=today,
            ).count(),
    }

    return api_response(
        data=data,
        message="Dashboard de inventario obtenido correctamente.",
    )


# ============================================================================
# DASHBOARD COMPRAS
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_purchasing(request):
    user = request.user

    can_supply_requests = _can_view_supply_requests(user)
    can_purchase_orders = _can_view_purchase_orders(user)

    if not (
        can_supply_requests
        or can_purchase_orders
    ):
        raise PermissionDenied(
            "No tienes permiso para ver información de compras."
        )

    data = {
        "supply_requests_by_status": [],
        "purchase_orders_by_status": [],
        "purchase_receipts_by_status": [],
        "purchase_orders_total_amount": 0,
    }

    # ------------------------------------------------------------------------
    # Solicitudes
    # ------------------------------------------------------------------------

    if can_supply_requests:
        supply_qs = (
            SupplyRequest.objects
            .select_related("branch")
            .all()
        )

        supply_qs = apply_branch_scope(
            supply_qs,
            user,
            branch_field="branch",
        )

        data["supply_requests_by_status"] = list(
            supply_qs
            .values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        )

    # ------------------------------------------------------------------------
    # Órdenes / recepciones
    # ------------------------------------------------------------------------

    if can_purchase_orders:
        po_qs = (
            PurchaseOrder.objects
            .select_related(
                "branch",
                "supplier",
            )
            .all()
        )

        po_qs = apply_branch_scope(
            po_qs,
            user,
            branch_field="branch",
        )

        receipt_qs = (
            PurchaseReceipt.objects
            .select_related("branch")
            .all()
        )

        receipt_qs = apply_branch_scope(
            receipt_qs,
            user,
            branch_field="branch",
        )

        data["purchase_orders_by_status"] = list(
            po_qs
            .values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        )

        data["purchase_receipts_by_status"] = list(
            receipt_qs
            .values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        )

        data["purchase_orders_total_amount"] = (
            po_qs.aggregate(
                total=Sum("total_amount")
            )["total"]
            or 0
        )

    return api_response(
        data=data,
        message="Dashboard de compras obtenido correctamente.",
    )


# ============================================================================
# DASHBOARD FINANZAS
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_finance(request):
    user = request.user

    if not _can_view_finance(user):
        raise PermissionDenied(
            "No tienes permiso para ver información financiera."
        )

    invoices_qs = (
        SupplierInvoice.objects
        .select_related("legal_entity")
        .all()
    )

    invoices_qs = apply_legal_entity_scope(
        invoices_qs,
        user,
        legal_entity_field="legal_entity",
    )

    payments_qs = (
        Payment.objects
        .select_related("legal_entity")
        .all()
    )

    payments_qs = apply_legal_entity_scope(
        payments_qs,
        user,
        legal_entity_field="legal_entity",
    )

    budgets_qs = (
        Budget.objects
        .select_related("legal_entity")
        .all()
    )

    budgets_qs = apply_legal_entity_scope(
        budgets_qs,
        user,
        legal_entity_field="legal_entity",
    )

    total_invoiced_amount = (
        invoices_qs.aggregate(
            total=Sum("total_amount")
        )["total"]
        or 0
    )

    total_paid_amount = (
        payments_qs.aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    budget_amount_total = (
        budgets_qs.aggregate(
            total=Sum("budget_amount")
        )["total"]
        or 0
    )

    budget_consumed_total = (
        budgets_qs.aggregate(
            total=Sum("consumed_amount")
        )["total"]
        or 0
    )

    budget_available_total = (
        budget_amount_total
        - budget_consumed_total
    )

    data = {
        "invoices_by_status": list(
            invoices_qs
            .values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        ),

        "payments_by_status": list(
            payments_qs
            .values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        ),

        "total_invoiced_amount":
            total_invoiced_amount,

        "total_paid_amount":
            total_paid_amount,

        "budget_amount_total":
            budget_amount_total,

        "budget_consumed_total":
            budget_consumed_total,

        "budget_available_total":
            budget_available_total,
    }

    return api_response(
        data=data,
        message="Dashboard financiero obtenido correctamente.",
    )

# ============================================================================
# TABLERO EJECUTIVO
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_executive(request):
    """
    Todo lo que la pantalla de inicio necesita, en una sola llamada.

    Se prefiere un endpoint agregado a seis pequeños porque el tablero los
    consume siempre juntos: seis viajes para pintar una pantalla se notan, y
    dejarían los bloques llegando en desorden.

    Un bloque en None significa "sin permiso"; una lista vacía, "sin datos".
    La interfaz necesita distinguirlos para no decirle "no hay información" a
    quien en realidad no tiene acceso.

    Parámetros:
        months        cuántos meses cubre la serie (1 a 36, por defecto 12)
        legal_entity  uuid de una razón social para acotar el tablero
    """
    from apps.dashboard import executive as ex

    user = request.user

    try:
        months = int(request.query_params.get("months", 12))
    except (TypeError, ValueError):
        months = 12
    months = max(1, min(36, months))

    periodo = ex.month_range(months)

    legal_entity = None
    uuid_param = request.query_params.get("legal_entity")
    if uuid_param:
        from apps.organizations.models import LegalEntity

        legal_entity = LegalEntity.objects.filter(uuid=uuid_param).first()

    can_finance = _can_view_finance(user)
    can_inventory = _can_view_inventory(user)
    can_purchasing = _can_view_supply_requests(user) or _can_view_purchase_orders(user)

    data = {
        "period": {
            "months": months,
            "from": periodo[0].isoformat(),
            "to": periodo[-1].isoformat(),
            "labels": [ex.month_label(m) for m in periodo],
        },
        "access": {
            "finance": can_finance,
            "inventory": can_inventory,
            "purchasing": can_purchasing,
        },
        "kpis": {},
        "revenue": None,
        "budget": None,
        "purchasing": None,
        "inventory": None,
    }

    # ── Ingreso, cobranza y presupuesto ────────────────────────────────────
    if can_finance:
        revenue = ex.revenue_blocks(user, periodo, legal_entity=legal_entity)
        budget = ex.budget_block(user, legal_entity=legal_entity)

        series = revenue.pop("_series")
        deuda = revenue.pop("_receivable_total")

        data["revenue"] = revenue
        data["budget"] = budget

        # El mes en curso contra el anterior. El último punto de la serie es el
        # mes corriente, que va incompleto: se compara igual y la interfaz lo
        # rotula como "en curso" para que nadie lea la caída como un desplome.
        def actual_y_previo(clave):
            serie = series[clave]
            actual = serie[-1] if serie else ex.ZERO
            previo = serie[-2] if len(serie) > 1 else None
            return actual, previo

        ingreso_actual, ingreso_previo = actual_y_previo("revenue")
        caja_actual, caja_previo = actual_y_previo("collected")

        data["kpis"]["revenue_accrued"] = ex._kpi(
            float(ingreso_actual),
            float(ingreso_previo) if ingreso_previo is not None else None,
            series["revenue"],
        )
        data["kpis"]["revenue_collected"] = ex._kpi(
            float(caja_actual),
            float(caja_previo) if caja_previo is not None else None,
            series["collected"],
        )
        data["kpis"]["receivable_pending"] = ex._kpi(deuda)
        data["kpis"]["budget_execution"] = ex._kpi(
            budget["execution_pct"] or 0,
            unit="PCT",
        )

    # ── Compras ────────────────────────────────────────────────────────────
    if can_purchasing:
        compras = ex.purchasing_block(user, periodo, legal_entity=legal_entity)
        data["purchasing"] = compras

        data["kpis"]["pending_receipts"] = ex._kpi(
            compras["pending_receipts"], unit="COUNT"
        )
        data["kpis"]["extraordinary_pct"] = ex._kpi(
            compras["extraordinary_pct"] or 0, unit="PCT"
        )

    # ── Inventario ─────────────────────────────────────────────────────────
    if can_inventory:
        inventario = ex.inventory_block(user)
        data["inventory"] = inventario

        data["kpis"]["low_stock"] = ex._kpi(
            inventario["low_stock_count"], unit="COUNT"
        )
        data["kpis"]["expiring_lots"] = ex._kpi(
            inventario["expiring_count"], unit="COUNT"
        )

    return api_response(
        data=data,
        message="Tablero ejecutivo obtenido correctamente.",
    )
