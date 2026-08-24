"""
Servicios de presupuesto.

El presupuesto de MauleMed hoy existe como estructura y está vacío: se compara
contra el real cuando alguien lo llena a mano. Estos servicios lo convierten en
un control que corre dentro del flujo de compra.

El ciclo de una compra sobre el presupuesto tiene dos momentos:

    orden aprobada  →  commit_budget    (comprometido)
    factura recibida →  consume_budget  (consumido, libera el compromiso)
    orden anulada    →  release_commitment

Separarlos importa porque entre la autorización y la factura pueden pasar
semanas, y durante ese tiempo el saldo tiene que reflejar que la plata ya está
comprometida. De lo contrario dos compras seguidas ven el mismo saldo libre.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import Budget


ZERO = Decimal("0")


def to_decimal(value):
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Resolución del presupuesto aplicable
# ---------------------------------------------------------------------------

def get_budget_for(
    *,
    legal_entity,
    period_year,
    period_month,
    budget_category=None,
    branch=None,
    cost_center=None,
    product_category=None,
):
    """
    Devuelve el presupuesto que gobierna un gasto, del más específico al más
    general.

    La organización define el presupuesto al nivel que puede: a veces por
    centro de costo, a veces sólo por sociedad. Buscar únicamente la
    coincidencia exacta dejaría sin control todo gasto cuyo centro de costo
    todavía no tiene línea propia, que al principio son casi todos.
    """

    base = Budget.objects.filter(
        legal_entity=legal_entity,
        period_year=period_year,
        period_month=period_month,
    )

    if budget_category is not None:
        base = base.filter(budget_category=budget_category)

    # De más específico a más general. El primero que exista, manda.
    candidates = [
        {"branch": branch, "cost_center": cost_center, "category": product_category},
        {"branch": branch, "cost_center": cost_center, "category": None},
        {"branch": branch, "cost_center": None, "category": None},
        {"branch": None, "cost_center": None, "category": None},
    ]

    seen = []
    for scope in candidates:
        if scope in seen:
            continue
        seen.append(scope)

        budget = base.filter(**scope).first()
        if budget is not None:
            return budget

    return None


def budget_snapshot(budget):
    """Forma serializable del estado de un presupuesto, para la API y la UI."""

    if budget is None:
        return {
            "found": False,
            "budget_uuid": None,
            "budget_amount": ZERO,
            "committed_amount": ZERO,
            "consumed_amount": ZERO,
            "available_amount": ZERO,
        }

    return {
        "found": True,
        "budget_uuid": str(budget.uuid),
        "budget_category": (
            budget.budget_category.name if budget.budget_category else None
        ),
        "cost_center": budget.cost_center.name if budget.cost_center else None,
        "period": f"{budget.period_month:02d}/{budget.period_year}",
        "budget_amount": budget.budget_amount,
        "committed_amount": budget.committed_amount,
        "consumed_amount": budget.consumed_amount,
        "available_amount": budget.available_amount,
    }


# ---------------------------------------------------------------------------
# Movimientos sobre el presupuesto
# ---------------------------------------------------------------------------

def _apply(budget, **increments):
    """
    Aplica incrementos con F() y recarga la instancia.

    Se usa F() y no lectura-modificación-escritura porque dos aprobaciones
    simultáneas sobre el mismo centro de costo perderían una de las dos.
    """

    if budget is None:
        return None

    with transaction.atomic():
        Budget.objects.filter(pk=budget.pk).update(
            **{
                field: F(field) + to_decimal(amount)
                for field, amount in increments.items()
            }
        )

    budget.refresh_from_db()
    return budget


def commit_budget(*, budget, amount):
    """Compromete un monto: la compra está autorizada pero aún sin factura."""
    return _apply(budget, committed_amount=to_decimal(amount))


def release_commitment(*, budget, amount):
    """Libera un compromiso, sin dejar el acumulado bajo cero."""

    if budget is None:
        return None

    amount = to_decimal(amount)
    # El compromiso puede haber sido liberado ya por otra vía (una factura
    # parcial, una anulación repetida). Nunca bajar de cero.
    amount = min(amount, budget.committed_amount)

    if amount <= ZERO:
        return budget

    return _apply(budget, committed_amount=-amount)


def consume_budget(*, budget, amount, release_committed=True):
    """
    Registra el gasto efectivo. Por defecto libera el compromiso equivalente,
    porque la factura es la materialización de la orden ya comprometida.
    """

    if budget is None:
        return None

    amount = to_decimal(amount)

    if release_committed:
        release_commitment(budget=budget, amount=amount)

    return _apply(budget, consumed_amount=amount)


# ---------------------------------------------------------------------------
# Evaluación previa: cuánto cuesta y cuánto queda
# ---------------------------------------------------------------------------

def get_reference_price(product):
    """
    Precio de referencia de un producto, promediando el último precio conocido
    de los proveedores activos que lo venden.

    Una solicitud de insumos no tiene proveedor todavía, así que no hay precio
    real: esto es una estimación declarada como tal. Devuelve None cuando no
    hay ningún precio, para poder distinguir "vale cero" de "no se sabe".
    """

    from apps.suppliers.models import SupplierProduct

    prices = [
        to_decimal(value)
        for value in SupplierProduct.objects.filter(
            product=product,
            is_active=True,
            last_price__isnull=False,
        ).values_list("last_price", flat=True)
    ]

    if not prices:
        return None

    return sum(prices) / len(prices)


def estimate_supply_request_amount(supply_request):
    """
    Estima el monto de una solicitud y dice con qué cobertura lo estima.

    Devuelve (monto, ítems_con_precio, ítems_totales). La UI necesita las tres
    cosas: un total sin decir que se calculó sobre la mitad de los ítems es un
    número que engaña.
    """

    total = ZERO
    priced = 0
    items = list(supply_request.items.select_related("product"))

    for item in items:
        quantity = item.approved_quantity
        if quantity is None or quantity <= ZERO:
            quantity = item.requested_quantity

        price = get_reference_price(item.product)
        if price is None:
            continue

        priced += 1
        total += to_decimal(quantity) * to_decimal(price)

    return total, priced, len(items)


def budget_status_for_supply_request(supply_request):
    """Estado presupuestario de una solicitud, para el endpoint budget-check."""

    estimated, priced_items, total_items = estimate_supply_request_amount(
        supply_request
    )

    budget = get_budget_for(
        legal_entity=supply_request.legal_entity,
        branch=supply_request.branch,
        cost_center=supply_request.cost_center,
        period_year=supply_request.period_year,
        period_month=supply_request.period_month,
    )

    snapshot = budget_snapshot(budget)
    available = snapshot["available_amount"]

    return {
        **snapshot,
        "estimated_amount": estimated,
        "priced_items": priced_items,
        "total_items": total_items,
        "estimate_is_partial": priced_items < total_items,
        "within_budget": bool(budget) and estimated <= available,
        "shortfall_amount": (
            max(ZERO, estimated - available) if budget else ZERO
        ),
    }


def budget_status_for_purchase_order(purchase_order):
    """Estado presupuestario de una orden, con su monto real."""

    budget = get_budget_for(
        legal_entity=purchase_order.legal_entity,
        branch=purchase_order.branch,
        cost_center=purchase_order.cost_center,
        period_year=purchase_order.created_at.year,
        period_month=purchase_order.created_at.month,
    )

    snapshot = budget_snapshot(budget)
    amount = to_decimal(purchase_order.total_amount)
    available = snapshot["available_amount"]

    return {
        **snapshot,
        "order_amount": amount,
        "within_budget": bool(budget) and amount <= available,
        "shortfall_amount": max(ZERO, amount - available) if budget else ZERO,
    }


# ---------------------------------------------------------------------------
# Ciclo completo de una orden de compra sobre el presupuesto
# ---------------------------------------------------------------------------

def budget_for_purchase_order(purchase_order):
    """El presupuesto que gobierna una orden, con su período de creación."""

    return get_budget_for(
        legal_entity=purchase_order.legal_entity,
        branch=purchase_order.branch,
        cost_center=purchase_order.cost_center,
        period_year=purchase_order.created_at.year,
        period_month=purchase_order.created_at.month,
    )


def commit_purchase_order(purchase_order):
    """
    Compromete el total de la orden y lo anota en la propia orden.

    Se anota en la orden —y no sólo en el presupuesto— para que liberar sea
    exacto: se libera lo que esta orden comprometió, ni más ni menos.
    """

    amount = to_decimal(purchase_order.total_amount)
    if amount <= ZERO:
        return None

    budget = budget_for_purchase_order(purchase_order)
    commit_budget(budget=budget, amount=amount)

    purchase_order.budget_committed_amount = amount
    purchase_order.save(update_fields=["budget_committed_amount", "updated_at"])

    return budget


def release_purchase_order_commitment(purchase_order, amount=None):
    """
    Libera el compromiso pendiente de una orden. Sin `amount`, libera todo lo
    que le queda. Es idempotente: llamarla dos veces no libera dos veces.
    """

    outstanding = to_decimal(purchase_order.budget_committed_amount)
    if outstanding <= ZERO:
        return None

    amount = outstanding if amount is None else min(to_decimal(amount), outstanding)
    if amount <= ZERO:
        return None

    budget = budget_for_purchase_order(purchase_order)
    release_commitment(budget=budget, amount=amount)

    purchase_order.budget_committed_amount = outstanding - amount
    purchase_order.save(update_fields=["budget_committed_amount", "updated_at"])

    return budget


def register_supplier_invoice(supplier_invoice):
    """
    Imputa una factura de proveedor al presupuesto.

    Si la factura viene de una orden, libera el compromiso equivalente: la
    factura es la materialización de lo que ya estaba reservado. Si no viene de
    una orden —la compra web o por correo que el informe describe— consume
    directamente, sin compromiso previo que liberar.
    """

    amount = to_decimal(supplier_invoice.total_amount)
    if amount <= ZERO:
        return None

    purchase_order = supplier_invoice.purchase_order

    # El compromiso se libera siempre contra la orden concreta, que es más
    # preciso que liberarlo contra el presupuesto.
    if purchase_order is not None:
        release_purchase_order_commitment(purchase_order, amount=amount)

    items = list(
        supplier_invoice.items.select_related("cost_center", "budget_category")
    )

    # Con detalle, cada ítem se imputa a su propio centro de costo. Sin él, la
    # factura entera va al centro de costo de la cabecera — que es lo que hoy
    # obliga a filtrar a mano cuando una factura mezcla dos centros.
    if items:
        _consume_by_item(supplier_invoice, items)
        return None

    return _consume_invoice_header(supplier_invoice, amount)


def _invoice_period(supplier_invoice):
    fecha = supplier_invoice.issue_date or supplier_invoice.created_at
    return fecha.year, fecha.month


def _consume_invoice_header(supplier_invoice, amount):
    period_year, period_month = _invoice_period(supplier_invoice)

    budget = get_budget_for(
        legal_entity=supplier_invoice.legal_entity,
        branch=supplier_invoice.branch,
        cost_center=supplier_invoice.cost_center,
        period_year=period_year,
        period_month=period_month,
    )

    consume_budget(budget=budget, amount=amount, release_committed=False)
    return budget


def _consume_by_item(supplier_invoice, items):
    """Imputa cada ítem a su centro de costo y a su línea presupuestaria."""

    period_year, period_month = _invoice_period(supplier_invoice)

    for item in items:
        item_amount = to_decimal(item.total_amount)
        if item_amount <= ZERO:
            continue

        budget = get_budget_for(
            legal_entity=supplier_invoice.legal_entity,
            branch=supplier_invoice.branch,
            cost_center=item.cost_center or supplier_invoice.cost_center,
            budget_category=item.budget_category,
            product_category=item.category,
            period_year=period_year,
            period_month=period_month,
        )

        consume_budget(budget=budget, amount=item_amount, release_committed=False)


def build_items_from_purchase_order(supplier_invoice):
    """
    Precarga el detalle de la factura desde la orden que la origina.

    Se hereda el centro de costo de la orden como punto de partida: quien
    registra la factura corrige los ítems que van a otro centro, en vez de
    tipear el detalle completo.
    """

    from .models import SupplierInvoiceItem

    purchase_order = supplier_invoice.purchase_order

    if purchase_order is None or supplier_invoice.items.exists():
        return []

    creados = []

    for order_item in purchase_order.items.select_related("product"):
        creados.append(
            SupplierInvoiceItem.objects.create(
                supplier_invoice=supplier_invoice,
                product=order_item.product,
                cost_center=purchase_order.cost_center,
                quantity=order_item.quantity,
                unit_price=order_item.unit_price,
                tax_amount=order_item.tax_amount,
            )
        )

    return creados


def invoice_items_match_total(supplier_invoice, tolerance=Decimal("1")):
    """
    (cuadra, suma_de_items, diferencia).

    La tolerancia por defecto es de un peso: los totales vienen redondeados
    desde el documento del proveedor y exigir cuadratura exacta rechazaría
    facturas correctas.
    """

    total_items = sum(
        (to_decimal(item.total_amount) for item in supplier_invoice.items.all()),
        ZERO,
    )
    diferencia = total_items - to_decimal(supplier_invoice.total_amount)

    return abs(diferencia) <= tolerance, total_items, diferencia
