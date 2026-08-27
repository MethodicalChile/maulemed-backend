"""
Tablero ejecutivo.

Reúne en una sola respuesta lo que la pantalla de inicio necesita: los seis
números de titular, las series mensuales y los cortes por sociedad, financiador
y línea presupuestaria.

Va en un módulo aparte de views.py porque son ~400 líneas de agregación que no
tienen nada que ver con los cuatro dashboards antiguos, y mezclarlas volvería
ese archivo inmanejable.

Dos reglas que se respetan en todo el módulo:

1. **Todo se agrega en la base**, con values().annotate(). Ningún bucle de
   Python sobre un queryset completo — es el problema que ya tiene
   dashboard_summary y que a escala de quince sociedades se nota.

2. **Sin permiso es None, sin datos es vacío.** Un bloque en None significa
   "este usuario no puede ver esto"; una lista vacía significa "no hay nada que
   mostrar". La interfaz necesita distinguirlos para no decir "sin datos" a
   quien en realidad no tiene acceso.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import (
    Count,
    DecimalField,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.common.scopes import apply_branch_scope, apply_legal_entity_scope
from apps.finance.models import Budget, SupplierInvoice
from apps.inventory.models import InventoryLot, InventoryStock
from apps.products.models import BranchProduct
from apps.purchasing.models import PurchaseOrder, PurchaseReceipt, SupplyRequest
from apps.revenue.models import (
    AccountReceivable,
    CashCollection,
    Financier,
    RevenueEntry,
)


ZERO = Decimal("0")

MONEY = DecimalField(max_digits=18, decimal_places=2)


def _money_sum(field):
    """Suma que devuelve 0 en vez de None, para no ensuciar la respuesta."""
    return Coalesce(Sum(field), Value(ZERO), output_field=MONEY)


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------

def month_start(value):
    return date(value.year, value.month, 1)


def shift_month(value, delta):
    """Mueve un primero-de-mes N meses, hacia atrás o hacia adelante."""
    total = value.year * 12 + (value.month - 1) + delta
    return date(total // 12, total % 12 + 1, 1)


def month_range(months):
    """
    Los primeros de mes del período, del más antiguo al actual.

    Se devuelven todos, incluidos los meses sin movimiento: una serie temporal
    con huecos se dibuja mal y hace parecer que el negocio se detuvo.
    """
    actual = month_start(timezone.localdate())
    return [shift_month(actual, -i) for i in range(months - 1, -1, -1)]


def month_label(value):
    NOMBRES = [
        "Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
    ]
    return f"{NOMBRES[value.month - 1]} {value.year % 100:02d}"


def _series_by_month(queryset, date_field, value_expr, months):
    """Serie mensual completa, con ceros donde no hubo movimiento."""
    filas = (
        queryset.annotate(mes=TruncMonth(date_field))
        .values("mes")
        .annotate(total=value_expr)
        .order_by("mes")
    )

    por_mes = {}
    for fila in filas:
        mes = fila["mes"]
        if mes is None:
            continue
        if hasattr(mes, "date"):
            mes = mes.date()
        por_mes[month_start(mes)] = fila["total"] or ZERO

    return [por_mes.get(m, ZERO) for m in months]


def _delta_pct(actual, anterior):
    """
    Variación porcentual. None cuando no hay base de comparación: mostrar
    "+100 %" porque el mes anterior fue cero es ruido, no información.
    """
    actual = Decimal(actual or 0)
    anterior = Decimal(anterior or 0)

    if anterior == 0:
        return None

    return round(float((actual - anterior) / anterior * 100), 1)


def _kpi(value, previous=None, sparkline=None, unit="CLP"):
    return {
        "value": value,
        "previous": previous,
        "delta_pct": _delta_pct(value, previous) if previous is not None else None,
        "sparkline": [float(v) for v in (sparkline or [])],
        "unit": unit,
    }


# ---------------------------------------------------------------------------
# Bloques
# ---------------------------------------------------------------------------

def revenue_blocks(user, months, legal_entity=None):
    """Todo lo que cuelga del ingreso: tendencia, sociedades, caja, cobranza."""

    desde = months[0]

    entradas = apply_legal_entity_scope(
        RevenueEntry.objects.filter(service_date__gte=desde),
        user,
        legal_entity_field="legal_entity",
    )
    cajas = apply_legal_entity_scope(
        CashCollection.objects.filter(collection_date__gte=desde),
        user,
        legal_entity_field="legal_entity",
    )
    facturas = apply_legal_entity_scope(
        SupplierInvoice.objects.filter(issue_date__gte=desde),
        user,
        legal_entity_field="legal_entity",
    )
    cobranza = apply_legal_entity_scope(
        AccountReceivable.objects.all(),
        user,
        legal_entity_field="legal_entity",
    )

    if legal_entity is not None:
        entradas = entradas.filter(legal_entity=legal_entity)
        cajas = cajas.filter(legal_entity=legal_entity)
        facturas = facturas.filter(legal_entity=legal_entity)
        cobranza = cobranza.filter(legal_entity=legal_entity)

    # ── Serie mensual: devengado contra gasto ──────────────────────────────
    devengado = _series_by_month(entradas, "service_date", _money_sum("net_amount"), months)
    percibido = _series_by_month(cajas, "collection_date", _money_sum("total_amount"), months)
    gasto = _series_by_month(facturas, "issue_date", _money_sum("total_amount"), months)

    trend = [
        {
            "month": m.isoformat(),
            "label": month_label(m),
            "revenue": float(devengado[i]),
            "collected": float(percibido[i]),
            "expense": float(gasto[i]),
        }
        for i, m in enumerate(months)
    ]

    # ── Ingreso por razón social ───────────────────────────────────────────
    por_sociedad = list(
        entradas.values("legal_entity__uuid", "legal_entity__name", "legal_entity__rut")
        .annotate(
            entries=Count("id"),
            appointments=Count("appointment_ref", distinct=True),
            amount=_money_sum("net_amount"),
        )
        .order_by("-amount")
    )

    # ── Medios de pago de la recaudación ───────────────────────────────────
    medios = cajas.aggregate(
        efectivo=_money_sum("cash_amount"),
        debito=_money_sum("debit_amount"),
        credito=_money_sum("credit_amount"),
        cheque=_money_sum("check_amount"),
        particular=_money_sum("particular_amount"),
        copago=_money_sum("copay_amount"),
    )

    # ── Antigüedad de la cobranza ──────────────────────────────────────────
    aging = _aging(cobranza)

    return {
        "trend": trend,
        "by_legal_entity": [
            {
                "uuid": str(f["legal_entity__uuid"]),
                "name": f["legal_entity__name"],
                "rut": f["legal_entity__rut"],
                "entries": f["entries"],
                "appointments": f["appointments"],
                "amount": float(f["amount"]),
            }
            for f in por_sociedad
        ],
        "payment_methods": {k: float(v) for k, v in medios.items()},
        "receivable_aging": aging,
        "_series": {"revenue": devengado, "collected": percibido, "expense": gasto},
        "_receivable_total": float(
            sum(a["total_pending"] for a in aging) if aging else 0
        ),
    }


AGING_BUCKETS = ["Sin vencer", "1-30", "31-60", "61-90", "90+", "Sin fecha"]


def _aging(queryset):
    """
    Antigüedad por financiador.

    Se calcula en Python sobre las cuentas con saldo —decenas de filas, no
    miles— porque el tramo depende de la fecha de hoy y de si la cuenta tiene
    vencimiento comprometido. Expresarlo en SQL complicaría la consulta sin
    ganar nada a este volumen.
    """
    pendientes = queryset.filter(
        billed_amount__gt=F("collected_amount")
    ).select_related("financier")

    por_financiador = {}

    for cuenta in pendientes:
        clave = cuenta.financier_id
        fila = por_financiador.setdefault(
            clave,
            {
                "financier": cuenta.financier.name,
                "financier_type": cuenta.financier.financier_type,
                "total_pending": 0.0,
                "buckets": {b: 0.0 for b in AGING_BUCKETS},
            },
        )
        monto = float(cuenta.pending_amount)
        fila["total_pending"] += monto
        fila["buckets"][cuenta.aging_bucket] += monto

    return sorted(
        por_financiador.values(), key=lambda f: f["total_pending"], reverse=True
    )


def budget_block(user, legal_entity=None):
    """Ejecución presupuestaria del mes en curso, por línea."""

    hoy = timezone.localdate()

    presupuestos = apply_legal_entity_scope(
        Budget.objects.filter(period_year=hoy.year, period_month=hoy.month),
        user,
        legal_entity_field="legal_entity",
    ).select_related("budget_category")

    if legal_entity is not None:
        presupuestos = presupuestos.filter(legal_entity=legal_entity)

    filas = list(
        presupuestos.filter(budget_category__isnull=False)
        .values("budget_category__code", "budget_category__name", "budget_category__block")
        .annotate(
            budget=_money_sum("budget_amount"),
            committed=_money_sum("committed_amount"),
            consumed=_money_sum("consumed_amount"),
        )
        .order_by("budget_category__display_order")
    )

    lineas = []
    for f in filas:
        presupuesto = float(f["budget"])
        usado = float(f["committed"]) + float(f["consumed"])
        lineas.append(
            {
                "code": f["budget_category__code"],
                "name": f["budget_category__name"],
                "block": f["budget_category__block"],
                "budget": presupuesto,
                "committed": float(f["committed"]),
                "consumed": float(f["consumed"]),
                "used": usado,
                "available": presupuesto - usado,
                "used_pct": round(usado / presupuesto * 100, 1) if presupuesto else None,
            }
        )

    totales = presupuestos.aggregate(
        budget=_money_sum("budget_amount"),
        committed=_money_sum("committed_amount"),
        consumed=_money_sum("consumed_amount"),
    )
    total_ppto = float(totales["budget"])
    total_usado = float(totales["committed"]) + float(totales["consumed"])

    return {
        "lines": lineas,
        "total_budget": total_ppto,
        "total_used": total_usado,
        "execution_pct": round(total_usado / total_ppto * 100, 1) if total_ppto else None,
    }


# Los ocho estados de la solicitud y los diez de la orden no se pueden pintar:
# más de siete clases con significado dejan de distinguirse. Se agrupan en las
# cuatro fases que la operación reconoce.
PIPELINE_GROUPS = [
    ("draft", "Por enviar", ["BORRADOR"]),
    ("in_review", "En revisión", ["ENVIADA", "EN_REVISION", "OBSERVADA", "EN_APROBACION"]),
    (
        "approved",
        "Aprobada o en camino",
        [
            "APROBADA",
            "PARCIALMENTE_APROBADA",
            "CONVERTIDA_EN_COMPRA",
            "ENVIADA_PROVEEDOR",
            "ACEPTADA_PROVEEDOR",
            "PARCIALMENTE_RECIBIDA",
        ],
    ),
    ("closed", "Cerrada", ["RECIBIDA", "CERRADA"]),
    ("rejected", "Rechazada o anulada", ["RECHAZADA", "RECHAZADA_PROVEEDOR", "CANCELADA"]),
]


def purchasing_block(user, months, legal_entity=None):
    desde = months[0]

    # Evita created_at__date__gte: aplicar DATE() sobre la columna puede impedir
    # que PostgreSQL aproveche un índice B-Tree normal sobre created_at.
    desde_dt = datetime.combine(desde, time.min)
    if settings.USE_TZ:
        desde_dt = timezone.make_aware(desde_dt, timezone.get_current_timezone())

    solicitudes = apply_branch_scope(
        SupplyRequest.objects.all(),
        user,
        branch_field="branch",
    )
    ordenes = apply_branch_scope(
        PurchaseOrder.objects.filter(created_at__gte=desde_dt),
        user,
        branch_field="branch",
    )

    if legal_entity is not None:
        solicitudes = solicitudes.filter(legal_entity=legal_entity)
        ordenes = ordenes.filter(legal_entity=legal_entity)

    def agrupar_conteo(conteo):
        return [
            {
                "key": key,
                "label": etiqueta,
                "count": sum(conteo.get(estado, 0) for estado in estados),
            }
            for key, etiqueta, estados in PIPELINE_GROUPS
        ]

    # Una sola query para todo el pipeline de solicitudes.
    conteo_solicitudes = {
        fila["status"]: fila["total"]
        for fila in solicitudes.values("status").annotate(total=Count("id"))
    }

    # Antes se ejecutaban cuatro queries sobre PurchaseOrder:
    #   1) agrupación por status
    #   2) total de órdenes
    #   3) extraordinarias
    #   4) pendientes de recepción
    #
    # Agrupando por status + purchase_type obtenemos todo en una sola query.
    filas_ordenes = list(
        ordenes.values("status", "purchase_type").annotate(total=Count("id"))
    )

    conteo_ordenes = {}
    total_ordenes = 0
    extraordinarias = 0
    pendientes_recepcion = 0

    tipos_extraordinarios = {
        PurchaseOrder.PURCHASE_TYPE_URGENT,
        PurchaseOrder.PURCHASE_TYPE_MANAGEMENT,
    }
    estados_pendientes_recepcion = {
        PurchaseOrder.STATUS_APPROVED,
        PurchaseOrder.STATUS_SENT_TO_SUPPLIER,
        PurchaseOrder.STATUS_ACCEPTED_BY_SUPPLIER,
        PurchaseOrder.STATUS_PARTIALLY_RECEIVED,
    }

    for fila in filas_ordenes:
        total = fila["total"]
        estado = fila["status"]
        tipo_compra = fila["purchase_type"]

        total_ordenes += total
        conteo_ordenes[estado] = conteo_ordenes.get(estado, 0) + total

        if tipo_compra in tipos_extraordinarios:
            extraordinarias += total

        if estado in estados_pendientes_recepcion:
            pendientes_recepcion += total

    proveedores = apply_legal_entity_scope(
        SupplierInvoice.objects.filter(issue_date__gte=desde),
        user,
        legal_entity_field="legal_entity",
    )
    if legal_entity is not None:
        proveedores = proveedores.filter(legal_entity=legal_entity)

    top = list(
        proveedores.values("supplier__uuid", "supplier__name")
        .annotate(invoices=Count("id"), amount=_money_sum("total_amount"))
        .order_by("-amount")[:6]
    )

    return {
        "supply_requests": agrupar_conteo(conteo_solicitudes),
        "purchase_orders": agrupar_conteo(conteo_ordenes),
        "orders_total": total_ordenes,
        "extraordinary_orders": extraordinarias,
        "extraordinary_pct": (
            round(extraordinarias / total_ordenes * 100, 1)
            if total_ordenes
            else None
        ),
        "pending_receipts": pendientes_recepcion,
        "top_suppliers": [
            {
                "uuid": str(f["supplier__uuid"]) if f["supplier__uuid"] else None,
                "name": f["supplier__name"] or "Sin proveedor",
                "invoices": f["invoices"],
                "amount": float(f["amount"]),
            }
            for f in top
        ],
    }


def inventory_block(user):
    # Para los conteos no necesitamos instanciar relaciones con select_related.
    # Lo aplicamos únicamente al queryset que sí devuelve los lotes al frontend.
    stocks = apply_branch_scope(
        InventoryStock.objects.all(),
        user,
        branch_field="warehouse__branch",
    )
    lotes = apply_branch_scope(
        InventoryLot.objects.all(),
        user,
        branch_field="warehouse__branch",
    )

    hoy = timezone.localdate()
    limite = hoy + timedelta(days=30)

    # El umbral vive en BranchProduct. Las subconsultas se ejecutan dentro de la
    # misma sentencia SQL que calcula ambos conteos de stock.
    umbral_critico = Subquery(
        BranchProduct.objects.filter(
            branch=OuterRef("warehouse__branch"),
            product=OuterRef("product"),
            is_active=True,
        ).values("critical_stock")[:1]
    )
    umbral_minimo = Subquery(
        BranchProduct.objects.filter(
            branch=OuterRef("warehouse__branch"),
            product=OuterRef("product"),
            is_active=True,
        ).values("min_stock")[:1]
    )

    stocks_con_umbral = stocks.annotate(
        disponible=F("quantity") - F("reserved_quantity"),
        critico=umbral_critico,
        minimo=umbral_minimo,
    )

    condicion_bajo_umbral = (
        Q(critico__gt=0, disponible__lte=F("critico"))
        | Q(critico=0, minimo__gt=0, disponible__lte=F("minimo"))
    )

    # Antes: stocks.count() + bajo_umbral.count() = 2 queries.
    # Ahora ambos valores salen de una sola agregación SQL.
    stock_stats = stocks_con_umbral.aggregate(
        stock_items=Count("id"),
        low_stock_count=Count("id", filter=condicion_bajo_umbral),
    )

    # Antes expiring_count y expired_count ejecutaban un COUNT independiente.
    # Ambos conteos se obtienen ahora en una sola query.
    lot_stats = lotes.aggregate(
        expiring_count=Count(
            "id",
            filter=Q(
                expiration_date__isnull=False,
                expiration_date__gte=hoy,
                expiration_date__lte=limite,
                quantity__gt=0,
            ),
        ),
        expired_count=Count(
            "id",
            filter=Q(
                expiration_date__lt=hoy,
                quantity__gt=0,
            ),
        ),
    )

    # Esta sí devuelve objetos, por eso aquí conviene select_related.
    por_vencer = (
        lotes.filter(
            expiration_date__isnull=False,
            expiration_date__gte=hoy,
            expiration_date__lte=limite,
            quantity__gt=0,
        )
        .select_related("warehouse", "product")
        .only(
            "lot_number",
            "expiration_date",
            "quantity",
            "warehouse__name",
            "product__name",
        )
        .order_by("expiration_date")[:8]
    )

    return {
        "stock_items": stock_stats["stock_items"],
        "low_stock_count": stock_stats["low_stock_count"],
        "expiring_count": lot_stats["expiring_count"],
        "expired_count": lot_stats["expired_count"],
        "expiring_lots": [
            {
                "product": lote.product.name,
                "warehouse": lote.warehouse.name,
                "lot_number": lote.lot_number or "—",
                "expiration_date": lote.expiration_date.isoformat(),
                "days_left": (lote.expiration_date - hoy).days,
                "quantity": float(lote.quantity),
            }
            for lote in por_vencer
        ],
    }


# """
# Tablero ejecutivo.

