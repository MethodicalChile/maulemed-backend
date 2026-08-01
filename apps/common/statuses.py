class SupplyRequestStatus:
    DRAFT                     = "BORRADOR"
    SUBMITTED                 = "ENVIADA"
    IN_REVIEW                 = "EN_REVISION"
    OBSERVED                  = "OBSERVADA"
    APPROVED                  = "APROBADA"
    REJECTED                  = "RECHAZADA"
    PARTIALLY_APPROVED        = "PARCIALMENTE_APROBADA"
    CONVERTED_TO_PURCHASE_ORDER = "CONVERTIDA_EN_COMPRA"

    VALID_FOR_CONVERSION = [
        APPROVED,
    ]

    FINAL_STATUSES = [
        REJECTED,
        CONVERTED_TO_PURCHASE_ORDER,
    ]


class PurchaseOrderStatus:
    DRAFT              = "BORRADOR"
    PENDING_APPROVAL   = "EN_APROBACION"
    APPROVED           = "APROBADA"
    SENT_TO_SUPPLIER   = "ENVIADA_PROVEEDOR"
    ACCEPTED_BY_SUPPLIER = "ACEPTADA_PROVEEDOR"
    REJECTED_BY_SUPPLIER = "RECHAZADA_PROVEEDOR"
    PARTIALLY_RECEIVED = "PARCIALMENTE_RECIBIDA"
    RECEIVED           = "RECIBIDA"
    CANCELLED          = "CANCELADA"
    CLOSED             = "CERRADA"

    VALID_FOR_SEND = [
        APPROVED,
    ]

    VALID_FOR_RECEIPT = [
        APPROVED,
        SENT_TO_SUPPLIER,
        ACCEPTED_BY_SUPPLIER,
        PARTIALLY_RECEIVED,
    ]

    FINAL_STATUSES = [
        RECEIVED,
        CLOSED,
        CANCELLED,
    ]


class PurchaseReceiptStatus:
    OK             = "RECIBIDO_OK"
    PARTIAL        = "RECIBIDO_PARCIAL"
    WITH_INCIDENT  = "CON_INCIDENCIA"
    REJECTED       = "RECHAZADO"

    # No hay estado "procesado/completado/cancelado" en el modelo.
    # Los servicios verifican contra esta lista para evitar re-procesar.
    FINAL_STATUSES: list = []


class StockTransferStatus:
    REQUESTED          = "SOLICITADO"
    APPROVED           = "APROBADO"
    REJECTED           = "RECHAZADO"
    SENT               = "ENVIADO"
    RECEIVED           = "RECIBIDO"
    RETURNED           = "DEVUELTO"
    CLOSED             = "CERRADO"
    CANCELLED          = "CANCELADO"

    VALID_FOR_SEND = [
        APPROVED,
    ]

    VALID_FOR_RECEIVE = [
        SENT,
    ]

    FINAL_STATUSES = [
        REJECTED,
        RECEIVED,
        CLOSED,
        CANCELLED,
    ]


class SupplierInvoiceStatus:
    RECEIVED           = "RECIBIDA"
    VALIDATED          = "VALIDADA"
    PARTIALLY_PAID     = "PARCIALMENTE_PAGADA"
    PAID               = "PAGADA"
    VOID               = "ANULADA"


class PaymentStatus:
    PENDING    = "PENDIENTE"
    PAID       = "PAGADO"
    CANCELLED  = "ANULADO"
