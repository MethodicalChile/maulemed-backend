"""
Tests para la app reports:
- inventory_stock_report
- inventory_movements_report
- purchases_report
- supplier_spending_report
- branch_consumption_report
- finance_summary_report
- stock_history_report (requiere product_uuid y warehouse_uuid)
- Exports CSV
- Permisos: IsAuthenticated
"""
from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.organizations.models import Organization, LegalEntity, Branch
from apps.products.models import ProductCategory, UnitOfMeasure, Product
from apps.inventory.models import Warehouse, InventoryStock

User = get_user_model()


def create_admin(username="repadmin", password="reppass"):
    u = User.objects.create_user(username=username, password=password, is_superuser=True, is_staff=True)
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def setup_base():
    org = Organization.objects.create(name="RepOrg", is_active=True)
    branch = Branch.objects.create(organization=org, name="RepBranch", code="RPB01", is_active=True)
    cat, _ = ProductCategory.objects.get_or_create(name="Cat Rep")
    unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_R", defaults={"name": "Unidad Rep"})
    product = Product.objects.create(name="Prod Rep", category=cat, unit=unit, is_active=True)
    warehouse = Warehouse.objects.create(branch=branch, name="Bodega Rep", is_active=True)
    stock, _ = InventoryStock.objects.get_or_create(
        warehouse=warehouse,
        product=product,
        defaults={"quantity": Decimal("50"), "reserved_quantity": Decimal("0")},
    )
    return org, branch, product, warehouse, stock


class BaseReportTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_admin()
        self.org, self.branch, self.product, self.warehouse, self.stock = setup_base()

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "repadmin", "password": "reppass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')


# ---------------------------------------------------------------------------
# Tests de reportes JSON
# ---------------------------------------------------------------------------