# Reúne en una sola respuesta lo que la pantalla de inicio necesita: los seis
# números de titular, las series mensuales y los cortes por sociedad, financiador
# y línea presupuestaria.

# Va en un módulo aparte de views.py porque son ~400 líneas de agregación que no
# tienen nada que ver con los cuatro dashboards antiguos, y mezclarlas volvería
# ese archivo inmanejable.

# Dos reglas que se respetan en todo el módulo:

# 1. **Todo se agrega en la base**, con values().annotate(). Ningún bucle de
#    Python sobre un queryset completo — es el problema que ya tiene
#    dashboard_summary y que a escala de quince sociedades se nota.

# 2. **Sin permiso es None, sin datos es vacío.** Un bloque en None significa
#    "este usuario no puede ver esto"; una lista vacía significa "no hay nada que
#    mostrar". La interfaz necesita distinguirlos para no decir "sin datos" a
#    quien en realidad no tiene acceso.
# """

# from datetime import date, timedelta
# from decimal import Decimal

# from django.db.models import (
#     Count,
#     DecimalField,
#     F,
#     OuterRef,
#     Q,
#     Subquery,
#     Sum,
#     Value,
# )
# from django.db.models.functions import Coalesce, TruncMonth
# from django.utils import timezone

# from apps.common.scopes import apply_branch_scope, apply_legal_entity_scope
# from apps.finance.models import Budget, SupplierInvoice
# from apps.inventory.models import InventoryLot, InventoryStock
# from apps.products.models import BranchProduct
# from apps.purchasing.models import PurchaseOrder, PurchaseReceipt, SupplyRequest
# from apps.revenue.models import (
#     AccountReceivable,
#     CashCollection,
#     Financier,
#     RevenueEntry,
# )


