"""
Siembra las categorías del presupuesto de caja.

Los nombres son literales de la hoja PRESUPUESTO de "Flujo de caja y ppto.xlsx"
de la Jefatura de Administración y Finanzas: 34 categorías en cinco bloques,
filas 7 a 44, en su orden original. Se transcriben tal cual —incluidos
"Licencias RIS/PACS y software" y "Pago de capital de créditos"— para que el
presupuesto cargado en la plataforma sea reconocible por quien hoy lo llena a
mano, y para que comparar real contra presupuesto no exija traducir nombres.

    python manage.py seed_budget_categories
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.finance.models import BudgetCategory


IN = BudgetCategory.SIGN_INFLOW
OUT = BudgetCategory.SIGN_OUTFLOW

OPERATING_REVENUE = BudgetCategory.BLOCK_OPERATING_REVENUE
OPERATING_EXPENSE = BudgetCategory.BLOCK_OPERATING_EXPENSE
INVESTMENT_EXPENSE = BudgetCategory.BLOCK_INVESTMENT_EXPENSE
FINANCING_REVENUE = BudgetCategory.BLOCK_FINANCING_REVENUE
FINANCING_EXPENSE = BudgetCategory.BLOCK_FINANCING_EXPENSE


# (código, nombre, bloque, signo)
CATEGORIES = [
    # ── Operación · Ingreso (5) ────────────────────────────────────────────
    ("OP-ING-01", "Pacientes particulares", OPERATING_REVENUE, IN),
    ("OP-ING-02", "Bonos FONASA", OPERATING_REVENUE, IN),
    ("OP-ING-03", "Isapres", OPERATING_REVENUE, IN),
    ("OP-ING-04", "Convenios empresas e instituciones", OPERATING_REVENUE, IN),
    ("OP-ING-05", "Otros ingresos operacionales", OPERATING_REVENUE, IN),

    # ── Operación · Egreso (20) ────────────────────────────────────────────
    ("OP-EGR-01", "Honorarios informes médicos", OPERATING_EXPENSE, OUT),
    ("OP-EGR-02", "Remuneraciones", OPERATING_EXPENSE, OUT),
    ("OP-EGR-03", "Cotizaciones previsionales", OPERATING_EXPENSE, OUT),
    ("OP-EGR-04", "Arriendo", OPERATING_EXPENSE, OUT),
    ("OP-EGR-05", "Leasing equipo RM", OPERATING_EXPENSE, OUT),
    ("OP-EGR-06", "Mantención equipo RM", OPERATING_EXPENSE, OUT),
    ("OP-EGR-07", "Insumos clínicos", OPERATING_EXPENSE, OUT),
    ("OP-EGR-08", "Contraste y medicamentos", OPERATING_EXPENSE, OUT),
    ("OP-EGR-09", "Energía eléctrica", OPERATING_EXPENSE, OUT),
    ("OP-EGR-10", "Agua", OPERATING_EXPENSE, OUT),
    ("OP-EGR-11", "Telefonía e internet", OPERATING_EXPENSE, OUT),
    ("OP-EGR-12", "Licencias RIS/PACS y software", OPERATING_EXPENSE, OUT),
    ("OP-EGR-13", "Aseo", OPERATING_EXPENSE, OUT),
    ("OP-EGR-14", "Seguros", OPERATING_EXPENSE, OUT),
    ("OP-EGR-15", "Comisiones bancarias y Transbank", OPERATING_EXPENSE, OUT),
    ("OP-EGR-16", "Marketing y publicidad", OPERATING_EXPENSE, OUT),
    ("OP-EGR-17", "Traslados y viáticos", OPERATING_EXPENSE, OUT),
    ("OP-EGR-18", "Servicios profesionales", OPERATING_EXPENSE, OUT),
    ("OP-EGR-19", "Impuestos, permisos y patentes", OPERATING_EXPENSE, OUT),
    ("OP-EGR-20", "Otros egresos operacionales", OPERATING_EXPENSE, OUT),

    # ── Inversión · Egreso (4) ─────────────────────────────────────────────
    ("INV-EGR-01", "Obras y habilitación", INVESTMENT_EXPENSE, OUT),
    ("INV-EGR-02", "Equipamiento clínico", INVESTMENT_EXPENSE, OUT),
    ("INV-EGR-03", "Mobiliario", INVESTMENT_EXPENSE, OUT),
    ("INV-EGR-04", "Tecnología y sistemas", INVESTMENT_EXPENSE, OUT),

    # ── Financiamiento · Ingreso (2) ───────────────────────────────────────
    ("FIN-ING-01", "Aportes de socios", FINANCING_REVENUE, IN),
    ("FIN-ING-02", "Créditos recibidos", FINANCING_REVENUE, IN),

    # ── Financiamiento · Egreso (3) ────────────────────────────────────────
    ("FIN-EGR-01", "Pago de capital de créditos", FINANCING_EXPENSE, OUT),
    ("FIN-EGR-02", "Intereses y gastos financieros", FINANCING_EXPENSE, OUT),
    ("FIN-EGR-03", "Retiros y dividendos", FINANCING_EXPENSE, OUT),
]


class Command(BaseCommand):
    help = "Siembra las 34 categorías del presupuesto de caja."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        updated = 0

        for order, (code, name, block, sign) in enumerate(CATEGORIES, start=1):
            category, was_created = BudgetCategory.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "block": block,
                    "sign": sign,
                    "display_order": order,
                    "is_active": True,
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Categorías de presupuesto: {created} creadas, {updated} actualizadas "
                f"({len(CATEGORIES)} en total)."
            )
        )
