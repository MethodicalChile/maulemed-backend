"""
Tests para la app finance:
- SupplierInvoice: CRUD, validaciones (due_date >= issue_date, unique supplier+invoice_number)
- Payment: CRUD, validaciones (cheque requiere número, amount > 0)
- Budget: CRUD, validaciones (consumed <= budget, unique scope)
- Permisos CanManageFinance (ADMIN/GERENTE/FINANZAS)
"""
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.organizations.models import Organization, LegalEntity, Branch
from apps.suppliers.models import Supplier
from apps.products.models import ProductCategory
from apps.finance.models import SupplierInvoice, Payment, Budget

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_superuser(username="finadmin", password="finpass"):
    u = User.objects.create_user(username=username, password=password, is_superuser=True, is_staff=True)
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def make_user_role(username, password, role_code):
    user = User.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(code=role_code, defaults={"name": role_code, "is_active": True})
    UserRoleAssignment.objects.create(user=user, role=role, is_active=True)
    UserProfile.objects.get_or_create(user=user, defaults={})
    return user


def setup_org():
    org = Organization.objects.create(name="FinOrg", is_active=True)
    le = LegalEntity.objects.create(organization=org, name="FinLE", rut="76900001-1", is_active=True)
    branch = Branch.objects.create(organization=org, legal_entity=le, name="FinBranch", code="FB001", is_active=True)
    return org, le, branch


def make_supplier(name="ProvFin", rut="76900999-9"):
    return Supplier.objects.create(name=name, rut=rut, is_active=True)


def make_invoice(supplier, le, invoice_number="F-001", total=Decimal("1190")):
    return SupplierInvoice.objects.create(
        supplier=supplier,
        legal_entity=le,
        invoice_number=invoice_number,
        issue_date=date.today(),
        net_amount=Decimal("1000"),
        tax_amount=Decimal("190"),
        total_amount=total,
        status=SupplierInvoice.STATUS_RECEIVED,
    )


class BaseFinanceTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = make_superuser()
        self.org, self.le, self.branch = setup_org()
        self.supplier = make_supplier()

    def _auth(self, username="finadmin", password="finpass"):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def _auth_admin(self):
        self._auth()


# ---------------------------------------------------------------------------
# Tests de SupplierInvoice
# ---------------------------------------------------------------------------

class SupplierInvoiceModelTests(TestCase):

    def setUp(self):
        _, self.le, _ = setup_org()
        self.supplier = make_supplier(rut="76901000-1")

    def test_clean_falla_si_vencimiento_antes_de_emision(self):
        invoice = SupplierInvoice(
            supplier=self.supplier,
            legal_entity=self.le,
            invoice_number="INV-ERR",
            issue_date=date.today(),
            due_date=date.today() - timedelta(days=1),
            total_amount=Decimal("100"),
        )
        with self.assertRaises(ValidationError):
            invoice.clean()

    def test_clean_ok_cuando_vencimiento_despues_emision(self):
        invoice = SupplierInvoice(
            supplier=self.supplier,
            legal_entity=self.le,
            invoice_number="INV-OK",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            total_amount=Decimal("100"),
        )
        # No debe lanzar excepción
        invoice.clean()

    def test_str_factura(self):
        invoice = SupplierInvoice(
            invoice_number="F-TEST",
        )
        invoice.supplier = self.supplier
        self.assertIn("F-TEST", str(invoice))

    def test_unique_supplier_invoice_number(self):
        make_invoice(self.supplier, self.le, invoice_number="DUP-001")
        with self.assertRaises(Exception):
            make_invoice(self.supplier, self.le, invoice_number="DUP-001")