# ZERO = Decimal("0")

# MONEY = DecimalField(max_digits=18, decimal_places=2)


# def _money_sum(field):
#     """Suma que devuelve 0 en vez de None, para no ensuciar la respuesta."""
#     return Coalesce(Sum(field), Value(ZERO), output_field=MONEY)


# # ---------------------------------------------------------------------------
# # Calendario
# # ---------------------------------------------------------------------------

# def month_start(value):
#     return date(value.year, value.month, 1)


# def shift_month(value, delta):
#     """Mueve un primero-de-mes N meses, hacia atrás o hacia adelante."""
#     total = value.year * 12 + (value.month - 1) + delta
#     return date(total // 12, total % 12 + 1, 1)


# def month_range(months):
#     """
#     Los primeros de mes del período, del más antiguo al actual.

#     Se devuelven todos, incluidos los meses sin movimiento: una serie temporal
#     con huecos se dibuja mal y hace parecer que el negocio se detuvo.
#     """
#     actual = month_start(timezone.localdate())
#     return [shift_month(actual, -i) for i in range(months - 1, -1, -1)]


# def month_label(value):
#     NOMBRES = [
#         "Ene", "Feb", "Mar", "Abr", "May", "Jun",
#         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
#     ]
#     return f"{NOMBRES[value.month - 1]} {value.year % 100:02d}"


