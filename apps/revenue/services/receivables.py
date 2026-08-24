"""
Cuentas por cobrar institucionales.

El puente entre lo devengado y lo percibido, que hoy no existe: la única fuente
de ingresos registra lo devengado y el flujo de caja se construye sobre lo
percibido.

Límite conocido de la fuente. El reporte de prestaciones no trae la separación
entre copago y bonificación, así que la deuda se construye sobre el valor total
de las prestaciones del financiador. El informe de depósitos sí trae el copago,
pero agregado por sociedad y no por financiador, de modo que no se puede
repartir. Cerrar esa brecha exige el reporte de facturación y cobranza por
financiador, que es una de las exportaciones que el análisis de datos deja
pedidas al proveedor del sistema clínico.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from ..models import (
    AccountReceivable,
    AccountReceivableItem,
    Financier,
    RevenueEntry,
)


ZERO = Decimal("0")


@transaction.atomic
def build_receivables_from_revenue(*, period_year, period_month, legal_entity=None):
    """
    Construye o actualiza las cuentas por cobrar de un período a partir del
    libro de ingresos.

    Sólo genera deuda para los financiadores marcados como institucionales: el
    particular paga en el mesón y ahí se acaba.

    Es idempotente — recalcula el monto facturado sin tocar lo ya cobrado, para
    que volver a correrlo tras una carga nueva no borre el trabajo de cobranza.
    """

    entries = RevenueEntry.objects.filter(
        service_date__year=period_year,
        service_date__month=period_month,
        financier__generates_receivable=True,
    )

    if legal_entity is not None:
        entries = entries.filter(legal_entity=legal_entity)

    agrupado = (
        entries.values("legal_entity_id", "financier_id")
        .annotate(total=Sum("net_amount"))
        .order_by()
    )

    resultado = []

    for fila in agrupado:
        receivable, _ = AccountReceivable.objects.get_or_create(
            legal_entity_id=fila["legal_entity_id"],
            financier_id=fila["financier_id"],
            period_year=period_year,
            period_month=period_month,
        )

        receivable.billed_amount = fila["total"] or ZERO
        receivable.recalculate_status()
        receivable.save(
            update_fields=["billed_amount", "status", "updated_at"]
        )

        _link_entries(receivable, entries)
        resultado.append(receivable)

    return resultado


def _link_entries(receivable, entries):
    """
    Liga la cuenta con las prestaciones que cobra, para que la factura cruzada
    quede desagregada aunque no pueda emitirse separada.
    """

    del_periodo = entries.filter(
        legal_entity_id=receivable.legal_entity_id,
        financier_id=receivable.financier_id,
    )

    ya_ligadas = set(
        AccountReceivableItem.objects.filter(
            account_receivable=receivable
        ).values_list("revenue_entry_id", flat=True)
    )

    nuevos = [
        AccountReceivableItem(
            account_receivable=receivable,
            revenue_entry=entry,
            amount=entry.net_amount,
        )
        for entry in del_periodo
        if entry.id not in ya_ligadas
    ]

    if nuevos:
        AccountReceivableItem.objects.bulk_create(nuevos)


def register_collection(*, receivable, amount, notes=None):
    """Registra un cobro parcial o total contra una cuenta por cobrar."""

    receivable.collected_amount = (receivable.collected_amount or ZERO) + Decimal(
        str(amount)
    )

    if notes:
        receivable.notes = f"{receivable.notes or ''}\n{notes}".strip()

    receivable.recalculate_status()
    receivable.save(
        update_fields=["collected_amount", "status", "notes", "updated_at"]
    )

    return receivable


def aging_report(queryset):
    """
    Antigüedad de la deuda por financiador.

    Los tramos se calculan en Python y no en SQL porque dependen de la fecha de
    hoy y de si la cuenta tiene fecha comprometida; expresarlo en la base
    complicaría la consulta sin ganar nada a este volumen.
    """

    BUCKETS = ["Sin vencer", "1-30", "31-60", "61-90", "90+", "Sin fecha"]

    por_financiador = {}

    for receivable in queryset.select_related("financier", "legal_entity"):
        pendiente = receivable.pending_amount
        if pendiente <= 0:
            continue

        clave = receivable.financier_id

        if clave not in por_financiador:
            por_financiador[clave] = {
                "financier_uuid": str(receivable.financier.uuid),
                "financier_name": receivable.financier.name,
                "financier_type": receivable.financier.financier_type,
                "total_pending": ZERO,
                "buckets": {b: ZERO for b in BUCKETS},
            }

        fila = por_financiador[clave]
        fila["total_pending"] += pendiente
        fila["buckets"][receivable.aging_bucket] += pendiente

    return sorted(
        por_financiador.values(),
        key=lambda f: f["total_pending"],
        reverse=True,
    )
