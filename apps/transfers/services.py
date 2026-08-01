import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from apps.common.statuses import StockTransferStatus
from apps.common.business_validations import validate_has_items, validate_status_in, validate_status_not_in
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import Warehouse, InventoryMovement
from apps.inventory.services import decrease_stock, increase_stock
from apps.transfers.models import StockTransfer


logger = logging.getLogger(__name__)


def to_decimal(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _get_first_active_warehouse_by_branch(branch):
    warehouse = Warehouse.objects.filter(
        branch=branch,
        is_active=True,
    ).order_by("id").first()

    if not warehouse:
        raise ValidationError(
            f"La sucursal {branch} no tiene una bodega activa configurada."
        )

    return warehouse


def get_origin_warehouse(stock_transfer):
    """
    Si el modelo tiene origin_warehouse, lo usa.
    Si no, toma la primera bodega activa de la sucursal origen.
    """
    if hasattr(stock_transfer, "origin_warehouse") and stock_transfer.origin_warehouse:
        return stock_transfer.origin_warehouse

    return _get_first_active_warehouse_by_branch(stock_transfer.origin_branch)


def get_destination_warehouse(stock_transfer):
    """
    Si el modelo tiene destination_warehouse, lo usa.
    Si no, toma la primera bodega activa de la sucursal destino.
    """
    if hasattr(stock_transfer, "destination_warehouse") and stock_transfer.destination_warehouse:
        return stock_transfer.destination_warehouse

    return _get_first_active_warehouse_by_branch(stock_transfer.destination_branch)


def _get_status(model, candidates, fallback=None):
    for candidate in candidates:
        if hasattr(model, candidate):
            return getattr(model, candidate)

    return fallback


@transaction.atomic
def approve_stock_transfer(*, stock_transfer, user):
    if not stock_transfer.items.exists():
        raise ValidationError("No se puede aprobar un traspaso sin ítems.")

    stock_transfer.status = StockTransfer.STATUS_APPROVED
    stock_transfer.approved_by = user
    stock_transfer.approved_at = timezone.now()
    stock_transfer.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "updated_at",
        ]
    )

    logger.info(f"Traspaso aprobado uuid={stock_transfer.uuid}")

    return stock_transfer


@transaction.atomic
def send_stock_transfer(*, stock_transfer, user):
    """
    Al enviar:
    - valida bodega origen
    - descuenta stock de origen
    - registra cantidades enviadas en los ítems
    - cambia estado a enviado
    """

    if not stock_transfer.items.exists():
        raise ValidationError("No se puede enviar un traspaso sin ítems.")

    origin_warehouse = get_origin_warehouse(stock_transfer)

    processed_items = []

    for item in stock_transfer.items.select_related("product", "lot").all():
        product = item.product

        quantity = to_decimal(
            getattr(item, "approved_quantity", None)
            or getattr(item, "requested_quantity", None)
        )

        if quantity <= 0:
            raise ValidationError(
                f"El producto {product} no tiene cantidad aprobada para enviar."
            )

        decrease_result = decrease_stock(
            warehouse=origin_warehouse,
            product=product,
            quantity=quantity,
            lot=item.lot if hasattr(item, "lot") else None,
            movement_type=InventoryMovement.TYPE_TRANSFER,
            reason=f"Salida por traspaso {stock_transfer.uuid}",
            reference_type="STOCK_TRANSFER",
            reference_uuid=stock_transfer.uuid,
            created_by_uuid=user.profile.uuid if hasattr(user, "profile") else None,
        )

        if hasattr(item, "sent_quantity"):
            item.sent_quantity = quantity
            item.save(update_fields=["sent_quantity", "updated_at"])

        processed_items.append(
            {
                "transfer_item_uuid": str(item.uuid),
                "product_uuid": str(product.uuid),
                "sent_quantity": str(quantity),
                "origin_warehouse_uuid": str(origin_warehouse.uuid),
                "movement_uuid": str(decrease_result["movement"].uuid),
            }
        )

    stock_transfer.status = StockTransfer.STATUS_SENT
    stock_transfer.sent_by = user
    stock_transfer.sent_at = timezone.now()
    stock_transfer.save(
        update_fields=[
            "status",
            "sent_by",
            "sent_at",
            "updated_at",
        ]
    )

    logger.info(
        f"Traspaso enviado uuid={stock_transfer.uuid} items={len(processed_items)}"
    )

    return {
        "stock_transfer": stock_transfer,
        "processed_items": processed_items,
    }