# def _series_by_month(queryset, date_field, value_expr, months):
#     """Serie mensual completa, con ceros donde no hubo movimiento."""
#     filas = (
#         queryset.annotate(mes=TruncMonth(date_field))
#         .values("mes")
#         .annotate(total=value_expr)
#         .order_by("mes")
#     )

#     por_mes = {}
#     for fila in filas:
#         mes = fila["mes"]
#         if mes is None:
#             continue
#         if hasattr(mes, "date"):
#             mes = mes.date()
#         por_mes[month_start(mes)] = fila["total"] or ZERO

#     return [por_mes.get(m, ZERO) for m in months]


# def _delta_pct(actual, anterior):
#     """
#     Variación porcentual. None cuando no hay base de comparación: mostrar
#     "+100 %" porque el mes anterior fue cero es ruido, no información.
#     """
#     actual = Decimal(actual or 0)
#     anterior = Decimal(anterior or 0)

#     if anterior == 0:
#         return None

#     return round(float((actual - anterior) / anterior * 100), 1)


# def _kpi(value, previous=None, sparkline=None, unit="CLP"):
#     return {
#         "value": value,
#         "previous": previous,
#         "delta_pct": _delta_pct(value, previous) if previous is not None else None,
#         "sparkline": [float(v) for v in (sparkline or [])],
#         "unit": unit,
#     }


