import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from apps.common.statuses import SupplyRequestStatus, PurchaseOrderStatus, PurchaseReceiptStatus
from apps.common.business_validations import validate_has_items, validate_status_in, validate_status_not_in, validate_positive_quantity
from django.db import transaction
from django.utils import timezone

from apps.inventory.services import increase_stock
from apps.purchasing.models import PurchaseOrder, PurchaseReceipt


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