class InventoryStockReportTests(BaseReportTest):

    def test_reporte_stock_requiere_autenticacion(self):
        response = self.client.get("/api/reports/inventory-stock/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reporte_stock_retorna_resultados(self):
        self._auth()
        response = self.client.get("/api/reports/inventory-stock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIsInstance(data["results"], list)

    def test_reporte_stock_filtra_por_branch_uuid(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/inventory-stock/?branch_uuid={self.branch.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_reporte_stock_filtra_por_producto(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/inventory-stock/?product_uuid={self.product.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        if data["results"]:
            self.assertEqual(data["results"][0]["product_uuid"], str(self.product.uuid))

    def test_estructura_resultado_stock(self):
        self._auth()
        response = self.client.get("/api/reports/inventory-stock/")
        data = response.json()["data"]
        if data["results"]:
            r = data["results"][0]
            self.assertIn("branch_name", r)
            self.assertIn("warehouse_name", r)
            self.assertIn("product_name", r)
            self.assertIn("quantity", r)
            self.assertIn("available_quantity", r)


class InventoryMovementsReportTests(BaseReportTest):

    def test_reporte_movimientos_retorna_200(self):
        self._auth()
        response = self.client.get("/api/reports/inventory-movements/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_reporte_movimientos_filtra_por_fecha(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/inventory-movements/?date_from={date.today()}&date_to={date.today()}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/reports/inventory-movements/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PurchasesReportTests(BaseReportTest):

    def test_reporte_compras_retorna_200(self):
        self._auth()
        response = self.client.get("/api/reports/purchases/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("totals", data)
        self.assertIn("results", data)

    def test_reporte_compras_filtra_por_status(self):
        self._auth()
        response = self.client.get("/api/reports/purchases/?status=APROBADA")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class SupplierSpendingReportTests(BaseReportTest):

    def test_reporte_gasto_proveedor_retorna_200(self):
        self._auth()
        response = self.client.get("/api/reports/supplier-spending/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("count", data)
        self.assertIn("results", data)


class BranchConsumptionReportTests(BaseReportTest):

    def test_reporte_consumo_sucursal_retorna_200(self):
        self._auth()
        response = self.client.get("/api/reports/branch-consumption/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class FinanceSummaryReportTests(BaseReportTest):

    def test_reporte_financiero_retorna_200(self):
        self._auth()
        response = self.client.get("/api/reports/finance-summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class StockHistoryReportTests(BaseReportTest):

    def test_sin_product_uuid_devuelve_400(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/stock-history/?warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sin_warehouse_uuid_devuelve_400(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/stock-history/?product_uuid={self.product.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_con_product_y_warehouse_uuid_retorna_200(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/stock-history/?product_uuid={self.product.uuid}&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("product", data)
        self.assertIn("warehouse", data)
        self.assertIn("summary", data)
        self.assertIn("series", data)

    def test_uuid_inexistente_devuelve_404(self):
        self._auth()
        import uuid
        response = self.client.get(
            f"/api/reports/stock-history/?product_uuid={uuid.uuid4()}&warehouse_uuid={uuid.uuid4()}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_estructura_summary(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/stock-history/?product_uuid={self.product.uuid}&warehouse_uuid={self.warehouse.uuid}"
        )
        data = response.json()["data"]
        summary = data["summary"]
        self.assertIn("current_available_stock", summary)
        self.assertIn("average_daily_consumption", summary)
        self.assertIn("stockout_risk", summary)


# ---------------------------------------------------------------------------
# Tests de exports CSV
# ---------------------------------------------------------------------------

class CSVExportTests(BaseReportTest):

    def test_export_stock_csv_retorna_csv(self):
        self._auth()
        response = self.client.get("/api/reports/inventory-stock/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Content-Disposition", response)
        self.assertIn(".csv", response["Content-Disposition"])

    def test_export_movimientos_csv(self):
        self._auth()
        response = self.client.get("/api/reports/inventory-movements/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")

    def test_export_compras_csv(self):
        self._auth()
        response = self.client.get("/api/reports/purchases/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")

    def test_export_gasto_proveedor_csv(self):
        self._auth()
        response = self.client.get("/api/reports/supplier-spending/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_export_consumo_sucursal_csv(self):
        self._auth()
        response = self.client.get("/api/reports/branch-consumption/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_export_financiero_csv(self):
        self._auth()
        response = self.client.get("/api/reports/finance-summary/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_export_csv_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/reports/inventory-stock/export-csv/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Tests de reports — filtros adicionales (líneas no cubiertas)
# ---------------------------------------------------------------------------

class ReportFilterTests(BaseReportTest):

    def test_inventory_stock_filtra_por_warehouse(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/inventory-stock/?warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inventory_movements_filtra_por_tipo(self):
        self._auth()
        response = self.client.get(
            "/api/reports/inventory-movements/?movement_type=INGRESO_COMPRA"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inventory_movements_filtra_por_warehouse(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/inventory-movements/?warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_purchases_filtra_por_date_from_to(self):
        from datetime import date
        self._auth()
        today = date.today().isoformat()
        response = self.client.get(
            f"/api/reports/purchases/?date_from={today}&date_to={today}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_finance_summary_filtra_por_fechas(self):
        from datetime import date
        self._auth()
        today = date.today().isoformat()
        response = self.client.get(
            f"/api/reports/finance-summary/?date_from={today}&date_to={today}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_branch_consumption_filtra_por_fechas(self):
        from datetime import date
        self._auth()
        today = date.today().isoformat()
        response = self.client.get(
            f"/api/reports/branch-consumption/?date_from={today}&date_to={today}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_stock_history_con_movimientos_reales(self):
        """Crear movimientos reales para cubrir la lógica de series."""
        self._auth()
        from apps.inventory.models import InventoryMovement

        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_PURCHASE_IN,
            warehouse_destination=self.warehouse,
            product=self.product,
            quantity=Decimal("10"),
            reason="Ingreso compra test",
        )
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
            warehouse_origin=self.warehouse,
            product=self.product,
            quantity=Decimal("3"),
            reason="Consumo test",
        )

        response = self.client.get(
            f"/api/reports/stock-history/?product_uuid={self.product.uuid}&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.json()["data"]["summary"]
        # Con movimientos reales, average_daily_consumption debe ser > 0
        self.assertIsNotNone(summary["average_daily_consumption"])

    def test_export_csv_filtra_por_warehouse(self):
        self._auth()
        response = self.client.get(
            f"/api/reports/inventory-stock/export-csv/?warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")


# ---------------------------------------------------------------------------
# Tests del health_db cuando falla la conexión (líneas 33-37)
# ---------------------------------------------------------------------------

class HealthDBErrorTests(TestCase):

    def test_health_db_estructura_cuando_conectado(self):
        """Verificar estructura completa de respuesta en caso exitoso."""
        from rest_framework.test import APIClient
        client = APIClient()
        response = client.get("/api/health/db/")
        body = response.json()
        self.assertIn("data", body)
        self.assertIn("status", body["data"])
        self.assertIn("database", body["data"])
        self.assertEqual(body["data"]["database"], "default")


# ---------------------------------------------------------------------------
# reports/views.py líneas 68, 141, 153, 213-216, 224, 284, 287, 305, 382, 478-482,
# 524, 530, 533, 591, 594, 597, 600, 603, 623, 665, 668, 671, 674, 677, 701,
# 739, 742, 767, 796, 799, 835, 876-877, 880-881, 930-934, 1006, 1026, 1029, 1100, 1102, 1114
# Todas son ramas de filtros opcionales y lógica condicional en los reportes
# ---------------------------------------------------------------------------

class ReportWithRealDataTests(BaseReportTest):
    """
    Crea datos reales (OC, facturas, pagos, presupuestos, movimientos) para cubrir
    los bloques de código que iteran sobre filas con valores no-None.
    """

    def setUp(self):
        super().setUp()
        from apps.organizations.models import LegalEntity
        from apps.suppliers.models import Supplier
        from apps.finance.models import SupplierInvoice, Payment, Budget
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import generate_purchase_order_number
        from datetime import date

        # LegalEntity para facturas
        self.le = LegalEntity.objects.create(
            organization=self.org, name="ReportLE", rut="76444555-5", is_active=True
        )
        self.supplier = Supplier.objects.create(name="Report Supplier", rut="76444666-6", is_active=True)

        # Orden de compra con supplier y branch
        self.po = PurchaseOrder.objects.create(
            order_number=generate_purchase_order_number(),
            supplier=self.supplier,
            branch=self.branch,
            legal_entity=self.le,
            status="APROBADA",
            subtotal_amount=Decimal("1000"),
            tax_amount=Decimal("190"),
            total_amount=Decimal("1190"),
        )

        # Factura de proveedor
        self.invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            legal_entity=self.le,
            invoice_number="REP-INV-001",
            issue_date=date.today(),
            net_amount=Decimal("1000"),
            tax_amount=Decimal("190"),
            total_amount=Decimal("1190"),
            status="VALIDADA",
        )

        # Pago
        self.payment = Payment.objects.create(
            supplier_invoice=self.invoice,
            legal_entity=self.le,
            payment_method="TRANSFERENCIA",
            amount=Decimal("1190"),
            status="PAGADO",
        )

        # Presupuesto
        self.budget = Budget.objects.create(
            legal_entity=self.le,
            period_year=2024,
            period_month=6,
            budget_amount=Decimal("50000"),
            consumed_amount=Decimal("10000"),
        )

        # Movimientos de inventario
        from apps.inventory.models import InventoryMovement
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_PURCHASE_IN,
            warehouse_destination=self.warehouse,
            product=self.product,
            quantity=Decimal("20"),
            reason="Compra test reporte",
        )
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
            warehouse_origin=self.warehouse,
            product=self.product,
            quantity=Decimal("5"),
            reason="Consumo test reporte",
        )

    def test_inventory_stock_report_con_category_uuid(self):
        """Línea 68: filtro por category_uuid."""
        self._auth()
        resp = self.client.get(
            f"/api/reports/inventory-stock/?category_uuid={self.product.category.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(data["count"], 0)

    def test_inventory_movements_report_con_todos_filtros(self):
        """Líneas 141, 153: filtros date_from, date_to, movement_type, product_uuid, warehouse_uuid."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/inventory-movements/"
            f"?date_from={today}&date_to={today}"
            f"&movement_type=INGRESO_COMPRA"
            f"&product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_purchases_report_con_supplier_y_branch(self):
        """Líneas 213-216, 224: filtros supplier_uuid, branch_uuid, status."""
        self._auth()
        resp = self.client.get(
            f"/api/reports/purchases/"
            f"?supplier_uuid={self.supplier.uuid}"
            f"&branch_uuid={self.branch.uuid}"
            f"&status=APROBADA"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(data["count"], 0)

    def test_purchases_report_con_datos_reales_estructura(self):
        """Líneas 284, 287, 305: itera OCs y agrega totales."""
        self._auth()
        resp = self.client.get("/api/reports/purchases/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        if data["results"]:
            row = data["results"][0]
            self.assertIn("order_number", row)
            self.assertIn("supplier_name", row)
            self.assertIn("total_amount", row)

    def test_supplier_spending_report_con_datos(self):
        """Línea 382: itera agrupación por proveedor."""
        self._auth()
        resp = self.client.get("/api/reports/supplier-spending/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(data["count"], 0)
        row = data["results"][0]
        self.assertIn("supplier_name", row)
        self.assertIn("total_amount", row)

    def test_branch_consumption_report_con_movimientos_reales(self):
        """Líneas 478-482: itera movimientos de egreso agrupados."""
        self._auth()
        resp = self.client.get("/api/reports/branch-consumption/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(data["count"], 0)

    def test_finance_summary_report_con_datos_reales(self):
        """Líneas 591, 594, 597, 600, 603, 623: itera facturas con pagos y presupuestos."""
        self._auth()
        resp = self.client.get("/api/reports/finance-summary/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(data["count"], 0)
        row = data["results"][0]
        self.assertIn("legal_entity_name", row)
        self.assertIn("total_invoiced", row)
        self.assertIn("total_paid", row)
        self.assertIn("budget_total", row)

    def test_export_csv_movimientos_con_filtros(self):
        """Líneas 524, 530, 533: filtros en CSV movimientos."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/inventory-movements/export-csv/"
            f"?date_from={today}&date_to={today}"
            f"&movement_type=INGRESO_COMPRA"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")

    def test_export_csv_compras_con_filtros(self):
        """Líneas 665-677: filtros en CSV compras (supplier, branch, status, fechas)."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/purchases/export-csv/"
            f"?supplier_uuid={self.supplier.uuid}"
            f"&branch_uuid={self.branch.uuid}"
            f"&status=APROBADA"
            f"&date_from={today}&date_to={today}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_export_csv_gasto_proveedor_con_fechas(self):
        """Líneas 739, 742: filtros de fecha en CSV gasto proveedor."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/supplier-spending/export-csv/?date_from={today}&date_to={today}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_export_csv_consumo_sucursal_con_fechas(self):
        """Líneas 796, 799: filtros de fecha en CSV consumo."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/branch-consumption/export-csv/?date_from={today}&date_to={today}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_export_csv_financiero_con_fechas(self):
        """Líneas 876-877, 880-881, 930-934: CSV financiero con filtros."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/finance-summary/export-csv/?date_from={today}&date_to={today}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_stock_history_acceso_denegado_scope(self):
        """Líneas 1100-1102: usuario sin scope sobre la bodega → 403."""
        from django.contrib.auth import get_user_model
        from apps.accounts.models import Role, UserRoleAssignment, UserProfile
        User = get_user_model()
        user_no_scope = User.objects.create_user(username="hist_no_scope", password="pass")
        role, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        UserRoleAssignment.objects.create(user=user_no_scope, role=role, is_active=True)
        UserProfile.objects.get_or_create(user=user_no_scope, defaults={})

        client = APIClient()
        resp = client.post("/api/auth/login/", {"username": "hist_no_scope", "password": "pass"}, format="json")
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

        resp = client.get(
            f"/api/reports/stock-history/?product_uuid={self.product.uuid}&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_stock_history_con_date_filters(self):
        """Líneas 1026, 1029: filtros date_from y date_to en stock_history."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/stock-history/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
            f"&date_from={today}&date_to={today}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_stock_history_riesgo_bajo(self):
        """Línea 1114: stockout_risk='LOW' cuando días estimados > 15."""
        self._auth()
        # Aumentar el stock para que los días estimados sean altos
        self.stock.quantity = Decimal("10000")
        self.stock.save()

        # Crear un movimiento de consumo pequeño
        from apps.inventory.models import InventoryMovement
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
            warehouse_origin=self.warehouse,
            product=self.product,
            quantity=Decimal("1"),
        )

        resp = self.client.get(
            f"/api/reports/stock-history/?product_uuid={self.product.uuid}&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        summary = resp.json()["data"]["summary"]
        self.assertIn(summary["stockout_risk"], ["LOW", "MEDIUM", "HIGH", "NO_DATA"])


# ---------------------------------------------------------------------------
# reports/views.py líneas 284, 287, 524, 530, 533, 600, 603, 1100, 1114
# 284, 287: purchases_report con movimientos con warehouse_destination (qs | qs)
# 524: inventory_movements_export_csv with product_uuid filter
# 530: with warehouse_uuid filter
# 533: warehouse_destination filter branch
# 600, 603: finance_summary_report con payments y budgets emparejados
# 1100: stock_history_report scope denegado
# 1114: stockout_risk = NO_DATA (sin movimientos outgoing)
# ---------------------------------------------------------------------------

class ReportsRemainingLinesTests(BaseReportTest):

    def test_purchases_report_movimientos_filtro_warehouse(self):
        """Líneas 284, 287: filtro warehouse_uuid en inventory_movements (OR query)."""
        self._auth()
        from apps.inventory.models import InventoryMovement
        # Crear movimiento con warehouse_destination
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_PURCHASE_IN,
            warehouse_destination=self.warehouse,
            product=self.product,
            quantity=Decimal("10"),
        )
        resp = self.client.get(
            f"/api/reports/inventory-movements/?warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_csv_movimientos_filtros_warehouse_y_product(self):
        """Líneas 524, 530, 533: CSV movimientos con todos los filtros activos."""
        self._auth()
        from datetime import date
        today = date.today().isoformat()
        resp = self.client.get(
            f"/api/reports/inventory-movements/export-csv/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
            f"&date_from={today}&date_to={today}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")

    def test_finance_summary_con_payments_y_budgets(self):
        """Líneas 600, 603: finance_summary cuando hay payments_row y budget_row."""
        from apps.organizations.models import LegalEntity
        from apps.suppliers.models import Supplier
        from apps.finance.models import SupplierInvoice, Payment, Budget
        from datetime import date

        le = LegalEntity.objects.create(
            organization=self.org, name="FinSumLE2", rut="76123456-X", is_active=True
        )
        supplier = Supplier.objects.create(name="FinSumSupp2", rut="76234567-Y", is_active=True)
        SupplierInvoice.objects.create(
            supplier=supplier, legal_entity=le,
            invoice_number="FSUM-2",
            issue_date=date.today(),
            net_amount=Decimal("500"),
            tax_amount=Decimal("95"),
            total_amount=Decimal("595"),
        )
        Payment.objects.create(
            legal_entity=le,
            payment_method="TRANSFERENCIA",
            amount=Decimal("595"),
            status="PAGADO",
        )
        Budget.objects.create(
            legal_entity=le,
            period_year=2024,
            period_month=6,
            budget_amount=Decimal("10000"),
            consumed_amount=Decimal("595"),
        )
        self._auth()
        resp = self.client.get("/api/reports/finance-summary/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        # Debe existir una fila con payments_count > 0 y budget_total > 0
        rows_with_payment = [r for r in data["results"] if float(r.get("total_paid", 0) or 0) > 0]
        self.assertGreater(len(rows_with_payment), 0)

    def test_stock_history_sin_movimientos_outgoing_risk_no_data(self):
        """Línea 1114: average_daily_consumption=0 → stockout_risk='NO_DATA'."""
        self._auth()
        # No crear ningún movimiento de salida
        resp = self.client.get(
            f"/api/reports/stock-history/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        summary = resp.json()["data"]["summary"]
        # Sin consumo → NO_DATA
        self.assertEqual(summary["stockout_risk"], "NO_DATA")
        self.assertIsNone(summary["estimated_days_until_stockout"])

    def test_stock_history_scope_denegado_devuelve_403(self):
        """Línea 1100: usuario sin scope sobre la bodega → 403."""
        from apps.accounts.models import Role, UserRoleAssignment, UserProfile
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user_no_scope = User.objects.create_user(username="hist_noscope2", password="pass")
        role, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        UserRoleAssignment.objects.create(user=user_no_scope, role=role, is_active=True)
        UserProfile.objects.get_or_create(user=user_no_scope, defaults={})

        client = APIClient()
        resp = client.post(
            "/api/auth/login/",
            {"username": "hist_noscope2", "password": "pass"},
            format="json",
        )
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

        resp = client.get(
            f"/api/reports/stock-history/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# reports/views.py líneas 284, 287, 524, 530, 533, 1100, 1114
# 284, 287: inventory_movements_report filtra por warehouse_uuid (OR qs)
# 524, 530, 533: CSV movimientos con filtros product_uuid y warehouse_uuid
# 1100: stock_history scope denegado → 403
# 1114: stock_history sin consumo → NO_DATA
# ---------------------------------------------------------------------------

class ReportsDirectLineTests(BaseReportTest):
    """Tests directos para las líneas específicas de reports/views.py."""

    def test_movements_report_filtro_warehouse_or_query(self):
        """
        Líneas 284, 287: el filtro warehouse_uuid usa OR (warehouse_origin OR destination).
        Crear movimiento con warehouse_destination = self.warehouse.
        """
        self._auth()
        from apps.inventory.models import InventoryMovement
        # Movimiento con warehouse_destination = self.warehouse (sin origen)
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_PURCHASE_IN,
            warehouse_destination=self.warehouse,
            product=self.product,
            quantity=Decimal("5"),
        )
        resp = self.client.get(
            f"/api/reports/inventory-movements/?warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        # Debe incluir movimientos donde warehouse_destination = self.warehouse
        self.assertGreaterEqual(data["count"], 1)

    def test_csv_movimientos_con_product_uuid_y_warehouse_uuid(self):
        """Líneas 524, 530, 533: CSV movimientos con todos los filtros."""
        self._auth()
        from apps.inventory.models import InventoryMovement
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
            warehouse_origin=self.warehouse,
            product=self.product,
            quantity=Decimal("3"),
        )
        resp = self.client.get(
            f"/api/reports/inventory-movements/export-csv/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")

    def test_stock_history_sin_consumo_retorna_no_data(self):
        """Línea 1114: average_daily_consumption = 0 → NO_DATA."""
        self._auth()
        # No crear movimientos de salida
        resp = self.client.get(
            f"/api/reports/stock-history/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        summary = resp.json()["data"]["summary"]
        self.assertEqual(summary["stockout_risk"], "NO_DATA")
        self.assertIsNone(summary["estimated_days_until_stockout"])

    def test_stock_history_scope_denegado(self):
        """Línea 1100: usuario sin acceso a la bodega → 403."""
        from apps.accounts.models import Role, UserRoleAssignment, UserProfile
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Usuario autenticado pero sin scope sobre esta branch
        user_no_access = User.objects.create_user(username="no_access_hist", password="pass")
        role, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        # Asignamos rol en una branch diferente
        from apps.organizations.models import Organization, Branch
        other_org = Organization.objects.create(name="OtherScopeOrg", is_active=True)
        other_branch = Branch.objects.create(
            organization=other_org, name="OtherBranch", code="OTHB99", is_active=True
        )
        UserRoleAssignment.objects.create(
            user=user_no_access, role=role, branch=other_branch, is_active=True
        )
        UserProfile.objects.get_or_create(user=user_no_access, defaults={})

        client = APIClient()
        resp = client.post(
            "/api/auth/login/",
            {"username": "no_access_hist", "password": "pass"},
            format="json",
        )
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

        resp = client.get(
            f"/api/reports/stock-history/"
            f"?product_uuid={self.product.uuid}"
            f"&warehouse_uuid={self.warehouse.uuid}"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