# # ---------------------------------------------------------------------------
# # Bloques
# # ---------------------------------------------------------------------------

# def revenue_blocks(user, months, legal_entity=None):
#     """Todo lo que cuelga del ingreso: tendencia, sociedades, caja, cobranza."""

#     desde = months[0]

#     entradas = apply_legal_entity_scope(
#         RevenueEntry.objects.filter(service_date__gte=desde),
#         user,
#         legal_entity_field="legal_entity",
#     )
#     cajas = apply_legal_entity_scope(
#         CashCollection.objects.filter(collection_date__gte=desde),
#         user,
#         legal_entity_field="legal_entity",
#     )
#     facturas = apply_legal_entity_scope(
#         SupplierInvoice.objects.filter(issue_date__gte=desde),
#         user,
#         legal_entity_field="legal_entity",
#     )
#     cobranza = apply_legal_entity_scope(
#         AccountReceivable.objects.all(),
#         user,
#         legal_entity_field="legal_entity",
#     )

#     if legal_entity is not None:
#         entradas = entradas.filter(legal_entity=legal_entity)
#         cajas = cajas.filter(legal_entity=legal_entity)
#         facturas = facturas.filter(legal_entity=legal_entity)
#         cobranza = cobranza.filter(legal_entity=legal_entity)

