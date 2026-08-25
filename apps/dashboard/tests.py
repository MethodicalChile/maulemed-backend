"""
Tests para la app dashboard:
- dashboard_summary: retorna secciones según rol
- dashboard_inventory: datos de inventario
- dashboard_purchasing: datos de compras
- dashboard_finance: datos financieros
- Permisos: IsAuthenticated (datos se filtran por rol)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.organizations.models import Organization, LegalEntity, Branch

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user(username, password, is_superuser=False):
    u = User.objects.create_user(
        username=username, password=password,
        is_superuser=is_superuser, is_staff=is_superuser
    )
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def assign_role(user, role_code, branch=None, le=None):
    role, _ = Role.objects.get_or_create(
        code=role_code, defaults={"name": role_code, "is_active": True}
    )
    UserRoleAssignment.objects.create(
        user=user, role=role, branch=branch, legal_entity=le, is_active=True
    )


class BaseDashboardTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_user("dashboardadmin", "dashpass", is_superuser=True)
        self.finanzas_user = create_user("finanzas_dash", "finpass")
        assign_role(self.finanzas_user, "FINANZAS")
        self.bodeguero = create_user("bode_dash", "bodepass")
        assign_role(self.bodeguero, "BODEGUERO")
        self.doctor = create_user("doctor_dash", "docpass")
        assign_role(self.doctor, "DOCTOR")

    def _auth(self, username, password):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def _auth_admin(self):
        self._auth("dashboardadmin", "dashpass")


# ---------------------------------------------------------------------------
# Tests de dashboard_summary
# ---------------------------------------------------------------------------

class DashboardSummaryTests(BaseDashboardTest):

    def test_admin_obtiene_todas_las_secciones(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("inventory", data)
        self.assertIn("purchasing", data)
        self.assertIn("finance", data)
        self.assertIn("unread_notifications", data)

    def test_finanzas_obtiene_seccion_finance(self):
        self._auth("finanzas_dash", "finpass")
        response = self.client.get("/api/dashboard/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        # Finance debe estar disponible
        self.assertIsNotNone(data.get("finance"))

    def test_doctor_obtiene_seccion_inventory(self):
        self._auth("doctor_dash", "docpass")
        response = self.client.get("/api/dashboard/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        # Doctor puede ver inventario pero no finanzas
        self.assertIsNotNone(data.get("inventory"))
        self.assertIsNone(data.get("finance"))

    def test_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/dashboard/summary/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_estructura_seccion_inventory(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/summary/")
        data = response.json()["data"]
        inv = data.get("inventory")
        self.assertIn("stock_items", inv)
        self.assertIn("low_stock_count", inv)
        self.assertIn("expiring_soon_count", inv)
        self.assertIn("expired_count", inv)

    def test_estructura_seccion_purchasing(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/summary/")
        data = response.json()["data"]
        purch = data.get("purchasing")
        self.assertIn("supply_requests_total", purch)
        self.assertIn("purchase_orders_total", purch)
        self.assertIn("pending_receipts", purch)

    def test_estructura_seccion_finance(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/summary/")
        data = response.json()["data"]
        fin = data.get("finance")
        self.assertIn("supplier_invoices_total", fin)
        self.assertIn("total_invoiced_amount", fin)
        self.assertIn("total_paid_amount", fin)


# ---------------------------------------------------------------------------
# Tests de dashboard_inventory
# ---------------------------------------------------------------------------

class DashboardInventoryTests(BaseDashboardTest):

    def test_admin_obtiene_dashboard_inventory(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/inventory/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("stock_items", data)
        self.assertIn("total_quantity", data)
        self.assertIn("lots_total", data)
        self.assertIn("lots_expiring_soon", data)
        self.assertIn("lots_expired", data)

    def test_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/dashboard/inventory/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Tests de dashboard_purchasing
# ---------------------------------------------------------------------------

class DashboardPurchasingTests(BaseDashboardTest):

    def test_admin_obtiene_dashboard_purchasing(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/purchasing/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("supply_requests_by_status", data)
        self.assertIn("purchase_orders_by_status", data)
        self.assertIn("purchase_receipts_by_status", data)
        self.assertIn("purchase_orders_total_amount", data)

    def test_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/dashboard/purchasing/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Tests de dashboard_finance
# ---------------------------------------------------------------------------

class DashboardFinanceTests(BaseDashboardTest):

    def test_admin_obtiene_dashboard_finance(self):
        self._auth_admin()
        response = self.client.get("/api/dashboard/finance/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("invoices_by_status", data)
        self.assertIn("total_invoiced_amount", data)
        self.assertIn("total_paid_amount", data)
        self.assertIn("budget_amount_total", data)

    def test_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/dashboard/finance/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Tests de dashboard/views.py líneas 93-104
# Cubre: la excepción capturada en el loop de low_stock_count cuando
# el BranchProduct.critical_stock es None/0 → threshold None → continue
# ---------------------------------------------------------------------------

class DashboardLowStockLoopTests(TestCase):
    """
    Cubre las ramas del loop de low_stock_count en dashboard_summary:
    - BranchProduct sin threshold (None) → continue
    - stock.available_quantity > threshold → no cuenta
    - stock.available_quantity <= threshold → cuenta
    """

    def setUp(self):
        self.client = APIClient()
        from apps.organizations.models import Organization, Branch
        from apps.products.models import ProductCategory, UnitOfMeasure, Product, BranchProduct
        from apps.inventory.models import Warehouse, InventoryStock
        from apps.accounts.models import Role, UserRoleAssignment, UserProfile

        org = Organization.objects.create(name="DashLSOrg", is_active=True)
        self.branch = Branch.objects.create(organization=org, name="DashLSBranch", code="DLSB01", is_active=True)
        cat, _ = ProductCategory.objects.get_or_create(name="Cat DashLS")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_DLS", defaults={"name": "U"})

        # Producto 1: con BranchProduct con threshold → stock CRÍTICO
        self.prod_critico = Product.objects.create(name="Prod Critico DLS", category=cat, unit=unit, is_active=True)
        BranchProduct.objects.create(
            branch=self.branch, product=self.prod_critico,
            critical_stock=Decimal("5"), min_stock=Decimal("10"), is_active=True
        )
        self.wh = Warehouse.objects.create(branch=self.branch, name="W DashLS", is_active=True)
        InventoryStock.objects.create(
            warehouse=self.wh, product=self.prod_critico,
            quantity=Decimal("2"), reserved_quantity=Decimal("0")
        )

        # Producto 2: sin BranchProduct → skip
        self.prod_sin_bp = Product.objects.create(name="Prod Sin BP DLS", category=cat, unit=unit, is_active=True)
        InventoryStock.objects.create(
            warehouse=self.wh, product=self.prod_sin_bp,
            quantity=Decimal("100"), reserved_quantity=Decimal("0")
        )

        # Producto 3: BranchProduct con threshold=0 (None efectivo) → skip
        self.prod_threshold_none = Product.objects.create(name="Prod Threshold None", category=cat, unit=unit, is_active=True)
        BranchProduct.objects.create(
            branch=self.branch, product=self.prod_threshold_none,
            critical_stock=Decimal("0"), min_stock=Decimal("0"), is_active=True
        )
        InventoryStock.objects.create(
            warehouse=self.wh, product=self.prod_threshold_none,
            quantity=Decimal("1"), reserved_quantity=Decimal("0")
        )

        # Usuario con scope en esta branch
        self.bodeguero = User.objects.create_user(username="dash_ls_bode", password="pass")
        role_b, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        UserRoleAssignment.objects.create(user=self.bodeguero, role=role_b, branch=self.branch, is_active=True)
        UserProfile.objects.get_or_create(user=self.bodeguero, defaults={})

    def _auth(self):
        resp = self.client.post("/api/auth/login/", {"username": "dash_ls_bode", "password": "pass"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_summary_cuenta_stock_critico(self):
        self._auth()
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        inv = resp.json()["data"]["inventory"]
        # Debe contar al menos 1 item crítico
        self.assertGreaterEqual(inv["low_stock_count"], 1)

    def test_summary_inventory_tiene_contadores_correctos(self):
        self._auth()
        resp = self.client.get("/api/dashboard/summary/")
        inv = resp.json()["data"]["inventory"]
        self.assertGreaterEqual(inv["stock_items"], 1)
        self.assertIn("expiring_soon_count", inv)
        self.assertIn("expired_count", inv)


# ---------------------------------------------------------------------------
# Tests adicionales de dashboard — usuarios sin scopes ven datos limitados
# ---------------------------------------------------------------------------

class DashboardScopeTests(BaseDashboardTest):

    def test_usuario_sin_roles_ve_solo_unread_notifications(self):
        """Usuario autenticado sin ningún rol ve el summary pero sin secciones."""
        user_norole = create_user("norole_dash", "pass")
        resp = self.client.post("/api/auth/login/", {"username": "norole_dash", "password": "pass"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        # Sin roles → no tiene secciones de inventario/purchasing/finance
        self.assertIsNone(data["inventory"])
        self.assertIsNone(data["purchasing"])
        self.assertIsNone(data["finance"])
        self.assertIn("unread_notifications", data)


# ---------------------------------------------------------------------------
# Tablero ejecutivo
# ---------------------------------------------------------------------------

class ExecutiveCalendarTests(TestCase):
    """El calendario del período: es lo que decide cuántos puntos tiene la serie."""

    def test_shift_month_cruza_el_año(self):
        from datetime import date
        from apps.dashboard.executive import shift_month

        self.assertEqual(shift_month(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(shift_month(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(shift_month(date(2026, 6, 1), -18), date(2024, 12, 1))

    def test_month_range_devuelve_todos_los_meses_pedidos(self):
        from apps.dashboard.executive import month_range

        meses = month_range(12)

        self.assertEqual(len(meses), 12)
        self.assertTrue(all(m.day == 1 for m in meses))
        self.assertEqual(meses, sorted(meses))

    def test_delta_pct_sin_base_devuelve_none(self):
        """
        Un "+100 %" porque el mes anterior fue cero es ruido, no información.
        """
        from apps.dashboard.executive import _delta_pct

        self.assertIsNone(_delta_pct(1000, 0))
        self.assertIsNone(_delta_pct(1000, None))
        self.assertEqual(_delta_pct(150, 100), 50.0)
        self.assertEqual(_delta_pct(50, 100), -50.0)


class ExecutiveDashboardTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="ExecOrg", is_active=True)
        self.le = LegalEntity.objects.create(
            organization=self.org, name="ExecLE", rut="76123999-1", is_active=True
        )
        self.branch = Branch.objects.create(
            organization=self.org, legal_entity=self.le, name="ExecBranch", code="EB01"
        )

    def _auth(self, username="execadmin", superuser=True, role=None):
        user = create_user(username, "pass", is_superuser=superuser)
        if role:
            assign_role(user, role, branch=self.branch)
        self.client.force_authenticate(user=user)
        return user

    def test_admin_recibe_todos_los_bloques(self):
        self._auth()

        resp = self.client.get("/api/dashboard/executive/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        d = resp.json()["data"]

        for bloque in ("revenue", "budget", "purchasing", "inventory"):
            self.assertIsNotNone(d[bloque], f"falta {bloque}")

        self.assertTrue(d["access"]["finance"])

    def test_la_serie_trae_un_punto_por_mes_aunque_no_haya_datos(self):
        """
        Una serie con huecos se dibuja mal y hace parecer que el negocio se
        detuvo. Los meses sin movimiento van en cero, no ausentes.
        """
        self._auth("exec_serie")

        resp = self.client.get("/api/dashboard/executive/?months=6")
        d = resp.json()["data"]

        self.assertEqual(len(d["period"]["labels"]), 6)
        self.assertEqual(len(d["revenue"]["trend"]), 6)
        self.assertTrue(all(p["revenue"] == 0 for p in d["revenue"]["trend"]))

    def test_months_se_acota_a_un_rango_razonable(self):
        self._auth("exec_rango")

        self.assertEqual(
            self.client.get("/api/dashboard/executive/?months=999").json()["data"][
                "period"
            ]["months"],
            36,
        )
        self.assertEqual(
            self.client.get("/api/dashboard/executive/?months=0").json()["data"][
                "period"
            ]["months"],
            1,
        )
        self.assertEqual(
            self.client.get("/api/dashboard/executive/?months=abc").json()["data"][
                "period"
            ]["months"],
            12,
        )

    def test_sin_permiso_el_bloque_es_none_y_no_una_lista_vacia(self):
        """
        La interfaz necesita distinguir "no puedes ver esto" de "no hay nada":
        decirle "sin datos" a quien no tiene acceso es mentirle.
        """
        self._auth("exec_secretaria", superuser=False, role="SECRETARIA")

        resp = self.client.get("/api/dashboard/executive/")
        d = resp.json()["data"]

        self.assertFalse(d["access"]["finance"])
        self.assertIsNone(d["revenue"])
        self.assertIsNone(d["budget"])

    def test_requiere_autenticacion(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/dashboard/executive/")
        self.assertIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_tendencia_y_kpi_reflejan_el_ingreso_cargado(self):
        from datetime import date
        from django.utils import timezone
        from apps.revenue.models import Financier, RevenueEntry

        self._auth("exec_datos")

        financiador = Financier.objects.create(
            code="F-TEST", name="Financiador", financier_type=Financier.TYPE_FONASA
        )
        hoy = timezone.localdate()
        mes = date(hoy.year, hoy.month, 1)

        for monto in (Decimal("100000"), Decimal("50000")):
            RevenueEntry.objects.create(
                legal_entity=self.le,
                financier=financiador,
                service_date=mes,
                gross_amount=monto,
                net_amount=monto,
            )

        d = self.client.get("/api/dashboard/executive/?months=3").json()["data"]

        self.assertEqual(d["revenue"]["trend"][-1]["revenue"], 150000.0)
        self.assertEqual(d["kpis"]["revenue_accrued"]["value"], 150000.0)
        self.assertEqual(len(d["kpis"]["revenue_accrued"]["sparkline"]), 3)

        sociedades = d["revenue"]["by_legal_entity"]
        self.assertEqual(len(sociedades), 1)
        self.assertEqual(sociedades[0]["amount"], 150000.0)

    def test_el_pipeline_agrupa_los_estados_en_cuatro_fases(self):
        """
        Ocho estados de solicitud y diez de orden no se pueden pintar: más de
        siete clases con significado dejan de distinguirse.
        """
        self._auth("exec_pipeline")

        d = self.client.get("/api/dashboard/executive/").json()["data"]
        grupos = d["purchasing"]["purchase_orders"]

        self.assertEqual(len(grupos), 5)
        self.assertEqual(
            [g["key"] for g in grupos],
            ["draft", "in_review", "approved", "closed", "rejected"],
        )

    def test_stock_bajo_umbral_usa_branch_product(self):
        """
        El umbral que manda es el de BranchProduct, que es el que consulta la
        alerta — no el min_level de InventoryStock, que nadie lee.
        """
        from apps.inventory.models import InventoryStock, Warehouse
        from apps.products.models import BranchProduct, Product, ProductCategory, UnitOfMeasure

        self._auth("exec_stock")

        categoria = ProductCategory.objects.create(name="Cat")
        unidad = UnitOfMeasure.objects.create(code="UN", name="Unidad")
        producto = Product.objects.create(
            category=categoria, unit=unidad, name="Insumo"
        )
        bodega = Warehouse.objects.create(branch=self.branch, name="Bodega")

        BranchProduct.objects.create(
            branch=self.branch,
            product=producto,
            min_stock=Decimal("50"),
            critical_stock=Decimal("20"),
            is_active=True,
        )
        InventoryStock.objects.create(
            warehouse=bodega,
            product=producto,
            quantity=Decimal("10"),
            min_level=Decimal("0"),  # el campo que nadie consulta
        )

        d = self.client.get("/api/dashboard/executive/").json()["data"]

        self.assertEqual(d["inventory"]["low_stock_count"], 1)
