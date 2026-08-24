"""
Carga del reporte de prestaciones al libro de ingresos.

El parser de `documents` ya extrae las columnas que hacen falta —prestador,
financiador, sucursal, valor, descuento— pero sólo las muestra. Aquí se
persisten.

Dos decisiones de diseño que conviene no revertir:

1. **No se guarda identificación del paciente.** El reporte trae RUT y nombre;
   la carga los descarta. Para el control financiero basta la referencia de la
   cita, y persistirlos metería datos personales de salud donde no hacen falta.

2. **Lo que no mapea no se importa.** Una fila cuyo prestador o financiador no
   se puede resolver queda listada en el lote para que alguien cree el alias y
   reintente. Atribuirla "a la que más se parece" destruiría en silencio justo
   la apertura por sociedad que este módulo existe para conservar.

La carga se hace contra un archivo con estas columnas, nunca contra un sistema
clínico concreto: MauleMed está migrando de RISPACS y el proceso no cambia con
el sistema.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.organizations.models import Branch, LegalEntityAlias

from ..models import Financier, FinancierAlias, RevenueEntry, RevenueImportBatch


ZERO = Decimal("0")


def _decimal(value):
    if value in (None, "", "-"):
        return ZERO
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return ZERO


def _date(value):
    """El parser normaliza a ISO; se toleran los formatos chilenos por si acaso."""

    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()

    texto = str(value).strip()[:19]

    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[: len(formato) + 2], formato).date()
        except ValueError:
            continue

    return None


def _resolve_branch(raw_name, legal_entity):
    """
    La sucursal es opcional: el ingreso se atribuye a la sociedad aunque el
    nombre de sucursal no calce con ninguna cargada.
    """

    if not raw_name:
        return None

    normalized = LegalEntityAlias.normalize(raw_name)

    return (
        Branch.objects.filter(
            name__iexact=normalized, is_active=True
        ).first()
        or Branch.objects.filter(
            legal_entity=legal_entity, is_active=True
        ).filter(name__icontains=normalized.split()[-1]).first()
    )


def analyze_records(records):
    """
    Revisa qué se puede mapear, sin escribir nada.

    Alimenta la previsualización: el usuario ve cuántas filas entrarían y qué
    alias le faltan antes de confirmar.
    """

    unmapped_providers = set()
    unmapped_financiers = set()
    mappable = 0

    for record in records:
        legal_entity = LegalEntityAlias.resolve(record.get("provider"))
        financier = FinancierAlias.resolve(record.get("financier"))

        if legal_entity is None:
            unmapped_providers.add(
                LegalEntityAlias.normalize(record.get("provider")) or "(vacío)"
            )

        if financier is None:
            unmapped_financiers.add(
                FinancierAlias.normalize(record.get("financier")) or "(vacío)"
            )

        if legal_entity is not None and financier is not None:
            mappable += 1

    return {
        "rows_total": len(records),
        "rows_mappable": mappable,
        "rows_skipped": len(records) - mappable,
        "unmapped_providers": sorted(unmapped_providers),
        "unmapped_financiers": sorted(unmapped_financiers),
    }


@transaction.atomic
def import_records(records, *, file_name=None, document=None, user=None):
    """Persiste las filas mapeables y devuelve el lote con su resultado."""

    analysis = analyze_records(records)

    batch = RevenueImportBatch.objects.create(
        document=document,
        file_name=file_name,
        rows_total=analysis["rows_total"],
        unmapped_providers=analysis["unmapped_providers"],
        unmapped_financiers=analysis["unmapped_financiers"],
        imported_by=user,
        status=RevenueImportBatch.STATUS_IMPORTED,
    )

    fechas = []
    importadas = 0
    vistas = set()

    for record in records:
        legal_entity = LegalEntityAlias.resolve(record.get("provider"))
        financier = FinancierAlias.resolve(record.get("financier"))

        if legal_entity is None or financier is None:
            continue

        service_date = _date(record.get("date") or record.get("scheduled_datetime"))
        if service_date is None:
            continue

        appointment_ref = str(record.get("id") or "").strip() or None
        procedure_code = str(record.get("procedure_code") or "").strip() or None

        # Una cita puede repetir el mismo procedimiento (rodilla izquierda y
        # derecha comparten código). La clave de unicidad las colapsaría, así
        # que se desambigua con un sufijo en vez de perder la línea.
        clave = (appointment_ref, procedure_code)
        if clave in vistas:
            sufijo = 2
            while (appointment_ref, f"{procedure_code}#{sufijo}") in vistas:
                sufijo += 1
            procedure_code = f"{procedure_code}#{sufijo}"
            clave = (appointment_ref, procedure_code)
        vistas.add(clave)

        gross = _decimal(record.get("value"))

        # El archivo consigna los descuentos en negativo, y el net_value que
        # calcula el parser los resta con ese signo, inflando el ingreso. Se
        # guarda el descuento como magnitud positiva y el neto se recalcula:
        # mezclar convenios de signo es una fuente clásica de error silencioso.
        discount = abs(_decimal(record.get("discount")))

        RevenueEntry.objects.create(
            legal_entity=legal_entity,
            branch=_resolve_branch(record.get("branch"), legal_entity),
            financier=financier,
            service_date=service_date,
            appointment_ref=appointment_ref,
            procedure_code=procedure_code,
            procedure_name=record.get("procedure"),
            modality=record.get("modality"),
            room=record.get("room"),
            status=record.get("status"),
            gross_amount=gross,
            discount_amount=discount,
            net_amount=gross - discount,
            import_batch=batch,
        )

        fechas.append(service_date)
        importadas += 1

    batch.rows_imported = importadas
    batch.rows_skipped = analysis["rows_total"] - importadas
    batch.period_from = min(fechas) if fechas else None
    batch.period_to = max(fechas) if fechas else None
    batch.save(
        update_fields=[
            "rows_imported",
            "rows_skipped",
            "period_from",
            "period_to",
            "updated_at",
        ]
    )

    return batch


def parse_uploaded_reporte(uploaded_file):
    """
    Extrae las filas del archivo usando el parser que ya existe.

    Devuelve (records, file_name). Levanta ValidationError de DRF si el archivo
    no es un reporte de prestaciones.
    """

    from rest_framework.exceptions import ValidationError

    from apps.documents.services.document_parser import (
        DOCUMENT_TYPE_REPORTE,
        document_parser,
    )

    parsed = document_parser.parse(uploaded_file)

    if parsed.get("document_type") != DOCUMENT_TYPE_REPORTE:
        raise ValidationError(
            {
                "file": (
                    "El archivo no es un reporte de prestaciones. "
                    f"Se detectó: {parsed.get('document_type_label')}."
                )
            }
        )

    # La respuesta del parser anida distinto según el origen: el PDF deja el
    # resultado en "data", y la planilla lo envuelve una vez más porque el
    # excel_parser agrega su propia cabecera. Se buscan las filas en ambos.
    contenedor = parsed.get("data") or {}
    records = contenedor.get("records")

    if records is None:
        records = (contenedor.get("data") or {}).get("records", [])

    return records, uploaded_file.name