class SupplierInvoiceAPITests(BaseFinanceTest):

    def test_crear_factura(self):
        self._auth_admin()
        response = self.client.post(
            "/api/supplier-invoices/",
            {
                "supplier": self.supplier.id,
                "legal_entity": self.le.id,
                "invoice_number": "API-001",
                "issue_date": str(date.today()),
                "net_amount": "1000.00",
                "tax_amount": "190.00",
                "total_amount": "1190.00",
                "status": SupplierInvoice.STATUS_RECEIVED,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["data"]["invoice_number"], "API-001")

    def test_listar_facturas(self):
        self._auth_admin()
        response = self.client.get("/api/supplier-invoices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_actualizar_factura(self):
        self._auth_admin()
        inv = make_invoice(self.supplier, self.le, invoice_number="UPD-001")
        response = self.client.patch(
            f"/api/supplier-invoices/{inv.uuid}/",
            {"status": SupplierInvoice.STATUS_VALIDATED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["status"], SupplierInvoice.STATUS_VALIDATED)

    def test_soft_delete_factura(self):
        self._auth_admin()
        inv = make_invoice(self.supplier, self.le, invoice_number="DEL-001")
        response = self.client.delete(f"/api/supplier-invoices/{inv.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        inv.refresh_from_db()
        self.assertIsNotNone(inv.deleted_at)

    def test_sin_autenticacion_no_puede_listar(self):
        response = self.client.get("/api/supplier-invoices/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_usuario_sin_permiso_finanzas_no_puede_ver_facturas(self):
        # Bodeguero no tiene permiso CanManageFinance
        bodeguero = make_user_role("bode_fin", "pass123", "BODEGUERO")
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "bode_fin", "password": "pass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')
        response = self.client.get("/api/supplier-invoices/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Tests de Payment
# ---------------------------------------------------------------------------

class PaymentModelTests(TestCase):

    def setUp(self):
        _, self.le, _ = setup_org()
        self.supplier = make_supplier(rut="76902000-2")
        self.invoice = make_invoice(self.supplier, self.le, invoice_number="PAY-F001")

    def test_clean_falla_si_pago_cheque_sin_numero(self):
        payment = Payment(
            supplier_invoice=self.invoice,
            legal_entity=self.le,
            payment_method=Payment.METHOD_CHECK,
            amount=Decimal("100"),
            check_number=None,
        )
        with self.assertRaises(ValidationError):
            payment.clean()

    def test_clean_ok_si_pago_cheque_con_numero(self):
        payment = Payment(
            supplier_invoice=self.invoice,
            legal_entity=self.le,
            payment_method=Payment.METHOD_CHECK,
            amount=Decimal("100"),
            check_number="CHQ-12345",
        )
        payment.clean()  # No debe lanzar excepción

    def test_str_pago(self):
        payment = Payment(payment_method="TRANSFERENCIA", amount=Decimal("500"))
        self.assertIn("TRANSFERENCIA", str(payment))


class PaymentAPITests(BaseFinanceTest):

    def setUp(self):
        super().setUp()
        self.invoice = make_invoice(self.supplier, self.le, invoice_number="PAY-API-001")

    def test_crear_pago(self):
        self._auth_admin()
        response = self.client.post(
            "/api/payments/",
            {
                "supplier_invoice": self.invoice.id,
                "legal_entity": self.le.id,
                "payment_method": Payment.METHOD_TRANSFER,
                "amount": "1190.00",
                "payment_date": str(date.today()),
                "status": Payment.STATUS_PENDING,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_listar_pagos(self):
        self._auth_admin()
        response = self.client.get("/api/payments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Tests de Budget
# ---------------------------------------------------------------------------

class BudgetModelTests(TestCase):

    def setUp(self):
        _, self.le, _ = setup_org()

    def test_available_amount_property(self):
        budget = Budget(
            legal_entity=self.le,
            period_year=2024,
            period_month=6,
            budget_amount=Decimal("10000"),
            consumed_amount=Decimal("3000"),
        )
        self.assertEqual(budget.available_amount, Decimal("7000"))

    def test_sobregiro_se_registra_y_no_bloquea(self):
        """
        El sobregiro tiene que poder existir en el sistema.

        Antes clean() lo rechazaba. Bloquearlo obligaba a dejar la compra fuera
        de la plataforma, que es peor que verla desviada: el presupuesto dejaba
        de reflejar el gasto real justo cuando más importaba.
        """
        budget = Budget(
            legal_entity=self.le,
            period_year=2024,
            period_month=6,
            budget_amount=Decimal("1000"),
            consumed_amount=Decimal("2000"),
        )

        budget.clean()  # no levanta

        self.assertEqual(budget.available_amount, Decimal("-1000"))
        self.assertEqual(budget.deviation_amount, Decimal("1000"))
        self.assertTrue(budget.is_overrun)

    def test_disponible_descuenta_comprometido_y_consumido(self):
        """
        Entre aprobar la orden y recibir la factura pueden pasar semanas. Si el
        saldo no descontara el comprometido, dos compras seguidas verían el
        mismo disponible.
        """
        budget = Budget(
            legal_entity=self.le,
            period_year=2024,
            period_month=6,
            budget_amount=Decimal("10000"),
            committed_amount=Decimal("2500"),
            consumed_amount=Decimal("3000"),
        )

        self.assertEqual(budget.used_amount, Decimal("5500"))
        self.assertEqual(budget.available_amount, Decimal("4500"))
        self.assertFalse(budget.is_overrun)

    def test_str_budget(self):
        # Crear org/le dedicados para evitar colisión de RUT con setUp
        from apps.organizations.models import Organization, LegalEntity
        import uuid as _uuid
        org = Organization.objects.create(name=f"StrBudgetOrg-{_uuid.uuid4().hex[:6]}", is_active=True)
        le = LegalEntity.objects.create(
            organization=org,
            name=f"StrBudgetLE-{_uuid.uuid4().hex[:6]}",
            rut=f"76-{_uuid.uuid4().int % 900000 + 100000}-K",
            is_active=True,
        )
        budget = Budget(legal_entity=le, period_year=2024, period_month=6)
        self.assertIn("6/2024", str(budget))


class BudgetAPITests(BaseFinanceTest):

    def test_crear_presupuesto(self):
        self._auth_admin()
        response = self.client.post(
            "/api/budgets/",
            {
                "legal_entity": self.le.id,
                "period_year": 2024,
                "period_month": 6,
                "budget_amount": "50000.00",
                "consumed_amount": "0.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_listar_presupuestos(self):
        self._auth_admin()
        response = self.client.get("/api/budgets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unique_constraint_presupuesto(self):
        self._auth_admin()
        Budget.objects.create(
            legal_entity=self.le,
            period_year=2024,
            period_month=7,
            budget_amount=Decimal("10000"),
            consumed_amount=Decimal("0"),
        )
        response = self.client.post(
            "/api/budgets/",
            {
                "legal_entity": self.le.id,
                "period_year": 2024,
                "period_month": 7,
                "budget_amount": "5000.00",
                "consumed_amount": "0.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_soft_delete_presupuesto(self):
        self._auth_admin()
        budget = Budget.objects.create(
            legal_entity=self.le,
            period_year=2024,
            period_month=8,
            budget_amount=Decimal("5000"),
            consumed_amount=Decimal("0"),
        )
        response = self.client.delete(f"/api/budgets/{budget.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        budget.refresh_from_db()
        self.assertIsNotNone(budget.deleted_at)


# ---------------------------------------------------------------------------
# finance/serializers.py línea 80: BudgetSerializer.validate() en UPDATE
# Cubre qs.exclude(pk=self.instance.pk) para actualizar presupuesto existente
# ---------------------------------------------------------------------------

class BudgetSerializerUpdateTests(BaseFinanceTest):

    def test_actualizar_presupuesto_propio_no_falla_unicidad(self):
        """Línea 80: al actualizar, excluye el pk propio para no fallar unique."""
        self._auth_admin()
        from apps.finance.models import Budget
        budget = Budget.objects.create(
            legal_entity=self.le,
            period_year=2024,
            period_month=9,
            budget_amount=Decimal("5000"),
            consumed_amount=Decimal("0"),
        )
        # Actualizar notas (sin cambiar el scope) → no debe fallar validación
        resp = self.client.patch(
            f"/api/budgets/{budget.uuid}/",
            {"budget_amount": "8000.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["data"]["budget_amount"], "8000.00")

    def test_actualizar_presupuesto_con_scope_diferente_ok(self):
        """Actualizar periodo de un presupuesto (scope diferente) es válido."""
        self._auth_admin()
        from apps.finance.models import Budget
        budget = Budget.objects.create(
            legal_entity=self.le,
            period_year=2024,
            period_month=10,
            budget_amount=Decimal("3000"),
            consumed_amount=Decimal("0"),
        )
        resp = self.client.patch(
            f"/api/budgets/{budget.uuid}/",
            {"notes": "Actualizado"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# C1 · Servicios de presupuesto
# ---------------------------------------------------------------------------

class BudgetCategorySeedTests(TestCase):
    """Las categorías son las de la planilla, no una taxonomía inventada."""

    def test_seed_crea_las_34_categorias_de_la_planilla(self):
        from django.core.management import call_command
        from apps.finance.models import BudgetCategory

        call_command("seed_budget_categories", verbosity=0)

        self.assertEqual(BudgetCategory.objects.count(), 34)

        bloques = {
            BudgetCategory.BLOCK_OPERATING_REVENUE: 5,
            BudgetCategory.BLOCK_OPERATING_EXPENSE: 20,
            BudgetCategory.BLOCK_INVESTMENT_EXPENSE: 4,
            BudgetCategory.BLOCK_FINANCING_REVENUE: 2,
            BudgetCategory.BLOCK_FINANCING_EXPENSE: 3,
        }
        for block, esperado in bloques.items():
            self.assertEqual(
                BudgetCategory.objects.filter(block=block).count(),
                esperado,
                f"bloque {block}",
            )

        # Nombre literal de la planilla, no una versión "corregida".
        self.assertTrue(
            BudgetCategory.objects.filter(
                name="Licencias RIS/PACS y software"
            ).exists()
        )

    def test_seed_es_idempotente(self):
        from django.core.management import call_command
        from apps.finance.models import BudgetCategory

        call_command("seed_budget_categories", verbosity=0)
        call_command("seed_budget_categories", verbosity=0)

        self.assertEqual(BudgetCategory.objects.count(), 34)


class BudgetServiceTests(TestCase):

    def setUp(self):
        from apps.organizations.models import CostCenter
        from apps.finance.models import BudgetCategory

        self.org, self.le, self.branch = setup_org()
        self.cost_center = CostCenter.objects.create(
            legal_entity=self.le,
            branch=self.branch,
            code="CC-01",
            name="Imagenología",
            is_active=True,
        )
        self.category = BudgetCategory.objects.create(
            code="OP-EGR-07",
            name="Insumos clínicos",
            block=BudgetCategory.BLOCK_OPERATING_EXPENSE,
            sign=BudgetCategory.SIGN_OUTFLOW,
        )

    def _budget(self, **kwargs):
        defaults = dict(
            legal_entity=self.le,
            branch=self.branch,
            cost_center=self.cost_center,
            budget_category=self.category,
            period_year=2026,
            period_month=8,
            budget_amount=Decimal("1000000"),
        )
        defaults.update(kwargs)
        return Budget.objects.create(**defaults)

    def test_get_budget_for_cae_al_alcance_mas_general(self):
        """
        Si el centro de costo no tiene línea propia, gobierna la de la sociedad.
        Exigir coincidencia exacta dejaría sin control casi todo gasto al
        principio, cuando los centros de costo recién se están cargando.
        """
        from apps.finance.services import get_budget_for

        general = self._budget(branch=None, cost_center=None)

        encontrado = get_budget_for(
            legal_entity=self.le,
            branch=self.branch,
            cost_center=self.cost_center,
            budget_category=self.category,
            period_year=2026,
            period_month=8,
        )
        self.assertEqual(encontrado, general)

    def test_get_budget_for_prefiere_el_mas_especifico(self):
        from apps.finance.services import get_budget_for

        self._budget(branch=None, cost_center=None)
        especifico = self._budget()

        encontrado = get_budget_for(
            legal_entity=self.le,
            branch=self.branch,
            cost_center=self.cost_center,
            budget_category=self.category,
            period_year=2026,
            period_month=8,
        )
        self.assertEqual(encontrado, especifico)

    def test_commit_y_consume_no_cuentan_dos_veces(self):
        """
        Comprometer al aprobar y consumir al facturar tiene que dar el mismo
        saldo que consumir una sola vez: la factura materializa el compromiso,
        no se suma a él.
        """
        from apps.finance.services import commit_budget, consume_budget

        budget = self._budget()

        commit_budget(budget=budget, amount=Decimal("300000"))
        budget.refresh_from_db()
        self.assertEqual(budget.available_amount, Decimal("700000"))

        consume_budget(budget=budget, amount=Decimal("300000"))
        budget.refresh_from_db()
        self.assertEqual(budget.committed_amount, Decimal("0"))
        self.assertEqual(budget.consumed_amount, Decimal("300000"))
        self.assertEqual(budget.available_amount, Decimal("700000"))

    def test_release_no_deja_comprometido_negativo(self):
        from apps.finance.services import commit_budget, release_commitment

        budget = self._budget()
        commit_budget(budget=budget, amount=Decimal("100000"))

        release_commitment(budget=budget, amount=Decimal("500000"))
        budget.refresh_from_db()

        self.assertEqual(budget.committed_amount, Decimal("0"))

    def test_servicios_toleran_presupuesto_inexistente(self):
        """
        Sin presupuesto cargado la compra tiene que poder seguir. El control
        informa; no es una precondición de la operación clínica.
        """
        from apps.finance.services import (
            commit_budget,
            consume_budget,
            release_commitment,
        )

        self.assertIsNone(commit_budget(budget=None, amount=Decimal("100")))
        self.assertIsNone(consume_budget(budget=None, amount=Decimal("100")))
        self.assertIsNone(release_commitment(budget=None, amount=Decimal("100")))

    def test_encuentra_el_presupuesto_de_sociedad_y_centro_sin_sucursal(self):
        """
        La forma más habitual de cargar el presupuesto: por sociedad y centro
        de costo, sin abrir por sucursal.

        Si la búsqueda soltara el centro de costo antes que la sucursal, este
        presupuesto no se encontraría nunca y el control quedaría mudo — que es
        lo que pasaba al levantar la app con datos reales.
        """
        from apps.finance.services import get_budget_for

        esperado = self._budget(branch=None)

        encontrado = get_budget_for(
            legal_entity=self.le,
            branch=self.branch,
            cost_center=self.cost_center,
            budget_category=self.category,
            period_year=2026,
            period_month=8,
        )
        self.assertEqual(encontrado, esperado)

    def test_sin_presupuesto_la_orden_no_declara_compromiso(self):
        """
        Anotar un compromiso sin presupuesto haría que la orden declarara algo
        que no existe en ninguna parte.
        """
        from apps.finance.services import commit_purchase_order
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import generate_purchase_order_number
        from apps.suppliers.models import Supplier

        proveedor = Supplier.objects.create(name="Prov", rut="99111222-3")
        po = PurchaseOrder.objects.create(
            order_number=generate_purchase_order_number(),
            supplier=proveedor,
            branch=self.branch,
            legal_entity=self.le,
            cost_center=self.cost_center,
            total_amount=Decimal("50000"),
        )

        self.assertIsNone(commit_purchase_order(po))

        po.refresh_from_db()
        self.assertEqual(po.budget_committed_amount, Decimal("0"))

    def test_budget_snapshot_sin_presupuesto(self):
        from apps.finance.services import budget_snapshot

        snapshot = budget_snapshot(None)

        self.assertFalse(snapshot["found"])
        self.assertEqual(snapshot["available_amount"], Decimal("0"))


# ---------------------------------------------------------------------------
# C3 · Detalle de la factura de compra
# ---------------------------------------------------------------------------

class SupplierInvoiceItemTests(TestCase):
    """
    "Que las facturas de compra también se pudiesen ir registrando y ojalá
    filtrando por ítem en forma automática" — Jefatura de Adm. y Finanzas.
    """

    def setUp(self):
        from apps.organizations.models import CostCenter
        from apps.finance.models import BudgetCategory
        from apps.products.models import ProductCategory, UnitOfMeasure, Product
        from django.utils import timezone

        self.client = APIClient()
        self.admin = make_superuser("inv_item_admin", "pass")
        self.client.force_authenticate(user=self.admin)

        _, self.le, self.branch = setup_org()
        self.supplier = Supplier.objects.create(
            name="Proveedor Ítems", rut="77123456-7", is_active=True
        )

        self.cc_imagen = CostCenter.objects.create(
            legal_entity=self.le, code="CC-IMG", name="Imagenología", is_active=True
        )
        self.cc_admin = CostCenter.objects.create(
            legal_entity=self.le, code="CC-ADM", name="Administración", is_active=True
        )

        self.categoria = ProductCategory.objects.create(name="Insumos", is_active=True)
        self.unidad = UnitOfMeasure.objects.create(code="UN", name="Unidad")
        self.producto = Product.objects.create(
            category=self.categoria, unit=self.unidad, name="Guantes"
        )

        self.budget_category = BudgetCategory.objects.create(
            code="OP-EGR-07",
            name="Insumos clínicos",
            block=BudgetCategory.BLOCK_OPERATING_EXPENSE,
        )

        hoy = timezone.now()
        self.period = (hoy.year, hoy.month)

    def _factura(self, total=Decimal("100000"), cost_center=None):
        return SupplierInvoice.objects.create(
            supplier=self.supplier,
            legal_entity=self.le,
            branch=self.branch,
            cost_center=cost_center,
            invoice_number=f"F-{SupplierInvoice.objects.count() + 1}",
            total_amount=total,
        )

    def _budget(self, cost_center, amount=Decimal("500000")):
        return Budget.objects.create(
            legal_entity=self.le,
            branch=self.branch,
            cost_center=cost_center,
            budget_category=self.budget_category,
            period_year=self.period[0],
            period_month=self.period[1],
            budget_amount=amount,
        )

    def test_total_del_item_se_deriva_y_no_se_pide(self):
        from apps.finance.models import SupplierInvoiceItem

        factura = self._factura()
        item = SupplierInvoiceItem.objects.create(
            supplier_invoice=factura,
            product=self.producto,
            quantity=Decimal("10"),
            unit_price=Decimal("1500"),
            tax_amount=Decimal("2850"),
        )

        self.assertEqual(item.net_amount, Decimal("15000"))
        self.assertEqual(item.total_amount, Decimal("17850"))
        # Hereda la categoría del producto sin que nadie la escriba.
        self.assertEqual(item.category_id, self.categoria.id)

    def test_factura_con_dos_centros_de_costo_se_imputa_a_cada_uno(self):
        """
        El caso que motiva todo C3: sin detalle, esta factura cargaba entera a
        un solo centro de costo.
        """
        from apps.finance.models import SupplierInvoiceItem
        from apps.finance.services import register_supplier_invoice

        b_imagen = self._budget(self.cc_imagen)
        b_admin = self._budget(self.cc_admin)

        factura = self._factura(total=Decimal("30000"), cost_center=self.cc_imagen)

        SupplierInvoiceItem.objects.create(
            supplier_invoice=factura,
            product=self.producto,
            cost_center=self.cc_imagen,
            budget_category=self.budget_category,
            quantity=Decimal("1"),
            unit_price=Decimal("20000"),
        )
        SupplierInvoiceItem.objects.create(
            supplier_invoice=factura,
            description="Resma de papel",
            cost_center=self.cc_admin,
            budget_category=self.budget_category,
            quantity=Decimal("1"),
            unit_price=Decimal("10000"),
        )

        register_supplier_invoice(factura)

        b_imagen.refresh_from_db()
        b_admin.refresh_from_db()

        self.assertEqual(b_imagen.consumed_amount, Decimal("20000"))
        self.assertEqual(b_admin.consumed_amount, Decimal("10000"))

    def test_sin_detalle_se_imputa_por_la_cabecera(self):
        from apps.finance.services import register_supplier_invoice

        budget = self._budget(self.cc_imagen)
        factura = self._factura(total=Decimal("25000"), cost_center=self.cc_imagen)

        register_supplier_invoice(factura)

        budget.refresh_from_db()
        self.assertEqual(budget.consumed_amount, Decimal("25000"))

    def test_cuadratura_con_tolerancia_de_redondeo(self):
        from apps.finance.models import SupplierInvoiceItem
        from apps.finance.services import invoice_items_match_total

        factura = self._factura(total=Decimal("10000"))
        SupplierInvoiceItem.objects.create(
            supplier_invoice=factura,
            description="Servicio",
            quantity=Decimal("1"),
            unit_price=Decimal("10001"),
        )

        cuadra, suma, diferencia = invoice_items_match_total(factura)

        self.assertTrue(cuadra)
        self.assertEqual(suma, Decimal("10001"))
        self.assertEqual(diferencia, Decimal("1"))

    def test_cuadratura_detecta_diferencia_real(self):
        from apps.finance.models import SupplierInvoiceItem
        from apps.finance.services import invoice_items_match_total

        factura = self._factura(total=Decimal("10000"))
        SupplierInvoiceItem.objects.create(
            supplier_invoice=factura,
            description="Servicio",
            quantity=Decimal("1"),
            unit_price=Decimal("7000"),
        )

        cuadra, _, diferencia = invoice_items_match_total(factura)

        self.assertFalse(cuadra)
        self.assertEqual(diferencia, Decimal("-3000"))

    def test_prefill_items_desde_la_orden(self):
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderItem
        from apps.purchasing.services import generate_purchase_order_number

        po = PurchaseOrder.objects.create(
            order_number=generate_purchase_order_number(),
            supplier=self.supplier,
            branch=self.branch,
            legal_entity=self.le,
            cost_center=self.cc_imagen,
            status=PurchaseOrder.STATUS_RECEIVED,
            total_amount=Decimal("30000"),
        )
        PurchaseOrderItem.objects.create(
            purchase_order=po,
            product=self.producto,
            quantity=Decimal("3"),
            unit_price=Decimal("10000"),
        )

        factura = self._factura(total=Decimal("30000"))
        factura.purchase_order = po
        factura.save()

        resp = self.client.post(
            f"/api/supplier-invoices/{factura.uuid}/prefill-items/"
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(factura.items.count(), 1)

        item = factura.items.first()
        self.assertEqual(item.product_id, self.producto.id)
        self.assertEqual(item.cost_center_id, self.cc_imagen.id)
        self.assertEqual(item.total_amount, Decimal("30000"))

    def test_prefill_sin_orden_devuelve_400(self):
        factura = self._factura()

        resp = self.client.post(
            f"/api/supplier-invoices/{factura.uuid}/prefill-items/"
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_item_sin_producto_ni_descripcion_es_rechazado(self):
        factura = self._factura()

        resp = self.client.post(
            "/api/supplier-invoice-items/",
            {
                "supplier_invoice": factura.id,
                "quantity": "1",
                "unit_price": "1000",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# C4 · Plazos de pago
# ---------------------------------------------------------------------------

class PaymentTermsTests(TestCase):
    """
    payment_terms era texto libre y due_date se llenaba a mano, así que el
    plazo comprometido no era un dato consultable y el indicador "plazo
    promedio entre recepción de la factura y pago" no se podía calcular.
    """

    def setUp(self):
        _, self.le, self.branch = setup_org()
        self.supplier = Supplier.objects.create(
            name="Proveedor 30 días",
            rut="77999888-1",
            payment_terms="30 días fecha factura",
            payment_terms_days=30,
            is_active=True,
        )

    def _factura(self, **kwargs):
        defaults = dict(
            supplier=self.supplier,
            legal_entity=self.le,
            branch=self.branch,
            invoice_number=f"F-{SupplierInvoice.objects.count() + 1}",
            issue_date=date(2026, 8, 1),
            total_amount=Decimal("50000"),
        )
        defaults.update(kwargs)
        return SupplierInvoice.objects.create(**defaults)

    def test_vencimiento_se_deriva_del_plazo_del_proveedor(self):
        factura = self._factura()
        self.assertEqual(factura.due_date, date(2026, 8, 31))

    def test_fecha_escrita_a_mano_manda_sobre_el_plazo(self):
        """Hay facturas que se pactan fuera de la política general."""
        factura = self._factura(due_date=date(2026, 9, 15))
        self.assertEqual(factura.due_date, date(2026, 9, 15))

    def test_proveedor_sin_plazo_no_deriva_nada(self):
        otro = Supplier.objects.create(
            name="Proveedor sin plazo", rut="77111222-3", is_active=True
        )
        factura = self._factura(supplier=otro, invoice_number="F-SIN-PLAZO")
        self.assertIsNone(factura.due_date)

    def test_sin_fecha_de_emision_no_deriva_nada(self):
        factura = self._factura(issue_date=None, invoice_number="F-SIN-EMISION")
        self.assertIsNone(factura.due_date)

    def test_vencida_e_impaga_se_marca(self):
        factura = self._factura(
            issue_date=date(2020, 1, 1),
            invoice_number="F-VIEJA",
            status=SupplierInvoice.STATUS_RECEIVED,
        )

        self.assertTrue(factura.is_overdue)
        self.assertLess(factura.days_to_due, 0)

    def test_vencida_pero_pagada_no_se_marca(self):
        factura = self._factura(
            issue_date=date(2020, 1, 1),
            invoice_number="F-VIEJA-PAGADA",
            status=SupplierInvoice.STATUS_PAID,
        )

        self.assertFalse(factura.is_overdue)