#     # ── Serie mensual: devengado contra gasto ──────────────────────────────
#     devengado = _series_by_month(entradas, "service_date", _money_sum("net_amount"), months)
#     percibido = _series_by_month(cajas, "collection_date", _money_sum("total_amount"), months)
#     gasto = _series_by_month(facturas, "issue_date", _money_sum("total_amount"), months)

#     trend = [
#         {
#             "month": m.isoformat(),
#             "label": month_label(m),
#             "revenue": float(devengado[i]),
#             "collected": float(percibido[i]),
#             "expense": float(gasto[i]),
#         }
#         for i, m in enumerate(months)
#     ]

#     # ── Ingreso por razón social ───────────────────────────────────────────
#     por_sociedad = list(
#         entradas.values("legal_entity__uuid", "legal_entity__name", "legal_entity__rut")
#         .annotate(
#             entries=Count("id"),
#             appointments=Count("appointment_ref", distinct=True),
#             amount=_money_sum("net_amount"),
#         )
#         .order_by("-amount")
#     )

#     # ── Medios de pago de la recaudación ───────────────────────────────────
#     medios = cajas.aggregate(
#         efectivo=_money_sum("cash_amount"),
#         debito=_money_sum("debit_amount"),
#         credito=_money_sum("credit_amount"),
#         cheque=_money_sum("check_amount"),
#         particular=_money_sum("particular_amount"),
#         copago=_money_sum("copay_amount"),
#     )

#     # ── Antigüedad de la cobranza ──────────────────────────────────────────
#     aging = _aging(cobranza)

#     return {
#         "trend": trend,
#         "by_legal_entity": [
#             {
#                 "uuid": str(f["legal_entity__uuid"]),
#                 "name": f["legal_entity__name"],
#                 "rut": f["legal_entity__rut"],
#                 "entries": f["entries"],
#                 "appointments": f["appointments"],
#                 "amount": float(f["amount"]),
#             }
#             for f in por_sociedad
#         ],
#         "payment_methods": {k: float(v) for k, v in medios.items()},
#         "receivable_aging": aging,
#         "_series": {"revenue": devengado, "collected": percibido, "expense": gasto},
#         "_receivable_total": float(
#             sum(a["total_pending"] for a in aging) if aging else 0
#         ),
#     }


# AGING_BUCKETS = ["Sin vencer", "1-30", "31-60", "61-90", "90+", "Sin fecha"]


# def _aging(queryset):
#     """
#     Antigüedad por financiador.

#     Se calcula en Python sobre las cuentas con saldo —decenas de filas, no
#     miles— porque el tramo depende de la fecha de hoy y de si la cuenta tiene
#     vencimiento comprometido. Expresarlo en SQL complicaría la consulta sin
#     ganar nada a este volumen.
#     """
#     pendientes = queryset.filter(
#         billed_amount__gt=F("collected_amount")
#     ).select_related("financier")

#     por_financiador = {}