@transaction.atomic
def receive_stock_transfer(*, stock_transfer, user):
    """
    Al recibir:
    - valida bodega destino
    - aumenta stock en destino
    - registra cantidades recibidas
    - cambia estado a recibido
    """

    if not stock_transfer.items.exists():
        raise ValidationError("No se puede recibir un traspaso sin ítems.")

    destination_warehouse = get_destination_warehouse(stock_transfer)

    processed_items = []

    for item in stock_transfer.items.select_related("product", "lot").all():
        product = item.product

        quantity = to_decimal(
            getattr(item, "received_quantity", None)
            or getattr(item, "sent_quantity", None)
            or getattr(item, "approved_quantity", None)
            or getattr(item, "requested_quantity", None)
        )

        if quantity <= 0:
            raise ValidationError(
                f"El producto {product} no tiene cantidad válida para recibir."
            )

        lot = item.lot if hasattr(item, "lot") else None

        increase_result = increase_stock(
            warehouse=destination_warehouse,
            product=product,
            quantity=quantity,
            lot_number=lot.lot_number if lot else None,
            expiration_date=lot.expiration_date if lot else None,
            supplier=lot.supplier if lot else None,
            movement_type=InventoryMovement.TYPE_TRANSFER,
            reason=f"Ingreso por traspaso {stock_transfer.uuid}",
            reference_type="STOCK_TRANSFER",
            reference_uuid=stock_transfer.uuid,
            created_by_uuid=user.profile.uuid if hasattr(user, "profile") else None,
        )

        if hasattr(item, "received_quantity"):
            item.received_quantity = quantity
            item.save(update_fields=["received_quantity", "updated_at"])

        processed_items.append(
            {
                "transfer_item_uuid": str(item.uuid),
                "product_uuid": str(product.uuid),
                "received_quantity": str(quantity),
                "destination_warehouse_uuid": str(destination_warehouse.uuid),
                "stock_uuid": str(increase_result["stock"].uuid),
                "lot_uuid": str(increase_result["lot"].uuid) if increase_result["lot"] else None,
                "movement_uuid": str(increase_result["movement"].uuid),
            }
        )

    stock_transfer.status = StockTransfer.STATUS_RECEIVED
    stock_transfer.received_by = user
    stock_transfer.received_at = timezone.now()
    stock_transfer.save(
        update_fields=[
            "status",
            "received_by",
            "received_at",
            "updated_at",
        ]
    )

    logger.info(
        f"Traspaso recibido uuid={stock_transfer.uuid} items={len(processed_items)}"
    )

    return {
        "stock_transfer": stock_transfer,
        "processed_items": processed_items,
    }


@transaction.atomic
def close_stock_transfer(*, stock_transfer, user=None):
    closed_status = _get_status(
        StockTransfer,
        ["STATUS_CLOSED"],
        fallback="CERRADO",
    )

    stock_transfer.status = closed_status

    if hasattr(stock_transfer, "closed_at"):
        stock_transfer.closed_at = timezone.now()
        stock_transfer.save(update_fields=["status", "closed_at", "updated_at"])
    else:
        stock_transfer.save(update_fields=["status", "updated_at"])

    logger.info(f"Traspaso cerrado uuid={stock_transfer.uuid}")

    return stock_transfer
