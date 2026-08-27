import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from apps.common.statuses import SupplyRequestStatus, PurchaseOrderStatus, PurchaseReceiptStatus
from apps.common.business_validations import validate_has_items, validate_status_in, validate_status_not_in, validate_positive_quantity
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.services import increase_stock
from apps.inventory.models import InventoryStock
from apps.products.models import BranchProduct
from apps.suppliers.models import SupplierProduct
from apps.common.scopes import apply_branch_scope
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
)


logger = logging.getLogger(__name__)


def to_decimal(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _get_status_value(model, candidates, fallback=None):
    """
    Busca una constante de estado existente en el modelo.
    Sirve para evitar romper si el nombre exacto de la constante cambia.
    """
    for candidate in candidates:
        if hasattr(model, candidate):
            return getattr(model, candidate)

    return fallback


def _set_if_hasattr(instance, field_name, value):
    if hasattr(instance, field_name):
        setattr(instance, field_name, value)
        return True
    return False


@transaction.atomic
def process_purchase_receipt(*, purchase_receipt, user):
    """
    Procesa una recepción de compra y actualiza inventario.

    Reglas:
    - La recepción debe tener bodega.
    - La recepción debe tener ítems.
    - Cada ítem debe tener cantidad aceptada o recibida mayor a 0.
    - Aumenta stock por producto.
    - Crea lote si el producto lo requiere o si viene lote/vencimiento.
    - Actualiza cantidades recibidas en PurchaseOrderItem si existe relación por producto.
    """

    validate_status_not_in(
        purchase_receipt,
        PurchaseReceiptStatus.FINAL_STATUSES,
        message="Esta recepción no puede ser procesada en su estado actual.",
    )

    validate_has_items(
        purchase_receipt,
        related_name="items",
        message="No se puede procesar una recepción sin ítems.",
    )

    if purchase_receipt.purchase_order:
        validate_status_not_in(
            purchase_receipt.purchase_order,
            PurchaseOrderStatus.FINAL_STATUSES,
            message="No se puede procesar una recepción asociada a una OC finalizada o cancelada.",
        )

    if not purchase_receipt.warehouse:
        raise ValidationError("La recepción debe tener una bodega asociada.")

    if not purchase_receipt.items.exists():
        raise ValidationError("No se puede procesar una recepción sin ítems.")

    purchase_order = purchase_receipt.purchase_order
    warehouse = purchase_receipt.warehouse

    logger.info(
        f"Procesando recepción uuid={purchase_receipt.uuid} purchase_order={purchase_order}"
    )

    processed_items = []

    for receipt_item in purchase_receipt.items.select_related("product").all():
        product = receipt_item.product

        accepted_quantity = to_decimal(
            getattr(receipt_item, "accepted_quantity", None)
            or getattr(receipt_item, "received_quantity", None)
        )

        rejected_quantity = to_decimal(getattr(receipt_item, "rejected_quantity", 0))

        if accepted_quantity <= 0:
            logger.info(
                f"Ítem recepción omitido por cantidad aceptada 0 product={product}"
            )
            continue

        if rejected_quantity < 0:
            raise ValidationError("La cantidad rechazada no puede ser negativa.")

        lot_number = getattr(receipt_item, "lot_number", None)
        expiration_date = getattr(receipt_item, "expiration_date", None)

        result = increase_stock(
            warehouse=warehouse,
            product=product,
            quantity=accepted_quantity,
            lot_number=lot_number,
            expiration_date=expiration_date,
            supplier=purchase_order.supplier if purchase_order else None,
            reason=f"Recepción de compra {purchase_order.order_number if purchase_order else ''}",
            reference_type="PURCHASE_RECEIPT",
            reference_uuid=purchase_receipt.uuid,
            created_by_uuid=user.profile.uuid if hasattr(user, "profile") else None,
        )

        processed_items.append(
            {
                "receipt_item_uuid": str(receipt_item.uuid),
                "product_uuid": str(product.uuid),
                "accepted_quantity": str(accepted_quantity),
                "stock_uuid": str(result["stock"].uuid),
                "lot_uuid": str(result["lot"].uuid) if result["lot"] else None,
                "movement_uuid": str(result["movement"].uuid),
            }
        )

        if purchase_order:
            order_item = purchase_order.items.filter(product=product).first()

            if order_item:
                current_received = to_decimal(getattr(order_item, "received_quantity", 0))
                order_item.received_quantity = current_received + accepted_quantity
                order_item.save(update_fields=["received_quantity", "updated_at"])

    if not processed_items:
        raise ValidationError("No hay ítems con cantidad aceptada para procesar.")

    processed_status = _get_status_value(
        PurchaseReceipt,
        ["STATUS_PROCESSED", "STATUS_COMPLETED", "STATUS_RECEIVED"],
        fallback=getattr(purchase_receipt, "status", None),
    )

    update_fields = ["updated_at"]

    if processed_status:
        purchase_receipt.status = processed_status
        update_fields.append("status")

    if hasattr(purchase_receipt, "processed_at"):
        purchase_receipt.processed_at = timezone.now()
        update_fields.append("processed_at")

    if hasattr(purchase_receipt, "received_at") and not purchase_receipt.received_at:
        purchase_receipt.received_at = timezone.now()
        update_fields.append("received_at")

    purchase_receipt.save(update_fields=update_fields)

    if purchase_order:
        _update_purchase_order_status_by_receipts(purchase_order)

    logger.info(
        f"Recepción procesada correctamente uuid={purchase_receipt.uuid} items={len(processed_items)}"
    )

    return {
        "purchase_receipt": purchase_receipt,
        "purchase_order": purchase_order,
        "processed_items": processed_items,
    }


def _update_purchase_order_status_by_receipts(purchase_order):
    """
    Actualiza estado de la OC según cantidades recibidas.
    """

    total_items = purchase_order.items.count()

    if total_items == 0:
        return purchase_order

    fully_received = True
    partially_received = False

    for item in purchase_order.items.all():
        ordered_quantity = to_decimal(getattr(item, "quantity", 0))
        received_quantity = to_decimal(getattr(item, "received_quantity", 0))

        if received_quantity > 0:
            partially_received = True

        if received_quantity < ordered_quantity:
            fully_received = False

    if fully_received:
        new_status = _get_status_value(
            PurchaseOrder,
            ["STATUS_RECEIVED", "STATUS_COMPLETED", "STATUS_CLOSED"],
            fallback=getattr(purchase_order, "status", None),
        )
    elif partially_received:
        new_status = _get_status_value(
            PurchaseOrder,
            ["STATUS_PARTIALLY_RECEIVED", "STATUS_PARTIAL_RECEIVED"],
            fallback=getattr(purchase_order, "status", None),
        )
    else:
        new_status = getattr(purchase_order, "status", None)

    if new_status:
        purchase_order.status = new_status

    if fully_received and hasattr(purchase_order, "received_at"):
        purchase_order.received_at = timezone.now()
        purchase_order.save(update_fields=["status", "received_at", "updated_at"])
    else:
        purchase_order.save(update_fields=["status", "updated_at"])

    logger.info(
        f"Estado OC actualizado order={purchase_order} status={purchase_order.status}"
    )

    return purchase_order


def generate_purchase_order_number():
    """
    Genera un número único de OC con formato OC-YYYYMMDD-NNNN.
    Usa select_for_update en una transacción para evitar duplicados en concurrencia.
    """
    from django.db import transaction as db_transaction

    today = timezone.now().date()
    prefix = today.strftime("OC-%Y%m%d")

    with db_transaction.atomic():
        # Bloquea las filas del día para contar de forma segura
        count = (
            PurchaseOrder.objects.select_for_update()
            .filter(order_number__startswith=prefix)
            .count()
        ) + 1

    return f"{prefix}-{count:04d}"


def get_model_status(model, candidates, fallback):
    for candidate in candidates:
        if hasattr(model, candidate):
            return getattr(model, candidate)

    return fallback


def get_supplier_product_price(*, supplier, product):
    try:
        supplier_product = supplier.supplier_products.filter(
            product=product,
            is_active=True,
        ).first()

        if supplier_product and supplier_product.last_price is not None:
            return to_decimal(supplier_product.last_price)

    except Exception:
        pass

    return Decimal("0")


@transaction.atomic
def convert_supply_request_to_purchase_order(
    *,
    supply_request,
    supplier,
    user,
    expected_delivery_date=None,
    notes=None,
    tax_rate=Decimal("0.19"),
):
    """
    Convierte una solicitud de insumos en una orden de compra.

    Usa:
    - approved_quantity si existe y es mayor a 0
    - requested_quantity como respaldo

    El precio unitario se intenta obtener desde SupplierProduct.last_price.
    Si no existe precio, se crea con 0 para que abastecimiento lo complete.
    """

    validate_has_items(
        supply_request,
        related_name="items",
        message="No se puede convertir una solicitud sin ítems.",
    )

    validate_status_not_in(
        supply_request,
        SupplyRequestStatus.FINAL_STATUSES,
        message="No se puede convertir una solicitud finalizada, rechazada, cerrada o ya convertida.",
    )

    validate_status_in(
        supply_request,
        SupplyRequestStatus.VALID_FOR_CONVERSION,
        message="Solo se pueden convertir solicitudes aprobadas en orden de compra.",
    )

    existing_purchase_order = PurchaseOrder.objects.filter(
        supply_request=supply_request
    ).exclude(
        status__in=[
            PurchaseOrderStatus.CANCELLED,
        ]
    ).first()

    if existing_purchase_order:
        raise ValidationError(
            f"La solicitud ya tiene una orden de compra asociada: {existing_purchase_order.order_number}."
        )

    items_to_convert = []

    for item in supply_request.items.select_related("product").all():
        quantity = to_decimal(
            getattr(item, "approved_quantity", None)
            or getattr(item, "requested_quantity", None)
        )

        if quantity <= 0:
            continue

        unit_price = get_supplier_product_price(
            supplier=supplier,
            product=item.product,
        )

        total_amount = quantity * unit_price

        items_to_convert.append(
            {
                "source_item": item,
                "product": item.product,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": total_amount,
            }
        )

    if not items_to_convert:
        raise ValidationError("No hay ítems con cantidad válida para convertir.")

    subtotal_amount = sum(item["total_amount"] for item in items_to_convert)
    tax_amount = (subtotal_amount * to_decimal(tax_rate)).quantize(Decimal("0.01"))
    total_amount = (subtotal_amount + tax_amount).quantize(Decimal("0.01"))

    purchase_order = PurchaseOrder.objects.create(
        supplier=supplier,
        legal_entity=supply_request.legal_entity,
        branch=supply_request.branch,
        cost_center=supply_request.cost_center,
        supply_request=supply_request,
        order_number=generate_purchase_order_number(),
        status=PurchaseOrderStatus.DRAFT,
        requested_by=user,
        expected_delivery_date=expected_delivery_date,
        notes=notes,
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
    )

    created_items = []

    for item_data in items_to_convert:
        purchase_order_item = purchase_order.items.create(
            product=item_data["product"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            total_amount=item_data["total_amount"],
            received_quantity=Decimal("0"),
        )

        created_items.append(purchase_order_item)

    supply_request.status = SupplyRequestStatus.CONVERTED_TO_PURCHASE_ORDER
    supply_request.save(update_fields=["status", "updated_at"])

    logger.info(
        f"Solicitud convertida a OC supply_request={supply_request.uuid} purchase_order={purchase_order.uuid}"
    )

    return {
        "supply_request": supply_request,
        "purchase_order": purchase_order,
        "purchase_order_items": created_items,
    }


# ---------------------------------------------------------------------------
# C2 · Umbrales de aprobación por monto
# ---------------------------------------------------------------------------

def get_required_role(purchase_order):
    """
    Rol que la política exige para aprobar esta orden, o None si ninguna regla
    la gobierna.

    Cuando varias reglas calzan gana la más específica: primero la que nombra
    la razón social y el tipo de compra, después la que nombra una de las dos,
    y por último la global. Sin ese orden, una regla global permisiva anularía
    en silencio a una regla estricta escrita para un caso puntual.
    """

    from .models import ApprovalRule

    amount = to_decimal(purchase_order.total_amount)

    matching = [
        rule
        for rule in ApprovalRule.objects.filter(is_active=True).select_related(
            "required_role", "legal_entity"
        )
        if rule.matches(
            amount=amount,
            purchase_type=purchase_order.purchase_type,
            legal_entity=purchase_order.legal_entity,
        )
    ]

    if not matching:
        return None

    def specificity(rule):
        return (
            1 if rule.legal_entity_id else 0,
            1 if rule.purchase_type else 0,
            rule.amount_from,
        )

    matching.sort(key=specificity, reverse=True)
    return matching[0].required_role


def user_can_approve(user, purchase_order):
    """
    (permitido, rol_requerido).

    Sin regla aplicable, permitido: la política se va escribiendo por tramos y
    lo que todavía no está normado no puede quedar bloqueado.
    """

    required_role = get_required_role(purchase_order)

    if required_role is None:
        return True, None

    if getattr(user, "is_superuser", False):
        return True, required_role

    has_role = user.role_assignments.filter(
        role=required_role,
        is_active=True,
    ).exists()

    return has_role, required_role


# ---------------------------------------------------------------------------
# Sugerencias de compra
# ---------------------------------------------------------------------------

PURCHASE_PRIORITY_CRITICAL = "CRITICAL"
PURCHASE_PRIORITY_HIGH = "HIGH"


def _purchase_priority(*, available_stock, critical_stock):
    """
    Determina la prioridad de reposición.

    CRITICAL:
        stock disponible <= critical_stock, siempre que el umbral crítico
        configurado sea mayor que cero.

    HIGH:
        el producto está bajo su mínimo, pero aún no alcanza el nivel crítico.
    """
    available_stock = to_decimal(available_stock)
    critical_stock = to_decimal(critical_stock)

    if critical_stock > 0 and available_stock <= critical_stock:
        return PURCHASE_PRIORITY_CRITICAL

    return PURCHASE_PRIORITY_HIGH


def _supplier_purchase_options(*, supplier_products, suggested_quantity):
    """
    Construye y ordena las alternativas de proveedor.

    La selección del proveedor se mantiene determinística:
    - primero proveedores con precio vigente/cargado;
    - luego menor precio;
    - finalmente nombre para obtener un orden estable.

    No se utiliza IA para inventar precios ni cantidades.
    """
    suggested_quantity = to_decimal(suggested_quantity)
    options = []

    for supplier_product in supplier_products:
        supplier = supplier_product.supplier
        unit_price = (
            to_decimal(supplier_product.last_price)
            if supplier_product.last_price is not None
            else None
        )

        minimum_purchase = to_decimal(
            supplier_product.min_purchase_quantity
        )

        minimum_purchase_applies = (
            minimum_purchase > 0
            and minimum_purchase > suggested_quantity
        )

        estimated_total = (
            unit_price * suggested_quantity
            if unit_price is not None
            else None
        )

        options.append(
            {
                "supplier_product_uuid": str(
                    supplier_product.uuid
                ),
                "supplier_uuid": str(supplier.uuid),
                "supplier_name": supplier.name,
                "supplier_rut": supplier.rut,
                "supplier_sku": supplier_product.supplier_sku,
                "currency": supplier_product.currency,
                "unit_price": unit_price,
                "estimated_total": estimated_total,
                "min_purchase_quantity": minimum_purchase,
                "minimum_purchase_applies": minimum_purchase_applies,
                "requires_purchase_order": (
                    supplier_product.requires_purchase_order
                ),
                "allows_credit": supplier_product.allows_credit,
                "allows_cash_purchase": (
                    supplier_product.allows_cash_purchase
                ),
                "delivery_days": supplier.delivery_days,
                "payment_terms_days": supplier.payment_terms_days,
            }
        )

    options.sort(
        key=lambda option: (
            option["minimum_purchase_applies"],
            option["unit_price"] is None,
            (
                option["unit_price"]
                if option["unit_price"] is not None
                else Decimal("999999999999999999")
            ),
            option["supplier_name"] or "",
        )
    )

    return options


def get_purchase_suggestions(*, user, branch=None):
    """
    Genera sugerencias de reposición para mantener cada producto dentro de los
    márgenes configurados en BranchProduct.

    Regla de reposición:
        available_stock = stock físico - stock reservado

        Si available_stock < min_stock:
            target_stock = max_stock, cuando max_stock > 0
                           min_stock, en caso contrario

            suggested_quantity = target_stock - available_stock

    La consulta respeta el scope de sucursales del usuario.

    ``branch`` puede ser:
    - una instancia de Branch;
    - un UUID;
    - None para considerar todas las sucursales permitidas.

    El servicio NO llama todavía a Gemini. Devuelve información estructurada y
    auditable para que la capa de IA pueda, posteriormente, explicar o priorizar
    las alternativas sin modificar el cálculo de inventario.

    Consultas principales:
    1. BranchProduct dentro del scope del usuario.
    2. Stock agregado por sucursal/producto.
    3. SupplierProduct de todos los productos que necesitan reposición.

    Esto evita hacer consultas de stock o proveedores dentro de loops.
    """
    branch_products_qs = (
        BranchProduct.objects.filter(
            is_active=True,
            product__is_active=True,
        )
        .select_related(
            "branch",
            "product",
            "product__category",
            "product__unit",
            "cost_center",
        )
        .order_by(
            "branch__name",
            "product__name",
        )
    )

    branch_products_qs = apply_branch_scope(
        branch_products_qs,
        user,
        branch_field="branch",
    )

    if branch is not None:
        if hasattr(branch, "pk"):
            branch_products_qs = branch_products_qs.filter(
                branch=branch
            )
        else:
            branch_products_qs = branch_products_qs.filter(
                branch__uuid=branch
            )

    branch_products = list(branch_products_qs)

    if not branch_products:
        return {
            "summary": {
                "products_to_buy": 0,
                "critical_products": 0,
                "high_priority_products": 0,
                "estimated_total": Decimal("0"),
            },
            "suggestions": [],
        }

    branch_ids = {
        item.branch_id
        for item in branch_products
    }
    product_ids = {
        item.product_id
        for item in branch_products
    }

    # Una sola consulta para sumar stock de todas las bodegas de la sucursal.
    stock_rows = (
        InventoryStock.objects.filter(
            warehouse__branch_id__in=branch_ids,
            product_id__in=product_ids,
        )
        .values(
            "warehouse__branch_id",
            "product_id",
        )
        .annotate(
            total_quantity=Sum("quantity"),
            total_reserved_quantity=Sum("reserved_quantity"),
        )
    )

    stock_by_branch_product = {
        (
            row["warehouse__branch_id"],
            row["product_id"],
        ): {
            "quantity": to_decimal(
                row["total_quantity"]
            ),
            "reserved_quantity": to_decimal(
                row["total_reserved_quantity"]
            ),
        }
        for row in stock_rows
    }

    candidates = []

    for branch_product in branch_products:
        stock = stock_by_branch_product.get(
            (
                branch_product.branch_id,
                branch_product.product_id,
            ),
            {
                "quantity": Decimal("0"),
                "reserved_quantity": Decimal("0"),
            },
        )

        quantity = to_decimal(stock["quantity"])
        reserved_quantity = to_decimal(
            stock["reserved_quantity"]
        )
        available_stock = quantity - reserved_quantity

        min_stock = to_decimal(branch_product.min_stock)
        max_stock = to_decimal(branch_product.max_stock)
        critical_stock = to_decimal(
            branch_product.critical_stock
        )

        # Un mínimo igual a cero significa que no existe una regla de reposición
        # automática útil para este producto.
        if min_stock <= 0:
            continue

        if available_stock >= min_stock:
            continue

        target_stock = (
            max_stock
            if max_stock > 0
            else min_stock
        )

        # Una configuración inconsistente de max < min no debe recomendar una
        # cantidad negativa o dejar el producto bajo el mínimo.
        if target_stock < min_stock:
            target_stock = min_stock

        suggested_quantity = (
            target_stock - available_stock
        )

        if suggested_quantity <= 0:
            continue

        candidates.append(
            {
                "branch_product": branch_product,
                "quantity": quantity,
                "reserved_quantity": reserved_quantity,
                "available_stock": available_stock,
                "min_stock": min_stock,
                "max_stock": max_stock,
                "critical_stock": critical_stock,
                "target_stock": target_stock,
                "suggested_quantity": suggested_quantity,
                "priority": _purchase_priority(
                    available_stock=available_stock,
                    critical_stock=critical_stock,
                ),
            }
        )

    if not candidates:
        return {
            "summary": {
                "products_to_buy": 0,
                "critical_products": 0,
                "high_priority_products": 0,
                "estimated_total": Decimal("0"),
            },
            "suggestions": [],
        }

    candidate_product_ids = {
        candidate["branch_product"].product_id
        for candidate in candidates
    }

    # Una sola consulta para todas las alternativas de proveedor.
    supplier_products = (
        SupplierProduct.objects.filter(
            product_id__in=candidate_product_ids,
            is_active=True,
            supplier__is_active=True,
        )
        .select_related(
            "supplier",
            "product",
        )
        .order_by(
            "product_id",
            "supplier__name",
        )
    )

    suppliers_by_product = {}

    for supplier_product in supplier_products:
        suppliers_by_product.setdefault(
            supplier_product.product_id,
            [],
        ).append(supplier_product)

    suggestions = []
    estimated_total = Decimal("0")
    critical_products = 0
    high_priority_products = 0

    priority_order = {
        PURCHASE_PRIORITY_CRITICAL: 0,
        PURCHASE_PRIORITY_HIGH: 1,
    }

    for candidate in candidates:
        branch_product = candidate["branch_product"]
        product = branch_product.product

        supplier_options = _supplier_purchase_options(
            supplier_products=suppliers_by_product.get(
                product.id,
                [],
            ),
            suggested_quantity=candidate[
                "suggested_quantity"
            ],
        )

        recommended_supplier = (
            supplier_options[0]
            if supplier_options
            else None
        )

        if (
            recommended_supplier is not None
            and recommended_supplier["estimated_total"] is not None
        ):
            estimated_total += recommended_supplier[
                "estimated_total"
            ]

        if candidate["priority"] == PURCHASE_PRIORITY_CRITICAL:
            critical_products += 1
        else:
            high_priority_products += 1

        suggestions.append(
            {
                "branch_uuid": str(
                    branch_product.branch.uuid
                ),
                "branch_name": branch_product.branch.name,
                "product_uuid": str(product.uuid),
                "product_name": product.name,
                "product_internal_code": (
                    product.internal_code
                ),
                "product_sku": product.sku,
                "category": (
                    product.category.name
                    if product.category_id
                    else None
                ),
                "unit": (
                    product.unit.code
                    if product.unit_id
                    else None
                ),
                "quality_rating": to_decimal(
                    product.quality_rating
                ),
                "cost_center_uuid": (
                    str(branch_product.cost_center.uuid)
                    if branch_product.cost_center_id
                    else None
                ),
                "stock": {
                    "quantity": candidate["quantity"],
                    "reserved_quantity": candidate[
                        "reserved_quantity"
                    ],
                    "available_quantity": candidate[
                        "available_stock"
                    ],
                    "critical_stock": candidate[
                        "critical_stock"
                    ],
                    "min_stock": candidate["min_stock"],
                    "max_stock": candidate["max_stock"],
                    "target_stock": candidate[
                        "target_stock"
                    ],
                },
                "suggested_quantity": candidate[
                    "suggested_quantity"
                ],
                "priority": candidate["priority"],
                "recommended_supplier": recommended_supplier,
                "supplier_options": supplier_options,
            }
        )

    suggestions.sort(
        key=lambda suggestion: (
            priority_order.get(
                suggestion["priority"],
                99,
            ),
            -suggestion["quality_rating"],
            suggestion["product_name"] or "",
        )
    )

    return {
        "summary": {
            "products_to_buy": len(suggestions),
            "critical_products": critical_products,
            "high_priority_products": high_priority_products,
            "estimated_total": estimated_total,
        },
        "suggestions": suggestions,
    }


def _normalize_tax_rate(value):
    """
    Normaliza la tasa de impuesto.

    Acepta:
    - 0.19 -> 19 %
    - 19   -> 19 %
    """
    rate = to_decimal(value)

    if rate < 0:
        raise ValidationError(
            "La tasa de impuesto no puede ser negativa."
        )

    if rate > 1:
        rate = rate / Decimal("100")

    return rate


@transaction.atomic
def create_purchase_orders_from_suggestions(
    *,
    user,
    selected_items,
    tax_rate=Decimal("0.19"),
    notes=None,
):
    """
    Crea órdenes de compra BORRADOR desde sugerencias seleccionadas.

    Cada elemento de ``selected_items`` debe contener:

        {
            "branch_uuid": "...",
            "product_uuid": "...",

            # Opcional. Si no viene, usa el proveedor recomendado.
            "supplier_product_uuid": "...",

            # Opcional. Si no viene, usa suggested_quantity.
            "quantity": "10"
        }

    Seguridad / consistencia:
    - Las sugerencias se recalculan en backend antes de crear.
    - Se respeta el scope de sucursales del usuario.
    - El producto debe seguir bajo su stock mínimo.
    - El SupplierProduct debe estar activo.
    - El proveedor debe estar activo.
    - El SupplierProduct debe corresponder al producto.
    - Debe existir precio.
    - Se respeta la cantidad mínima de compra del proveedor.

    Agrupación:
    Se crea una OC separada por:
    - sucursal;
    - proveedor;
    - centro de costo;
    - moneda.

    La razón social se obtiene desde la sucursal.

    Las órdenes siempre quedan en BORRADOR. Este servicio nunca aprueba,
    compromete presupuesto ni envía automáticamente una orden.
    """
    if not isinstance(selected_items, (list, tuple)):
        raise ValidationError(
            "selected_items debe ser una lista."
        )

    if not selected_items:
        raise ValidationError(
            "Debes seleccionar al menos una sugerencia de compra."
        )

    normalized_tax_rate = _normalize_tax_rate(tax_rate)

    # Recalcular en backend evita confiar en cantidades, stock o proveedores
    # enviados previamente por el frontend.
    current_result = get_purchase_suggestions(
        user=user,
    )

    current_suggestions = current_result.get(
        "suggestions",
        [],
    )

    suggestion_by_key = {
        (
            suggestion["branch_uuid"],
            suggestion["product_uuid"],
        ): suggestion
        for suggestion in current_suggestions
    }

    normalized_items = []
    supplier_product_uuids = set()
    branch_uuids = set()
    product_uuids = set()

    seen_items = set()

    for index, selected in enumerate(
        selected_items,
        start=1,
    ):
        if not isinstance(selected, dict):
            raise ValidationError(
                f"El ítem {index} no tiene un formato válido."
            )

        branch_uuid = str(
            selected.get("branch_uuid") or ""
        ).strip()

        product_uuid = str(
            selected.get("product_uuid") or ""
        ).strip()

        if not branch_uuid:
            raise ValidationError(
                f"El ítem {index} no contiene branch_uuid."
            )

        if not product_uuid:
            raise ValidationError(
                f"El ítem {index} no contiene product_uuid."
            )

        key = (
            branch_uuid,
            product_uuid,
        )

        if key in seen_items:
            raise ValidationError(
                (
                    "El mismo producto no puede aparecer más de una vez "
                    "para la misma sucursal."
                )
            )

        seen_items.add(key)

        suggestion = suggestion_by_key.get(key)

        if suggestion is None:
            raise ValidationError(
                (
                    f"El producto {product_uuid} ya no posee una "
                    f"sugerencia de compra vigente para la sucursal "
                    f"{branch_uuid}. Actualiza las sugerencias."
                )
            )

        quantity_value = selected.get("quantity")

        if quantity_value in (None, ""):
            quantity = to_decimal(
                suggestion["suggested_quantity"]
            )
        else:
            try:
                quantity = to_decimal(quantity_value)
            except Exception as exc:
                raise ValidationError(
                    (
                        f"La cantidad del producto {product_uuid} "
                        f"no es válida."
                    )
                ) from exc

        if quantity <= 0:
            raise ValidationError(
                (
                    f"La cantidad del producto {product_uuid} "
                    f"debe ser mayor que cero."
                )
            )

        supplier_product_uuid = str(
            selected.get("supplier_product_uuid")
            or ""
        ).strip()

        if not supplier_product_uuid:
            recommended_supplier = suggestion.get(
                "recommended_supplier"
            )

            if not recommended_supplier:
                raise ValidationError(
                    (
                        f"El producto {suggestion['product_name']} "
                        f"no tiene un proveedor disponible."
                    )
                )

            supplier_product_uuid = str(
                recommended_supplier[
                    "supplier_product_uuid"
                ]
            )

        valid_supplier_option_uuids = {
            str(option["supplier_product_uuid"])
            for option in suggestion.get(
                "supplier_options",
                [],
            )
        }

        if (
            supplier_product_uuid
            not in valid_supplier_option_uuids
        ):
            raise ValidationError(
                (
                    f"El proveedor seleccionado para "
                    f"{suggestion['product_name']} ya no está "
                    f"disponible para ese producto."
                )
            )

        supplier_product_uuids.add(
            supplier_product_uuid
        )
        branch_uuids.add(branch_uuid)
        product_uuids.add(product_uuid)

        normalized_items.append(
            {
                "branch_uuid": branch_uuid,
                "product_uuid": product_uuid,
                "supplier_product_uuid": (
                    supplier_product_uuid
                ),
                "quantity": quantity,
                "suggestion": suggestion,
            }
        )

    branch_products_qs = (
        BranchProduct.objects.filter(
            branch__uuid__in=branch_uuids,
            product__uuid__in=product_uuids,
            is_active=True,
            product__is_active=True,
        )
        .select_related(
            "branch",
            "branch__legal_entity",
            "product",
            "cost_center",
        )
    )

    branch_products_qs = apply_branch_scope(
        branch_products_qs,
        user,
        branch_field="branch",
    )

    branch_product_by_key = {
        (
            str(branch_product.branch.uuid),
            str(branch_product.product.uuid),
        ): branch_product
        for branch_product in branch_products_qs
    }

    supplier_products = (
        SupplierProduct.objects.filter(
            uuid__in=supplier_product_uuids,
            is_active=True,
            supplier__is_active=True,
        )
        .select_related(
            "supplier",
            "product",
        )
    )

    supplier_product_by_uuid = {
        str(supplier_product.uuid): supplier_product
        for supplier_product in supplier_products
    }

    groups = {}

    for item in normalized_items:
        key = (
            item["branch_uuid"],
            item["product_uuid"],
        )

        branch_product = branch_product_by_key.get(key)

        if branch_product is None:
            raise ValidationError(
                (
                    f"No existe una configuración activa de inventario "
                    f"para el producto {item['product_uuid']} en la "
                    f"sucursal {item['branch_uuid']}."
                )
            )

        supplier_product = (
            supplier_product_by_uuid.get(
                item["supplier_product_uuid"]
            )
        )

        if supplier_product is None:
            raise ValidationError(
                (
                    f"El proveedor seleccionado para "
                    f"{branch_product.product.name} ya no está activo."
                )
            )

        if (
            supplier_product.product_id
            != branch_product.product_id
        ):
            raise ValidationError(
                (
                    f"El proveedor seleccionado no corresponde al "
                    f"producto {branch_product.product.name}."
                )
            )

        if supplier_product.last_price is None:
            raise ValidationError(
                (
                    f"El proveedor "
                    f"{supplier_product.supplier.name} no tiene precio "
                    f"cargado para {branch_product.product.name}."
                )
            )

        unit_price = to_decimal(
            supplier_product.last_price
        )

        if unit_price < 0:
            raise ValidationError(
                (
                    f"El precio de {branch_product.product.name} "
                    f"no puede ser negativo."
                )
            )

        quantity = item["quantity"]

        minimum_purchase = to_decimal(
            supplier_product.min_purchase_quantity
        )

        if (
            minimum_purchase > 0
            and quantity < minimum_purchase
        ):
            raise ValidationError(
                (
                    f"{supplier_product.supplier.name} exige una "
                    f"compra mínima de {minimum_purchase} unidades "
                    f"para {branch_product.product.name}. "
                    f"Cantidad seleccionada: {quantity}."
                )
            )

        currency = (
            supplier_product.currency
            or "CLP"
        )

        # Una OC debe representar una combinación coherente de contexto
        # contable/comercial. No mezclamos sucursales, proveedores, centros de
        # costo ni monedas en una misma orden.
        group_key = (
            branch_product.branch_id,
            supplier_product.supplier_id,
            branch_product.cost_center_id,
            currency,
        )

        group = groups.setdefault(
            group_key,
            {
                "branch": branch_product.branch,
                "supplier": supplier_product.supplier,
                "cost_center": branch_product.cost_center,
                "currency": currency,
                "items": [],
            },
        )

        line_subtotal = (
            quantity * unit_price
        ).quantize(
            Decimal("0.01")
        )

        line_tax = (
            line_subtotal * normalized_tax_rate
        ).quantize(
            Decimal("0.01")
        )

        line_total = (
            line_subtotal + line_tax
        ).quantize(
            Decimal("0.01")
        )

        group["items"].append(
            {
                "product": branch_product.product,
                "supplier_product": supplier_product,
                "quantity": quantity,
                "unit_price": unit_price,
                "currency": currency,
                "tax_amount": line_tax,
                "total_amount": line_total,
            }
        )

    if not groups:
        raise ValidationError(
            "No existen sugerencias válidas para crear órdenes."
        )

    created_orders = []
    total_created_items = 0

    for group in groups.values():
        branch = group["branch"]
        supplier = group["supplier"]
        cost_center = group["cost_center"]

        subtotal_amount = sum(
            (
                item["quantity"]
                * item["unit_price"]
            ).quantize(Decimal("0.01"))
            for item in group["items"]
        )

        tax_amount = sum(
            item["tax_amount"]
            for item in group["items"]
        )

        total_amount = (
            subtotal_amount + tax_amount
        ).quantize(
            Decimal("0.01")
        )

        order_notes_parts = [
            (
                "Orden generada desde sugerencias "
                "automáticas de reposición."
            )
        ]

        if notes:
            order_notes_parts.append(str(notes))

        purchase_order = PurchaseOrder.objects.create(
            supplier=supplier,
            legal_entity=branch.legal_entity,
            branch=branch,
            cost_center=cost_center,
            order_number=generate_purchase_order_number(),
            status=PurchaseOrderStatus.DRAFT,
            purchase_type=(
                PurchaseOrder.PURCHASE_TYPE_PURCHASE_ORDER
            ),
            requested_by=user,
            subtotal_amount=subtotal_amount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            notes="\n".join(order_notes_parts),
        )

        purchase_order_items = [
            PurchaseOrderItem(
                purchase_order=purchase_order,
                product=item["product"],
                supplier_product=item[
                    "supplier_product"
                ],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                currency=item["currency"],
                discount_amount=Decimal("0"),
                tax_amount=item["tax_amount"],
                total_amount=item["total_amount"],
                received_quantity=Decimal("0"),
            )
            for item in group["items"]
        ]

        PurchaseOrderItem.objects.bulk_create(
            purchase_order_items
        )

        total_created_items += len(
            purchase_order_items
        )

        created_orders.append(
            purchase_order
        )

        logger.info(
            (
                "OC sugerida creada "
                f"order={purchase_order.order_number} "
                f"supplier={supplier.name} "
                f"branch={branch.name} "
                f"items={len(purchase_order_items)} "
                f"total={total_amount}"
            )
        )

    return {
        "purchase_orders": created_orders,
        "orders_count": len(created_orders),
        "items_count": total_created_items,
    }



# import logging
# from decimal import Decimal

# from django.core.exceptions import ValidationError
# from apps.common.statuses import SupplyRequestStatus, PurchaseOrderStatus, PurchaseReceiptStatus
# from apps.common.business_validations import validate_has_items, validate_status_in, validate_status_not_in, validate_positive_quantity
# from django.db import transaction
# from django.db.models import Sum
# from django.utils import timezone

# from apps.inventory.services import increase_stock
# from apps.inventory.models import InventoryStock
# from apps.products.models import BranchProduct
# from apps.suppliers.models import SupplierProduct
# from apps.common.scopes import apply_branch_scope
# from apps.purchasing.models import PurchaseOrder, PurchaseReceipt


# logger = logging.getLogger(__name__)


# def to_decimal(value):
#     if value is None:
#         return Decimal("0")
#     return Decimal(str(value))


# def _get_status_value(model, candidates, fallback=None):
#     """
#     Busca una constante de estado existente en el modelo.
#     Sirve para evitar romper si el nombre exacto de la constante cambia.
#     """
#     for candidate in candidates:
#         if hasattr(model, candidate):
#             return getattr(model, candidate)

#     return fallback


# def _set_if_hasattr(instance, field_name, value):
#     if hasattr(instance, field_name):
#         setattr(instance, field_name, value)
#         return True
#     return False


# @transaction.atomic
# def process_purchase_receipt(*, purchase_receipt, user):
#     """
#     Procesa una recepción de compra y actualiza inventario.

#     Reglas:
#     - La recepción debe tener bodega.
#     - La recepción debe tener ítems.
#     - Cada ítem debe tener cantidad aceptada o recibida mayor a 0.
#     - Aumenta stock por producto.
#     - Crea lote si el producto lo requiere o si viene lote/vencimiento.
#     - Actualiza cantidades recibidas en PurchaseOrderItem si existe relación por producto.
#     """

#     validate_status_not_in(
#         purchase_receipt,
#         PurchaseReceiptStatus.FINAL_STATUSES,
#         message="Esta recepción no puede ser procesada en su estado actual.",
#     )

#     validate_has_items(
#         purchase_receipt,
#         related_name="items",
#         message="No se puede procesar una recepción sin ítems.",
#     )

#     if purchase_receipt.purchase_order:
#         validate_status_not_in(
#             purchase_receipt.purchase_order,
#             PurchaseOrderStatus.FINAL_STATUSES,
#             message="No se puede procesar una recepción asociada a una OC finalizada o cancelada.",
#         )

#     if not purchase_receipt.warehouse:
#         raise ValidationError("La recepción debe tener una bodega asociada.")

#     if not purchase_receipt.items.exists():
#         raise ValidationError("No se puede procesar una recepción sin ítems.")

#     purchase_order = purchase_receipt.purchase_order
#     warehouse = purchase_receipt.warehouse

#     logger.info(
#         f"Procesando recepción uuid={purchase_receipt.uuid} purchase_order={purchase_order}"
#     )

#     processed_items = []

#     for receipt_item in purchase_receipt.items.select_related("product").all():
#         product = receipt_item.product

#         accepted_quantity = to_decimal(
#             getattr(receipt_item, "accepted_quantity", None)
#             or getattr(receipt_item, "received_quantity", None)
#         )

#         rejected_quantity = to_decimal(getattr(receipt_item, "rejected_quantity", 0))

#         if accepted_quantity <= 0:
#             logger.info(
#                 f"Ítem recepción omitido por cantidad aceptada 0 product={product}"
#             )
#             continue

#         if rejected_quantity < 0:
#             raise ValidationError("La cantidad rechazada no puede ser negativa.")

#         lot_number = getattr(receipt_item, "lot_number", None)
#         expiration_date = getattr(receipt_item, "expiration_date", None)

#         result = increase_stock(
#             warehouse=warehouse,
#             product=product,
#             quantity=accepted_quantity,
#             lot_number=lot_number,
#             expiration_date=expiration_date,
#             supplier=purchase_order.supplier if purchase_order else None,
#             reason=f"Recepción de compra {purchase_order.order_number if purchase_order else ''}",
#             reference_type="PURCHASE_RECEIPT",
#             reference_uuid=purchase_receipt.uuid,
#             created_by_uuid=user.profile.uuid if hasattr(user, "profile") else None,
#         )

#         processed_items.append(
#             {
#                 "receipt_item_uuid": str(receipt_item.uuid),
#                 "product_uuid": str(product.uuid),
#                 "accepted_quantity": str(accepted_quantity),
#                 "stock_uuid": str(result["stock"].uuid),
#                 "lot_uuid": str(result["lot"].uuid) if result["lot"] else None,
#                 "movement_uuid": str(result["movement"].uuid),
#             }
#         )

#         if purchase_order:
#             order_item = purchase_order.items.filter(product=product).first()

#             if order_item:
#                 current_received = to_decimal(getattr(order_item, "received_quantity", 0))
#                 order_item.received_quantity = current_received + accepted_quantity
#                 order_item.save(update_fields=["received_quantity", "updated_at"])

#     if not processed_items:
#         raise ValidationError("No hay ítems con cantidad aceptada para procesar.")

#     processed_status = _get_status_value(
#         PurchaseReceipt,
#         ["STATUS_PROCESSED", "STATUS_COMPLETED", "STATUS_RECEIVED"],
#         fallback=getattr(purchase_receipt, "status", None),
#     )

#     update_fields = ["updated_at"]

#     if processed_status:
#         purchase_receipt.status = processed_status
#         update_fields.append("status")

#     if hasattr(purchase_receipt, "processed_at"):
#         purchase_receipt.processed_at = timezone.now()
#         update_fields.append("processed_at")

#     if hasattr(purchase_receipt, "received_at") and not purchase_receipt.received_at:
#         purchase_receipt.received_at = timezone.now()
#         update_fields.append("received_at")

#     purchase_receipt.save(update_fields=update_fields)

#     if purchase_order:
#         _update_purchase_order_status_by_receipts(purchase_order)

#     logger.info(
#         f"Recepción procesada correctamente uuid={purchase_receipt.uuid} items={len(processed_items)}"
#     )

#     return {
#         "purchase_receipt": purchase_receipt,
#         "purchase_order": purchase_order,
#         "processed_items": processed_items,
#     }


# def _update_purchase_order_status_by_receipts(purchase_order):
#     """
#     Actualiza estado de la OC según cantidades recibidas.
#     """

#     total_items = purchase_order.items.count()

#     if total_items == 0:
#         return purchase_order

#     fully_received = True
#     partially_received = False

#     for item in purchase_order.items.all():
#         ordered_quantity = to_decimal(getattr(item, "quantity", 0))
#         received_quantity = to_decimal(getattr(item, "received_quantity", 0))

#         if received_quantity > 0:
#             partially_received = True

#         if received_quantity < ordered_quantity:
#             fully_received = False

#     if fully_received:
#         new_status = _get_status_value(
#             PurchaseOrder,
#             ["STATUS_RECEIVED", "STATUS_COMPLETED", "STATUS_CLOSED"],
#             fallback=getattr(purchase_order, "status", None),
#         )
#     elif partially_received:
#         new_status = _get_status_value(
#             PurchaseOrder,
#             ["STATUS_PARTIALLY_RECEIVED", "STATUS_PARTIAL_RECEIVED"],
#             fallback=getattr(purchase_order, "status", None),
#         )
#     else:
#         new_status = getattr(purchase_order, "status", None)

#     if new_status:
#         purchase_order.status = new_status

#     if fully_received and hasattr(purchase_order, "received_at"):
#         purchase_order.received_at = timezone.now()
#         purchase_order.save(update_fields=["status", "received_at", "updated_at"])
#     else:
#         purchase_order.save(update_fields=["status", "updated_at"])

#     logger.info(
#         f"Estado OC actualizado order={purchase_order} status={purchase_order.status}"
#     )

#     return purchase_order


# def generate_purchase_order_number():
#     """
#     Genera un número único de OC con formato OC-YYYYMMDD-NNNN.
#     Usa select_for_update en una transacción para evitar duplicados en concurrencia.
#     """
#     from django.db import transaction as db_transaction

#     today = timezone.now().date()
#     prefix = today.strftime("OC-%Y%m%d")

#     with db_transaction.atomic():
#         # Bloquea las filas del día para contar de forma segura
#         count = (
#             PurchaseOrder.objects.select_for_update()
#             .filter(order_number__startswith=prefix)
#             .count()
#         ) + 1

#     return f"{prefix}-{count:04d}"


# def get_model_status(model, candidates, fallback):
#     for candidate in candidates:
#         if hasattr(model, candidate):
#             return getattr(model, candidate)

#     return fallback


# def get_supplier_product_price(*, supplier, product):
#     try:
#         supplier_product = supplier.supplier_products.filter(
#             product=product,
#             is_active=True,
#         ).first()

#         if supplier_product and supplier_product.last_price is not None:
#             return to_decimal(supplier_product.last_price)

#     except Exception:
#         pass

#     return Decimal("0")


# @transaction.atomic
# def convert_supply_request_to_purchase_order(
#     *,
#     supply_request,
#     supplier,
#     user,
#     expected_delivery_date=None,
#     notes=None,
#     tax_rate=Decimal("0.19"),
# ):
#     """
#     Convierte una solicitud de insumos en una orden de compra.

#     Usa:
#     - approved_quantity si existe y es mayor a 0
#     - requested_quantity como respaldo

#     El precio unitario se intenta obtener desde SupplierProduct.last_price.
#     Si no existe precio, se crea con 0 para que abastecimiento lo complete.
#     """

#     validate_has_items(
#         supply_request,
#         related_name="items",
#         message="No se puede convertir una solicitud sin ítems.",
#     )

#     validate_status_not_in(
#         supply_request,
#         SupplyRequestStatus.FINAL_STATUSES,
#         message="No se puede convertir una solicitud finalizada, rechazada, cerrada o ya convertida.",
#     )

#     validate_status_in(
#         supply_request,
#         SupplyRequestStatus.VALID_FOR_CONVERSION,
#         message="Solo se pueden convertir solicitudes aprobadas en orden de compra.",
#     )

#     existing_purchase_order = PurchaseOrder.objects.filter(
#         supply_request=supply_request
#     ).exclude(
#         status__in=[
#             PurchaseOrderStatus.CANCELLED,
#         ]
#     ).first()

#     if existing_purchase_order:
#         raise ValidationError(
#             f"La solicitud ya tiene una orden de compra asociada: {existing_purchase_order.order_number}."
#         )

#     items_to_convert = []

#     for item in supply_request.items.select_related("product").all():
#         quantity = to_decimal(
#             getattr(item, "approved_quantity", None)
#             or getattr(item, "requested_quantity", None)
#         )

#         if quantity <= 0:
#             continue

#         unit_price = get_supplier_product_price(
#             supplier=supplier,
#             product=item.product,
#         )

#         total_amount = quantity * unit_price

#         items_to_convert.append(
#             {
#                 "source_item": item,
#                 "product": item.product,
#                 "quantity": quantity,
#                 "unit_price": unit_price,
#                 "total_amount": total_amount,
#             }
#         )

#     if not items_to_convert:
#         raise ValidationError("No hay ítems con cantidad válida para convertir.")

#     subtotal_amount = sum(item["total_amount"] for item in items_to_convert)
#     tax_amount = (subtotal_amount * to_decimal(tax_rate)).quantize(Decimal("0.01"))
#     total_amount = (subtotal_amount + tax_amount).quantize(Decimal("0.01"))

#     purchase_order = PurchaseOrder.objects.create(
#         supplier=supplier,
#         legal_entity=supply_request.legal_entity,
#         branch=supply_request.branch,
#         cost_center=supply_request.cost_center,
#         supply_request=supply_request,
#         order_number=generate_purchase_order_number(),
#         status=PurchaseOrderStatus.DRAFT,
#         requested_by=user,
#         expected_delivery_date=expected_delivery_date,
#         notes=notes,
#         subtotal_amount=subtotal_amount,
#         tax_amount=tax_amount,
#         total_amount=total_amount,
#     )

#     created_items = []

#     for item_data in items_to_convert:
#         purchase_order_item = purchase_order.items.create(
#             product=item_data["product"],
#             quantity=item_data["quantity"],
#             unit_price=item_data["unit_price"],
#             total_amount=item_data["total_amount"],
#             received_quantity=Decimal("0"),
#         )

#         created_items.append(purchase_order_item)

#     supply_request.status = SupplyRequestStatus.CONVERTED_TO_PURCHASE_ORDER
#     supply_request.save(update_fields=["status", "updated_at"])

#     logger.info(
#         f"Solicitud convertida a OC supply_request={supply_request.uuid} purchase_order={purchase_order.uuid}"
#     )

#     return {
#         "supply_request": supply_request,
#         "purchase_order": purchase_order,
#         "purchase_order_items": created_items,
#     }


# # ---------------------------------------------------------------------------
# # C2 · Umbrales de aprobación por monto
# # ---------------------------------------------------------------------------

# def get_required_role(purchase_order):
#     """
#     Rol que la política exige para aprobar esta orden, o None si ninguna regla
#     la gobierna.

#     Cuando varias reglas calzan gana la más específica: primero la que nombra
#     la razón social y el tipo de compra, después la que nombra una de las dos,
#     y por último la global. Sin ese orden, una regla global permisiva anularía
#     en silencio a una regla estricta escrita para un caso puntual.
#     """

#     from .models import ApprovalRule

#     amount = to_decimal(purchase_order.total_amount)

#     matching = [
#         rule
#         for rule in ApprovalRule.objects.filter(is_active=True).select_related(
#             "required_role", "legal_entity"
#         )
#         if rule.matches(
#             amount=amount,
#             purchase_type=purchase_order.purchase_type,
#             legal_entity=purchase_order.legal_entity,
#         )
#     ]

#     if not matching:
#         return None

#     def specificity(rule):
#         return (
#             1 if rule.legal_entity_id else 0,
#             1 if rule.purchase_type else 0,
#             rule.amount_from,
#         )

#     matching.sort(key=specificity, reverse=True)
#     return matching[0].required_role


# def user_can_approve(user, purchase_order):
#     """
#     (permitido, rol_requerido).

#     Sin regla aplicable, permitido: la política se va escribiendo por tramos y
#     lo que todavía no está normado no puede quedar bloqueado.
#     """

#     required_role = get_required_role(purchase_order)

#     if required_role is None:
#         return True, None

#     if getattr(user, "is_superuser", False):
#         return True, required_role

#     has_role = user.role_assignments.filter(
#         role=required_role,
#         is_active=True,
#     ).exists()

#     return has_role, required_role


# # ---------------------------------------------------------------------------
# # Sugerencias de compra
# # ---------------------------------------------------------------------------

# PURCHASE_PRIORITY_CRITICAL = "CRITICAL"
# PURCHASE_PRIORITY_HIGH = "HIGH"


# def _purchase_priority(*, available_stock, critical_stock):
#     """
#     Determina la prioridad de reposición.

#     CRITICAL:
#         stock disponible <= critical_stock, siempre que el umbral crítico
#         configurado sea mayor que cero.

#     HIGH:
#         el producto está bajo su mínimo, pero aún no alcanza el nivel crítico.
#     """
#     available_stock = to_decimal(available_stock)
#     critical_stock = to_decimal(critical_stock)

#     if critical_stock > 0 and available_stock <= critical_stock:
#         return PURCHASE_PRIORITY_CRITICAL

#     return PURCHASE_PRIORITY_HIGH


# def _supplier_purchase_options(*, supplier_products, suggested_quantity):
#     """
#     Construye y ordena las alternativas de proveedor.

#     La selección del proveedor se mantiene determinística:
#     - primero proveedores con precio vigente/cargado;
#     - luego menor precio;
#     - finalmente nombre para obtener un orden estable.

#     No se utiliza IA para inventar precios ni cantidades.
#     """
#     suggested_quantity = to_decimal(suggested_quantity)
#     options = []

#     for supplier_product in supplier_products:
#         supplier = supplier_product.supplier
#         unit_price = (
#             to_decimal(supplier_product.last_price)
#             if supplier_product.last_price is not None
#             else None
#         )

#         minimum_purchase = to_decimal(
#             supplier_product.min_purchase_quantity
#         )

#         minimum_purchase_applies = (
#             minimum_purchase > 0
#             and minimum_purchase > suggested_quantity
#         )

#         estimated_total = (
#             unit_price * suggested_quantity
#             if unit_price is not None
#             else None
#         )

#         options.append(
#             {
#                 "supplier_product_uuid": str(
#                     supplier_product.uuid
#                 ),
#                 "supplier_uuid": str(supplier.uuid),
#                 "supplier_name": supplier.name,
#                 "supplier_rut": supplier.rut,
#                 "supplier_sku": supplier_product.supplier_sku,
#                 "currency": supplier_product.currency,
#                 "unit_price": unit_price,
#                 "estimated_total": estimated_total,
#                 "min_purchase_quantity": minimum_purchase,
#                 "minimum_purchase_applies": minimum_purchase_applies,
#                 "requires_purchase_order": (
#                     supplier_product.requires_purchase_order
#                 ),
#                 "allows_credit": supplier_product.allows_credit,
#                 "allows_cash_purchase": (
#                     supplier_product.allows_cash_purchase
#                 ),
#                 "delivery_days": supplier.delivery_days,
#                 "payment_terms_days": supplier.payment_terms_days,
#             }
#         )

#     options.sort(
#         key=lambda option: (
#             option["unit_price"] is None,
#             (
#                 option["unit_price"]
#                 if option["unit_price"] is not None
#                 else Decimal("999999999999999999")
#             ),
#             option["supplier_name"] or "",
#         )
#     )

#     return options


# def get_purchase_suggestions(*, user, branch=None):
#     """
#     Genera sugerencias de reposición para mantener cada producto dentro de los
#     márgenes configurados en BranchProduct.

#     Regla de reposición:
#         available_stock = stock físico - stock reservado

#         Si available_stock < min_stock:
#             target_stock = max_stock, cuando max_stock > 0
#                            min_stock, en caso contrario

#             suggested_quantity = target_stock - available_stock

#     La consulta respeta el scope de sucursales del usuario.

#     ``branch`` puede ser:
#     - una instancia de Branch;
#     - un UUID;
#     - None para considerar todas las sucursales permitidas.

#     El servicio NO llama todavía a Gemini. Devuelve información estructurada y
#     auditable para que la capa de IA pueda, posteriormente, explicar o priorizar
#     las alternativas sin modificar el cálculo de inventario.

#     Consultas principales:
#     1. BranchProduct dentro del scope del usuario.
#     2. Stock agregado por sucursal/producto.
#     3. SupplierProduct de todos los productos que necesitan reposición.

#     Esto evita hacer consultas de stock o proveedores dentro de loops.
#     """
#     branch_products_qs = (
#         BranchProduct.objects.filter(
#             is_active=True,
#             product__is_active=True,
#         )
#         .select_related(
#             "branch",
#             "product",
#             "product__category",
#             "product__unit",
#             "cost_center",
#         )
#         .order_by(
#             "branch__name",
#             "product__name",
#         )
#     )

#     branch_products_qs = apply_branch_scope(
#         branch_products_qs,
#         user,
#         branch_field="branch",
#     )

#     if branch is not None:
#         if hasattr(branch, "pk"):
#             branch_products_qs = branch_products_qs.filter(
#                 branch=branch
#             )
#         else:
#             branch_products_qs = branch_products_qs.filter(
#                 branch__uuid=branch
#             )

#     branch_products = list(branch_products_qs)

#     if not branch_products:
#         return {
#             "summary": {
#                 "products_to_buy": 0,
#                 "critical_products": 0,
#                 "high_priority_products": 0,
#                 "estimated_total": Decimal("0"),
#             },
#             "suggestions": [],
#         }

#     branch_ids = {
#         item.branch_id
#         for item in branch_products
#     }
#     product_ids = {
#         item.product_id
#         for item in branch_products
#     }

#     # Una sola consulta para sumar stock de todas las bodegas de la sucursal.
#     stock_rows = (
#         InventoryStock.objects.filter(
#             warehouse__branch_id__in=branch_ids,
#             product_id__in=product_ids,
#         )
#         .values(
#             "warehouse__branch_id",
#             "product_id",
#         )
#         .annotate(
#             total_quantity=Sum("quantity"),
#             total_reserved_quantity=Sum("reserved_quantity"),
#         )
#     )

#     stock_by_branch_product = {
#         (
#             row["warehouse__branch_id"],
#             row["product_id"],
#         ): {
#             "quantity": to_decimal(
#                 row["total_quantity"]
#             ),
#             "reserved_quantity": to_decimal(
#                 row["total_reserved_quantity"]
#             ),
#         }
#         for row in stock_rows
#     }

#     candidates = []

#     for branch_product in branch_products:
#         stock = stock_by_branch_product.get(
#             (
#                 branch_product.branch_id,
#                 branch_product.product_id,
#             ),
#             {
#                 "quantity": Decimal("0"),
#                 "reserved_quantity": Decimal("0"),
#             },
#         )

#         quantity = to_decimal(stock["quantity"])
#         reserved_quantity = to_decimal(
#             stock["reserved_quantity"]
#         )
#         available_stock = quantity - reserved_quantity

#         min_stock = to_decimal(branch_product.min_stock)
#         max_stock = to_decimal(branch_product.max_stock)
#         critical_stock = to_decimal(
#             branch_product.critical_stock
#         )

#         # Un mínimo igual a cero significa que no existe una regla de reposición
#         # automática útil para este producto.
#         if min_stock <= 0:
#             continue

#         if available_stock >= min_stock:
#             continue

#         target_stock = (
#             max_stock
#             if max_stock > 0
#             else min_stock
#         )

#         # Una configuración inconsistente de max < min no debe recomendar una
#         # cantidad negativa o dejar el producto bajo el mínimo.
#         if target_stock < min_stock:
#             target_stock = min_stock

#         suggested_quantity = (
#             target_stock - available_stock
#         )

#         if suggested_quantity <= 0:
#             continue

#         candidates.append(
#             {
#                 "branch_product": branch_product,
#                 "quantity": quantity,
#                 "reserved_quantity": reserved_quantity,
#                 "available_stock": available_stock,
#                 "min_stock": min_stock,
#                 "max_stock": max_stock,
#                 "critical_stock": critical_stock,
#                 "target_stock": target_stock,
#                 "suggested_quantity": suggested_quantity,
#                 "priority": _purchase_priority(
#                     available_stock=available_stock,
#                     critical_stock=critical_stock,
#                 ),
#             }
#         )

#     if not candidates:
#         return {
#             "summary": {
#                 "products_to_buy": 0,
#                 "critical_products": 0,
#                 "high_priority_products": 0,
#                 "estimated_total": Decimal("0"),
#             },
#             "suggestions": [],
#         }

#     candidate_product_ids = {
#         candidate["branch_product"].product_id
#         for candidate in candidates
#     }

#     # Una sola consulta para todas las alternativas de proveedor.
#     supplier_products = (
#         SupplierProduct.objects.filter(
#             product_id__in=candidate_product_ids,
#             is_active=True,
#             supplier__is_active=True,
#         )
#         .select_related(
#             "supplier",
#             "product",
#         )
#         .order_by(
#             "product_id",
#             "supplier__name",
#         )
#     )

#     suppliers_by_product = {}

#     for supplier_product in supplier_products:
#         suppliers_by_product.setdefault(
#             supplier_product.product_id,
#             [],
#         ).append(supplier_product)

#     suggestions = []
#     estimated_total = Decimal("0")
#     critical_products = 0
#     high_priority_products = 0

#     priority_order = {
#         PURCHASE_PRIORITY_CRITICAL: 0,
#         PURCHASE_PRIORITY_HIGH: 1,
#     }

#     for candidate in candidates:
#         branch_product = candidate["branch_product"]
#         product = branch_product.product

#         supplier_options = _supplier_purchase_options(
#             supplier_products=suppliers_by_product.get(
#                 product.id,
#                 [],
#             ),
#             suggested_quantity=candidate[
#                 "suggested_quantity"
#             ],
#         )

#         recommended_supplier = (
#             supplier_options[0]
#             if supplier_options
#             else None
#         )

#         if (
#             recommended_supplier is not None
#             and recommended_supplier["estimated_total"] is not None
#         ):
#             estimated_total += recommended_supplier[
#                 "estimated_total"
#             ]

#         if candidate["priority"] == PURCHASE_PRIORITY_CRITICAL:
#             critical_products += 1
#         else:
#             high_priority_products += 1

#         suggestions.append(
#             {
#                 "branch_uuid": str(
#                     branch_product.branch.uuid
#                 ),
#                 "branch_name": branch_product.branch.name,
#                 "product_uuid": str(product.uuid),
#                 "product_name": product.name,
#                 "product_internal_code": (
#                     product.internal_code
#                 ),
#                 "product_sku": product.sku,
#                 "category": (
#                     product.category.name
#                     if product.category_id
#                     else None
#                 ),
#                 "unit": (
#                     product.unit.code
#                     if product.unit_id
#                     else None
#                 ),
#                 "quality_rating": to_decimal(
#                     product.quality_rating
#                 ),
#                 "cost_center_uuid": (
#                     str(branch_product.cost_center.uuid)
#                     if branch_product.cost_center_id
#                     else None
#                 ),
#                 "stock": {
#                     "quantity": candidate["quantity"],
#                     "reserved_quantity": candidate[
#                         "reserved_quantity"
#                     ],
#                     "available_quantity": candidate[
#                         "available_stock"
#                     ],
#                     "critical_stock": candidate[
#                         "critical_stock"
#                     ],
#                     "min_stock": candidate["min_stock"],
#                     "max_stock": candidate["max_stock"],
#                     "target_stock": candidate[
#                         "target_stock"
#                     ],
#                 },
#                 "suggested_quantity": candidate[
#                     "suggested_quantity"
#                 ],
#                 "priority": candidate["priority"],
#                 "recommended_supplier": recommended_supplier,
#                 "supplier_options": supplier_options,
#             }
#         )

#     suggestions.sort(
#         key=lambda suggestion: (
#             priority_order.get(
#                 suggestion["priority"],
#                 99,
#             ),
#             -suggestion["quality_rating"],
#             suggestion["product_name"] or "",
#         )
#     )

#     return {
#         "summary": {
#             "products_to_buy": len(suggestions),
#             "critical_products": critical_products,
#             "high_priority_products": high_priority_products,
#             "estimated_total": estimated_total,
#         },
#         "suggestions": suggestions,
#     }



# # import logging
# # from decimal import Decimal

# # from django.core.exceptions import ValidationError
# # from apps.common.statuses import SupplyRequestStatus, PurchaseOrderStatus, PurchaseReceiptStatus
# # from apps.common.business_validations import validate_has_items, validate_status_in, validate_status_not_in, validate_positive_quantity
# # from django.db import transaction
# # from django.utils import timezone

# # from apps.inventory.services import increase_stock
# # from apps.purchasing.models import PurchaseOrder, PurchaseReceipt


# # logger = logging.getLogger(__name__)


# # def to_decimal(value):
# #     if value is None:
# #         return Decimal("0")
# #     return Decimal(str(value))


# # def _get_status_value(model, candidates, fallback=None):
# #     """
# #     Busca una constante de estado existente en el modelo.
# #     Sirve para evitar romper si el nombre exacto de la constante cambia.
# #     """
# #     for candidate in candidates:
# #         if hasattr(model, candidate):
# #             return getattr(model, candidate)

# #     return fallback


# # def _set_if_hasattr(instance, field_name, value):
# #     if hasattr(instance, field_name):
# #         setattr(instance, field_name, value)
# #         return True
# #     return False


# # @transaction.atomic
# # def process_purchase_receipt(*, purchase_receipt, user):
# #     """
# #     Procesa una recepción de compra y actualiza inventario.

# #     Reglas:
# #     - La recepción debe tener bodega.
# #     - La recepción debe tener ítems.
# #     - Cada ítem debe tener cantidad aceptada o recibida mayor a 0.
# #     - Aumenta stock por producto.
# #     - Crea lote si el producto lo requiere o si viene lote/vencimiento.
# #     - Actualiza cantidades recibidas en PurchaseOrderItem si existe relación por producto.
# #     """

# #     validate_status_not_in(
# #         purchase_receipt,
# #         PurchaseReceiptStatus.FINAL_STATUSES,
# #         message="Esta recepción no puede ser procesada en su estado actual.",
# #     )

# #     validate_has_items(
# #         purchase_receipt,
# #         related_name="items",
# #         message="No se puede procesar una recepción sin ítems.",
# #     )

# #     if purchase_receipt.purchase_order:
# #         validate_status_not_in(
# #             purchase_receipt.purchase_order,
# #             PurchaseOrderStatus.FINAL_STATUSES,
# #             message="No se puede procesar una recepción asociada a una OC finalizada o cancelada.",
# #         )

# #     if not purchase_receipt.warehouse:
# #         raise ValidationError("La recepción debe tener una bodega asociada.")

# #     if not purchase_receipt.items.exists():
# #         raise ValidationError("No se puede procesar una recepción sin ítems.")

# #     purchase_order = purchase_receipt.purchase_order
# #     warehouse = purchase_receipt.warehouse

# #     logger.info(
# #         f"Procesando recepción uuid={purchase_receipt.uuid} purchase_order={purchase_order}"
# #     )

# #     processed_items = []

# #     for receipt_item in purchase_receipt.items.select_related("product").all():
# #         product = receipt_item.product

# #         accepted_quantity = to_decimal(
# #             getattr(receipt_item, "accepted_quantity", None)
# #             or getattr(receipt_item, "received_quantity", None)
# #         )

# #         rejected_quantity = to_decimal(getattr(receipt_item, "rejected_quantity", 0))

# #         if accepted_quantity <= 0:
# #             logger.info(
# #                 f"Ítem recepción omitido por cantidad aceptada 0 product={product}"
# #             )
# #             continue

# #         if rejected_quantity < 0:
# #             raise ValidationError("La cantidad rechazada no puede ser negativa.")

# #         lot_number = getattr(receipt_item, "lot_number", None)
# #         expiration_date = getattr(receipt_item, "expiration_date", None)

# #         result = increase_stock(
# #             warehouse=warehouse,
# #             product=product,
# #             quantity=accepted_quantity,
# #             lot_number=lot_number,
# #             expiration_date=expiration_date,
# #             supplier=purchase_order.supplier if purchase_order else None,
# #             reason=f"Recepción de compra {purchase_order.order_number if purchase_order else ''}",
# #             reference_type="PURCHASE_RECEIPT",
# #             reference_uuid=purchase_receipt.uuid,
# #             created_by_uuid=user.profile.uuid if hasattr(user, "profile") else None,
# #         )

# #         processed_items.append(
# #             {
# #                 "receipt_item_uuid": str(receipt_item.uuid),
# #                 "product_uuid": str(product.uuid),
# #                 "accepted_quantity": str(accepted_quantity),
# #                 "stock_uuid": str(result["stock"].uuid),
# #                 "lot_uuid": str(result["lot"].uuid) if result["lot"] else None,
# #                 "movement_uuid": str(result["movement"].uuid),
# #             }
# #         )

# #         if purchase_order:
# #             order_item = purchase_order.items.filter(product=product).first()

# #             if order_item:
# #                 current_received = to_decimal(getattr(order_item, "received_quantity", 0))
# #                 order_item.received_quantity = current_received + accepted_quantity
# #                 order_item.save(update_fields=["received_quantity", "updated_at"])

# #     if not processed_items:
# #         raise ValidationError("No hay ítems con cantidad aceptada para procesar.")

# #     processed_status = _get_status_value(
# #         PurchaseReceipt,
# #         ["STATUS_PROCESSED", "STATUS_COMPLETED", "STATUS_RECEIVED"],
# #         fallback=getattr(purchase_receipt, "status", None),
# #     )

# #     update_fields = ["updated_at"]

# #     if processed_status:
# #         purchase_receipt.status = processed_status
# #         update_fields.append("status")

# #     if hasattr(purchase_receipt, "processed_at"):
# #         purchase_receipt.processed_at = timezone.now()
# #         update_fields.append("processed_at")

# #     if hasattr(purchase_receipt, "received_at") and not purchase_receipt.received_at:
# #         purchase_receipt.received_at = timezone.now()
# #         update_fields.append("received_at")

# #     purchase_receipt.save(update_fields=update_fields)

# #     if purchase_order:
# #         _update_purchase_order_status_by_receipts(purchase_order)

# #     logger.info(
# #         f"Recepción procesada correctamente uuid={purchase_receipt.uuid} items={len(processed_items)}"
# #     )

# #     return {
# #         "purchase_receipt": purchase_receipt,
# #         "purchase_order": purchase_order,
# #         "processed_items": processed_items,
# #     }


# # def _update_purchase_order_status_by_receipts(purchase_order):
# #     """
# #     Actualiza estado de la OC según cantidades recibidas.
# #     """

# #     total_items = purchase_order.items.count()

# #     if total_items == 0:
# #         return purchase_order

# #     fully_received = True
# #     partially_received = False

# #     for item in purchase_order.items.all():
# #         ordered_quantity = to_decimal(getattr(item, "quantity", 0))
# #         received_quantity = to_decimal(getattr(item, "received_quantity", 0))

# #         if received_quantity > 0:
# #             partially_received = True

# #         if received_quantity < ordered_quantity:
# #             fully_received = False

# #     if fully_received:
# #         new_status = _get_status_value(
# #             PurchaseOrder,
# #             ["STATUS_RECEIVED", "STATUS_COMPLETED", "STATUS_CLOSED"],
# #             fallback=getattr(purchase_order, "status", None),
# #         )
# #     elif partially_received:
# #         new_status = _get_status_value(
# #             PurchaseOrder,
# #             ["STATUS_PARTIALLY_RECEIVED", "STATUS_PARTIAL_RECEIVED"],
# #             fallback=getattr(purchase_order, "status", None),
# #         )
# #     else:
# #         new_status = getattr(purchase_order, "status", None)

# #     if new_status:
# #         purchase_order.status = new_status

# #     if fully_received and hasattr(purchase_order, "received_at"):
# #         purchase_order.received_at = timezone.now()
# #         purchase_order.save(update_fields=["status", "received_at", "updated_at"])
# #     else:
# #         purchase_order.save(update_fields=["status", "updated_at"])

# #     logger.info(
# #         f"Estado OC actualizado order={purchase_order} status={purchase_order.status}"
# #     )

# #     return purchase_order


# # def generate_purchase_order_number():
# #     """
# #     Genera un número único de OC con formato OC-YYYYMMDD-NNNN.
# #     Usa select_for_update en una transacción para evitar duplicados en concurrencia.
# #     """
# #     from django.db import transaction as db_transaction

# #     today = timezone.now().date()
# #     prefix = today.strftime("OC-%Y%m%d")

# #     with db_transaction.atomic():
# #         # Bloquea las filas del día para contar de forma segura
# #         count = (
# #             PurchaseOrder.objects.select_for_update()
# #             .filter(order_number__startswith=prefix)
# #             .count()
# #         ) + 1

# #     return f"{prefix}-{count:04d}"


# # def get_model_status(model, candidates, fallback):
# #     for candidate in candidates:
# #         if hasattr(model, candidate):
# #             return getattr(model, candidate)

# #     return fallback


# # def get_supplier_product_price(*, supplier, product):
# #     try:
# #         supplier_product = supplier.supplier_products.filter(
# #             product=product,
# #             is_active=True,
# #         ).first()

# #         if supplier_product and supplier_product.last_price is not None:
# #             return to_decimal(supplier_product.last_price)

# #     except Exception:
# #         pass

# #     return Decimal("0")


# # @transaction.atomic
# # def convert_supply_request_to_purchase_order(
# #     *,
# #     supply_request,
# #     supplier,
# #     user,
# #     expected_delivery_date=None,
# #     notes=None,
# #     tax_rate=Decimal("0.19"),
# # ):
# #     """
# #     Convierte una solicitud de insumos en una orden de compra.

# #     Usa:
# #     - approved_quantity si existe y es mayor a 0
# #     - requested_quantity como respaldo

# #     El precio unitario se intenta obtener desde SupplierProduct.last_price.
# #     Si no existe precio, se crea con 0 para que abastecimiento lo complete.
# #     """

# #     validate_has_items(
# #         supply_request,
# #         related_name="items",
# #         message="No se puede convertir una solicitud sin ítems.",
# #     )

# #     validate_status_not_in(
# #         supply_request,
# #         SupplyRequestStatus.FINAL_STATUSES,
# #         message="No se puede convertir una solicitud finalizada, rechazada, cerrada o ya convertida.",
# #     )

# #     validate_status_in(
# #         supply_request,
# #         SupplyRequestStatus.VALID_FOR_CONVERSION,
# #         message="Solo se pueden convertir solicitudes aprobadas en orden de compra.",
# #     )

# #     existing_purchase_order = PurchaseOrder.objects.filter(
# #         supply_request=supply_request
# #     ).exclude(
# #         status__in=[
# #             PurchaseOrderStatus.CANCELLED,
# #         ]
# #     ).first()

# #     if existing_purchase_order:
# #         raise ValidationError(
# #             f"La solicitud ya tiene una orden de compra asociada: {existing_purchase_order.order_number}."
# #         )

# #     items_to_convert = []

# #     for item in supply_request.items.select_related("product").all():
# #         quantity = to_decimal(
# #             getattr(item, "approved_quantity", None)
# #             or getattr(item, "requested_quantity", None)
# #         )

# #         if quantity <= 0:
# #             continue

# #         unit_price = get_supplier_product_price(
# #             supplier=supplier,
# #             product=item.product,
# #         )

# #         total_amount = quantity * unit_price

# #         items_to_convert.append(
# #             {
# #                 "source_item": item,
# #                 "product": item.product,
# #                 "quantity": quantity,
# #                 "unit_price": unit_price,
# #                 "total_amount": total_amount,
# #             }
# #         )

# #     if not items_to_convert:
# #         raise ValidationError("No hay ítems con cantidad válida para convertir.")

# #     subtotal_amount = sum(item["total_amount"] for item in items_to_convert)
# #     tax_amount = (subtotal_amount * to_decimal(tax_rate)).quantize(Decimal("0.01"))
# #     total_amount = (subtotal_amount + tax_amount).quantize(Decimal("0.01"))

# #     purchase_order = PurchaseOrder.objects.create(
# #         supplier=supplier,
# #         legal_entity=supply_request.legal_entity,
# #         branch=supply_request.branch,
# #         cost_center=supply_request.cost_center,
# #         supply_request=supply_request,
# #         order_number=generate_purchase_order_number(),
# #         status=PurchaseOrderStatus.DRAFT,
# #         requested_by=user,
# #         expected_delivery_date=expected_delivery_date,
# #         notes=notes,
# #         subtotal_amount=subtotal_amount,
# #         tax_amount=tax_amount,
# #         total_amount=total_amount,
# #     )

# #     created_items = []

# #     for item_data in items_to_convert:
# #         purchase_order_item = purchase_order.items.create(
# #             product=item_data["product"],
# #             quantity=item_data["quantity"],
# #             unit_price=item_data["unit_price"],
# #             total_amount=item_data["total_amount"],
# #             received_quantity=Decimal("0"),
# #         )

# #         created_items.append(purchase_order_item)

# #     supply_request.status = SupplyRequestStatus.CONVERTED_TO_PURCHASE_ORDER
# #     supply_request.save(update_fields=["status", "updated_at"])

# #     logger.info(
# #         f"Solicitud convertida a OC supply_request={supply_request.uuid} purchase_order={purchase_order.uuid}"
# #     )

# #     return {
# #         "supply_request": supply_request,
# #         "purchase_order": purchase_order,
# #         "purchase_order_items": created_items,
# #     }


# # # ---------------------------------------------------------------------------
# # # C2 · Umbrales de aprobación por monto
# # # ---------------------------------------------------------------------------

# # def get_required_role(purchase_order):
# #     """
# #     Rol que la política exige para aprobar esta orden, o None si ninguna regla
# #     la gobierna.

# #     Cuando varias reglas calzan gana la más específica: primero la que nombra
# #     la razón social y el tipo de compra, después la que nombra una de las dos,
# #     y por último la global. Sin ese orden, una regla global permisiva anularía
# #     en silencio a una regla estricta escrita para un caso puntual.
# #     """

# #     from .models import ApprovalRule

# #     amount = to_decimal(purchase_order.total_amount)

# #     matching = [
# #         rule
# #         for rule in ApprovalRule.objects.filter(is_active=True).select_related(
# #             "required_role", "legal_entity"
# #         )
# #         if rule.matches(
# #             amount=amount,
# #             purchase_type=purchase_order.purchase_type,
# #             legal_entity=purchase_order.legal_entity,
# #         )
# #     ]

# #     if not matching:
# #         return None

# #     def specificity(rule):
# #         return (
# #             1 if rule.legal_entity_id else 0,
# #             1 if rule.purchase_type else 0,
# #             rule.amount_from,
# #         )

# #     matching.sort(key=specificity, reverse=True)
# #     return matching[0].required_role


# # def user_can_approve(user, purchase_order):
# #     """
# #     (permitido, rol_requerido).

# #     Sin regla aplicable, permitido: la política se va escribiendo por tramos y
# #     lo que todavía no está normado no puede quedar bloqueado.
# #     """

# #     required_role = get_required_role(purchase_order)

# #     if required_role is None:
# #         return True, None

# #     if getattr(user, "is_superuser", False):
# #         return True, required_role

# #     has_role = user.role_assignments.filter(
# #         role=required_role,
# #         is_active=True,
# #     ).exists()

# #     return has_role, required_role