#     for cuenta in pendientes:
#         clave = cuenta.financier_id
#         fila = por_financiador.setdefault(
#             clave,
#             {
#                 "financier": cuenta.financier.name,
#                 "financier_type": cuenta.financier.financier_type,
#                 "total_pending": 0.0,
#                 "buckets": {b: 0.0 for b in AGING_BUCKETS},
#             },
#         )
#         monto = float(cuenta.pending_amount)
#         fila["total_pending"] += monto
#         fila["buckets"][cuenta.aging_bucket] += monto

#     return sorted(
#         por_financiador.values(), key=lambda f: f["total_pending"], reverse=True
#     )


# def budget_block(user, legal_entity=None):
#     """Ejecución presupuestaria del mes en curso, por línea."""

#     hoy = timezone.localdate()

#     presupuestos = apply_legal_entity_scope(
#         Budget.objects.filter(period_year=hoy.year, period_month=hoy.month),
#         user,
#         legal_entity_field="legal_entity",
#     ).select_related("budget_category")

#     if legal_entity is not None:
#         presupuestos = presupuestos.filter(legal_entity=legal_entity)

#     filas = list(
#         presupuestos.filter(budget_category__isnull=False)
#         .values("budget_category__code", "budget_category__name", "budget_category__block")
#         .annotate(
#             budget=_money_sum("budget_amount"),
#             committed=_money_sum("committed_amount"),
#             consumed=_money_sum("consumed_amount"),
#         )
#         .order_by("budget_category__display_order")
#     )

#     lineas = []
#     for f in filas:
#         presupuesto = float(f["budget"])
#         usado = float(f["committed"]) + float(f["consumed"])
#         lineas.append(
#             {
#                 "code": f["budget_category__code"],
#                 "name": f["budget_category__name"],
#                 "block": f["budget_category__block"],
#                 "budget": presupuesto,
#                 "committed": float(f["committed"]),
#                 "consumed": float(f["consumed"]),
#                 "used": usado,
#                 "available": presupuesto - usado,
#                 "used_pct": round(usado / presupuesto * 100, 1) if presupuesto else None,
#             }
#         )

#     totales = presupuestos.aggregate(
#         budget=_money_sum("budget_amount"),
#         committed=_money_sum("committed_amount"),
#         consumed=_money_sum("consumed_amount"),
#     )
#     total_ppto = float(totales["budget"])
#     total_usado = float(totales["committed"]) + float(totales["consumed"])

#     return {
#         "lines": lineas,
#         "total_budget": total_ppto,
#         "total_used": total_usado,
#         "execution_pct": round(total_usado / total_ppto * 100, 1) if total_ppto else None,
#     }


# # Los ocho estados de la solicitud y los diez de la orden no se pueden pintar:
# # más de siete clases con significado dejan de distinguirse. Se agrupan en las
# # cuatro fases que la operación reconoce.
# PIPELINE_GROUPS = [
#     ("draft", "Por enviar", ["BORRADOR"]),
#     ("in_review", "En revisión", ["ENVIADA", "EN_REVISION", "OBSERVADA", "EN_APROBACION"]),
#     (
#         "approved",
#         "Aprobada o en camino",
#         [
#             "APROBADA",
#             "PARCIALMENTE_APROBADA",
#             "CONVERTIDA_EN_COMPRA",
#             "ENVIADA_PROVEEDOR",
#             "ACEPTADA_PROVEEDOR",
#             "PARCIALMENTE_RECIBIDA",
#         ],
#     ),
#     ("closed", "Cerrada", ["RECIBIDA", "CERRADA"]),
#     ("rejected", "Rechazada o anulada", ["RECHAZADA", "RECHAZADA_PROVEEDOR", "CANCELADA"]),
# ]


# def purchasing_block(user, months, legal_entity=None):
#     desde = months[0]

#     solicitudes = apply_branch_scope(SupplyRequest.objects.all(), user, branch_field="branch")
#     ordenes = apply_branch_scope(
#         PurchaseOrder.objects.filter(created_at__date__gte=desde),
#         user,
#         branch_field="branch",
#     )

#     if legal_entity is not None:
#         solicitudes = solicitudes.filter(legal_entity=legal_entity)
#         ordenes = ordenes.filter(legal_entity=legal_entity)

#     def agrupar(queryset):
#         conteo = {
#             f["status"]: f["total"]
#             for f in queryset.values("status").annotate(total=Count("id"))
#         }
#         return [
#             {
#                 "key": key,
#                 "label": etiqueta,
#                 "count": sum(conteo.get(s, 0) for s in estados),
#             }
#             for key, etiqueta, estados in PIPELINE_GROUPS
#         ]

