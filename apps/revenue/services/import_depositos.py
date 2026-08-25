"""
Carga del informe de depósitos a la recaudación diaria.

El informe de depósitos es el único documento que ya viene abierto por razón
social, con su RUT. Es la fuente natural de lo percibido.

Viene en PDF y de un solo día: para construir el flujo del año hay que pedirle
al proveedor del sistema clínico la versión en planilla y por rango de fechas.
Mientras tanto, esta carga funciona con lo que hay.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.organizations.models import LegalEntity, LegalEntityAlias

from ..models import CashCollection


ZERO = Decimal("0")


def normalize_rut(value):
    """Deja el RUT sin puntos ni guion y en mayúsculas, para poder comparar."""

    if not value:
        return ""
    return re.sub(r"[^0-9kK]", "", str(value)).upper()


def _decimal(value):
    if value in (None, "", "-"):
        return ZERO
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return ZERO


def _date(value):
    if not value:
        return None
    texto = str(value).strip()
    for formato in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def resolve_legal_entity(*, rut=None, name=None):
    """
    Por RUT primero, que es identificador; por alias de nombre después.

    El informe trae el RUT con puntos y la ficha lo guarda sin ellos, así que
    la comparación se hace sobre la forma normalizada de ambos.
    """

    normalizado = normalize_rut(rut)

    if normalizado:
        for entidad in LegalEntity.objects.filter(is_active=True):
            if normalize_rut(entidad.rut) == normalizado:
                return entidad

    if name:
        return LegalEntityAlias.resolve(name)

    return None


def _payments_by_method(provider):
    metodos = {"EFECTIVO": ZERO, "DEBITO": ZERO, "CREDITO": ZERO, "CHEQUE": ZERO}

    for pago in provider.get("payments") or []:
        clave = (
            str(pago.get("payment_method") or "")
            .upper()
            .replace("É", "E")
            .replace("Ó", "O")
        )
        if clave in metodos:
            metodos[clave] = _decimal(pago.get("total"))

    return metodos


def analyze_providers(providers):
    """Qué sociedades del informe no se pueden resolver, sin escribir nada."""

    sin_resolver = []
    resueltas = set()
    bloques = 0

    for provider in providers:
        if _is_total_row(provider):
            continue

        bloques += 1
        entidad = resolve_legal_entity(
            rut=provider.get("rut"), name=provider.get("name")
        )

        if entidad is None:
            etiqueta = f"{provider.get('name')} ({provider.get('rut')})"
            if etiqueta not in sin_resolver:
                sin_resolver.append(etiqueta)
        else:
            resueltas.add(entidad.id)

    return {
        # Bloques del informe frente a sociedades distintas: no son lo mismo
        # cuando una sociedad recauda en más de un punto.
        "blocks_total": bloques,
        "rows_total": len(resueltas) + len(sin_resolver),
        "rows_mappable": len(resueltas),
        "unmapped_providers": sin_resolver,
    }


def _is_total_row(provider):
    """El informe cierra con una fila de totales que no es una sociedad."""

    nombre = str(provider.get("name") or "").strip().upper()
    return not provider.get("rut") or nombre.startswith("TOTAL")


@transaction.atomic
def import_providers(providers, *, collection_date, document=None):
    """
    Persiste la recaudación por sociedad de una jornada.

    Una misma sociedad puede aparecer en varios bloques del informe —Maule Sur
    figura dos veces en el del 24-07, por $832.416 y $113.680— porque el
    documento abre por punto de recaudación sin nombrar la sucursal. Los
    bloques se suman antes de persistir: guardarlos uno por uno con la misma
    clave haría que el segundo pisara al primero y la caja del día perdería
    plata en silencio.

    Reimportar el mismo día actualiza en vez de duplicar: el informe se puede
    volver a emitir tras una corrección.
    """

    agregado = {}

    for provider in providers:
        if _is_total_row(provider):
            continue

        entidad = resolve_legal_entity(
            rut=provider.get("rut"), name=provider.get("name")
        )
        if entidad is None:
            continue

        totales = provider.get("totals") or {}
        metodos = _payments_by_method(provider)

        acumulado = agregado.setdefault(
            entidad.id,
            {
                "legal_entity": entidad,
                "particular_amount": ZERO,
                "copay_amount": ZERO,
                "withdrawal_amount": ZERO,
                "total_amount": ZERO,
                "cash_amount": ZERO,
                "debit_amount": ZERO,
                "credit_amount": ZERO,
                "check_amount": ZERO,
            },
        )

        acumulado["particular_amount"] += _decimal(totales.get("particular"))
        acumulado["copay_amount"] += _decimal(totales.get("copay"))
        acumulado["withdrawal_amount"] += _decimal(totales.get("withdrawal"))
        acumulado["total_amount"] += _decimal(totales.get("total"))
        acumulado["cash_amount"] += metodos["EFECTIVO"]
        acumulado["debit_amount"] += metodos["DEBITO"]
        acumulado["credit_amount"] += metodos["CREDITO"]
        acumulado["check_amount"] += metodos["CHEQUE"]

    creadas = []

    for acumulado in agregado.values():
        entidad = acumulado.pop("legal_entity")

        collection, _ = CashCollection.objects.update_or_create(
            legal_entity=entidad,
            branch=None,
            collection_date=collection_date,
            defaults={**acumulado, "source_document": document},
        )
        creadas.append(collection)

    return creadas


def parse_uploaded_depositos(uploaded_file):
    """Devuelve (providers, fecha, file_name) desde el informe de depósitos."""

    from rest_framework.exceptions import ValidationError

    from apps.documents.services.document_parser import (
        DOCUMENT_TYPE_DETALLE_CAJA,
        document_parser,
    )

    parsed = document_parser.parse(uploaded_file)

    if parsed.get("document_type") != DOCUMENT_TYPE_DETALLE_CAJA:
        raise ValidationError(
            {
                "file": (
                    "El archivo no es un informe de depósitos. "
                    f"Se detectó: {parsed.get('document_type_label')}."
                )
            }
        )

    contenedor = parsed.get("data") or {}
    interior = contenedor.get("data") or contenedor

    providers = interior.get("providers") or []
    fecha = _date(interior.get("date_from"))

    return providers, fecha, uploaded_file.name