#     # Compras extraordinarias: el indicador que el capítulo 01 pide por nombre.
#     total_ordenes = ordenes.count()
#     extraordinarias = ordenes.filter(
#         purchase_type__in=[
#             PurchaseOrder.PURCHASE_TYPE_URGENT,
#             PurchaseOrder.PURCHASE_TYPE_MANAGEMENT,
#         ]
#     ).count()

#     pendientes_recepcion = ordenes.filter(
#         status__in=[
#             PurchaseOrder.STATUS_APPROVED,
#             PurchaseOrder.STATUS_SENT_TO_SUPPLIER,
#             PurchaseOrder.STATUS_ACCEPTED_BY_SUPPLIER,
#             PurchaseOrder.STATUS_PARTIALLY_RECEIVED,
#         ]
#     ).count()

#     proveedores = apply_legal_entity_scope(
#         SupplierInvoice.objects.filter(issue_date__gte=desde),
#         user,
#         legal_entity_field="legal_entity",
#     )
#     if legal_entity is not None:
#         proveedores = proveedores.filter(legal_entity=legal_entity)

#     top = list(
#         proveedores.values("supplier__uuid", "supplier__name")
#         .annotate(invoices=Count("id"), amount=_money_sum("total_amount"))
#         .order_by("-amount")[:6]
#     )

#     return {
#         "supply_requests": agrupar(solicitudes),
#         "purchase_orders": agrupar(ordenes),
#         "orders_total": total_ordenes,
#         "extraordinary_orders": extraordinarias,
#         "extraordinary_pct": (
#             round(extraordinarias / total_ordenes * 100, 1) if total_ordenes else None
#         ),
#         "pending_receipts": pendientes_recepcion,
#         "top_suppliers": [
#             {
#                 "uuid": str(f["supplier__uuid"]) if f["supplier__uuid"] else None,
#                 "name": f["supplier__name"] or "Sin proveedor",
#                 "invoices": f["invoices"],
#                 "amount": float(f["amount"]),
#             }
#             for f in top
#         ],
#     }


# def inventory_block(user):
#     stocks = apply_branch_scope(
#         InventoryStock.objects.select_related("warehouse", "product"),
#         user,
#         branch_field="warehouse__branch",
#     )
#     lotes = apply_branch_scope(
#         InventoryLot.objects.select_related("warehouse", "product"),
#         user,
#         branch_field="warehouse__branch",
#     )

#     hoy = timezone.localdate()
#     limite = hoy + timedelta(days=30)

#     # El umbral vive en BranchProduct —es el que consulta la alerta— y se trae
#     # con subconsultas correlacionadas por sucursal y producto. Así el conteo
#     # es una sola query, en vez de recorrer todo el stock en Python como hace
#     # dashboard_summary.
#     umbral_critico = Subquery(
#         BranchProduct.objects.filter(
#             branch=OuterRef("warehouse__branch"),
#             product=OuterRef("product"),
#             is_active=True,
#         ).values("critical_stock")[:1]
#     )
#     umbral_minimo = Subquery(
#         BranchProduct.objects.filter(
#             branch=OuterRef("warehouse__branch"),
#             product=OuterRef("product"),
#             is_active=True,
#         ).values("min_stock")[:1]
#     )

#     bajo_umbral = (
#         stocks.annotate(
#             disponible=F("quantity") - F("reserved_quantity"),
#             critico=umbral_critico,
#             minimo=umbral_minimo,
#         )
#         .filter(
#             # critical_stock manda; min_stock es el respaldo cuando es cero.
#             Q(critico__gt=0, disponible__lte=F("critico"))
#             | Q(critico=0, minimo__gt=0, disponible__lte=F("minimo"))
#         )
#     )

#     por_vencer = lotes.filter(
#         expiration_date__isnull=False,
#         expiration_date__gte=hoy,
#         expiration_date__lte=limite,
#         quantity__gt=0,
#     ).order_by("expiration_date")

#     return {
#         "stock_items": stocks.count(),
#         "low_stock_count": bajo_umbral.count(),
#         "expiring_count": por_vencer.count(),
#         "expired_count": lotes.filter(
#             expiration_date__lt=hoy, quantity__gt=0
#         ).count(),
#         "expiring_lots": [
#             {
#                 "product": lote.product.name,
#                 "warehouse": lote.warehouse.name,
#                 "lot_number": lote.lot_number or "—",
#                 "expiration_date": lote.expiration_date.isoformat(),
#                 "days_left": (lote.expiration_date - hoy).days,
#                 "quantity": float(lote.quantity),
#             }
#             for lote in por_vencer[:8]
#         ],
#     }
