"""
Tests para la app inventory:
- Modelos: Warehouse, InventoryStock, InventoryLot, InventoryMovement
- Servicios: increase_stock, decrease_stock, reserve_stock, release_reserved_stock,
             adjust_stock, transfer_stock_between_warehouses
- ViewSets: bodegas, stock, lotes, movimientos
- Custom actions: low_stock, expiring_soon, expired, increase, decrease, adjust, reserve, release
"""
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.organizations.models import Organization, Branch, LegalEntity
from apps.products.models import ProductCategory, UnitOfMeasure, Product, BranchProduct
from apps.suppliers.models import Supplier
from apps.inventory.models import Warehouse, InventoryStock, InventoryLot, InventoryMovement

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------

def create_superuser(username="invadmin", password="invpass"):
    return User.objects.create_user(
        username=username, password=password, is_superuser=True, is_staff=True
    )


def create_user_with_role(username, password, role_code, branch=None):
    user = User.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(
        code=role_code, defaults={"name": role_code.capitalize(), "is_active": True}
    )
    UserRoleAssignment.objects.create(
        user=user, role=role, branch=branch, is_active=True
    )
    UserProfile.objects.get_or_create(user=user, defaults={})
    return user


def make_org_and_branch(org_name="InvOrg", branch_name="InvBranch", branch_code="INVB"):
    org = Organization.objects.create(name=org_name, is_active=True)
    branch = Branch.objects.create(organization=org, name=branch_name, code=branch_code, is_active=True)
    return org, branch


def make_product(name="Producto Test", category=None, unit=None, requires_lot=False):
    if category is None:
        category, _ = ProductCategory.objects.get_or_create(name="Cat Test")
    if unit is None:
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN", defaults={"name": "Unidad"})
    return Product.objects.create(
        name=name,
        category=category,
        unit=unit,
        is_active=True,
        requires_lot=requires_lot,
    )


def make_warehouse(branch, name="Bodega Test", warehouse_type="GENERAL"):
    return Warehouse.objects.create(branch=branch, name=name, warehouse_type=warehouse_type, is_active=True)


def make_stock(warehouse, product, quantity=10, reserved=0):
    stock, _ = InventoryStock.objects.get_or_create(
        warehouse=warehouse,
        product=product,
        defaults={"quantity": quantity, "reserved_quantity": reserved},
    )
    stock.quantity = quantity
    stock.reserved_quantity = reserved
    stock.save()
    return stock


# ---------------------------------------------------------------------------
# Tests de modelos
# ---------------------------------------------------------------------------

class WarehouseModelTests(TestCase):

    def test_str_bodega(self):
        _, branch = make_org_and_branch()
        warehouse = Warehouse(branch=branch, name="Bodega Prueba")
        self.assertIn("Bodega Prueba", str(warehouse))

    def test_unique_constraint_branch_name(self):
        _, branch = make_org_and_branch(branch_code="UNQ01")
        Warehouse.objects.create(branch=branch, name="Bodega Única", is_active=True)
        with self.assertRaises(Exception):
            Warehouse.objects.create(branch=branch, name="Bodega Única", is_active=True)


class InventoryStockModelTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="STK01")
        self.warehouse = make_warehouse(self.branch, name="Bodega STK")
        self.product = make_product(name="Prod STK")

    def test_available_quantity_es_diferencia(self):
        stock = make_stock(self.warehouse, self.product, quantity=10, reserved=3)
        self.assertEqual(stock.available_quantity, Decimal("7"))

    def test_clean_falla_si_reservado_mayor_a_total(self):
        stock = InventoryStock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("5"),
            reserved_quantity=Decimal("10"),
        )
        with self.assertRaises(ValidationError):
            stock.clean()

    def test_str_stock(self):
        stock = make_stock(self.warehouse, self.product, quantity=5)
        self.assertIn("5", str(stock))


class InventoryLotModelTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="LOT01")
        self.warehouse = make_warehouse(self.branch, name="Bodega LOT")
        self.product = make_product(name="Prod LOT", requires_lot=True)

    def test_str_lote(self):
        lot = InventoryLot(
            warehouse=self.warehouse,
            product=self.product,
            lot_number="L001",
            quantity=Decimal("5"),
            status=InventoryLot.STATUS_AVAILABLE,
        )
        self.assertIn("L001", str(lot))

    def test_clean_requiere_lote_si_producto_lo_exige(self):
        lot = InventoryLot(
            warehouse=self.warehouse,
            product=self.product,
            lot_number=None,
            quantity=Decimal("5"),
        )
        with self.assertRaises(ValidationError):
            lot.clean()


class InventoryMovementModelTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="MOV01")
        self.w1 = make_warehouse(self.branch, name="Bodega MOV1")
        self.w2 = make_warehouse(self.branch, name="Bodega MOV2")
        self.product = make_product(name="Prod MOV")

    def test_clean_transferencia_requiere_origen_y_destino_distintos(self):
        movement = InventoryMovement(
            movement_type=InventoryMovement.TYPE_TRANSFER,
            product=self.product,
            quantity=Decimal("5"),
            warehouse_origin=self.w1,
            warehouse_destination=self.w1,
        )
        with self.assertRaises(ValidationError):
            movement.clean()

    def test_clean_egreso_requiere_bodega_origen(self):
        movement = InventoryMovement(
            movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
            product=self.product,
            quantity=Decimal("5"),
            warehouse_origin=None,
        )
        with self.assertRaises(ValidationError):
            movement.clean()

    def test_str_movimiento(self):
        movement = InventoryMovement(
            movement_type=InventoryMovement.TYPE_PURCHASE_IN,
            product=self.product,
            quantity=Decimal("3"),
        )
        self.assertIn("INGRESO_COMPRA", str(movement))


# ---------------------------------------------------------------------------
# Tests de servicios de inventario
# ---------------------------------------------------------------------------

class InventoryServicesTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="SRV01")
        self.warehouse = make_warehouse(self.branch, name="Bodega SRV")
        self.product = make_product(name="Prod SRV")

    def test_decrease_stock_falla_con_stock_insuficiente(self):
        from apps.inventory.services import decrease_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("5"))
        with self.assertRaises(ValidationError):
            decrease_stock(
                warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("10"),
            )

    def test_decrease_stock_falla_con_cantidad_cero(self):
        from apps.inventory.services import decrease_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("5"))
        with self.assertRaises(ValidationError):
            decrease_stock(
                warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("0"),
            )

    def test_decrease_stock_falla_con_cantidad_negativa(self):
        from apps.inventory.services import decrease_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("5"))
        with self.assertRaises(ValidationError):
            decrease_stock(
                warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("-1"),
            )

    def test_reserve_stock_reduce_disponible(self):
        from apps.inventory.services import reserve_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("10"), reserved=Decimal("0"))
        stock = reserve_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("3"),
        )
        self.assertEqual(stock.reserved_quantity, Decimal("3"))
        self.assertEqual(stock.available_quantity, Decimal("7"))

    def test_reserve_stock_falla_si_no_hay_disponible(self):
        from apps.inventory.services import reserve_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("2"), reserved=Decimal("0"))
        with self.assertRaises(ValidationError):
            reserve_stock(
                warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("5"),
            )

    def test_release_reserved_stock_libera_reserva(self):
        from apps.inventory.services import release_reserved_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("10"), reserved=Decimal("4"))
        stock = release_reserved_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("2"),
        )
        self.assertEqual(stock.reserved_quantity, Decimal("2"))

    def test_release_falla_si_se_intenta_liberar_mas_de_lo_reservado(self):
        from apps.inventory.services import release_reserved_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("10"), reserved=Decimal("1"))
        with self.assertRaises(ValidationError):
            release_reserved_stock(
                warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("5"),
            )

    def test_adjust_stock_cero_falla(self):
        from apps.inventory.services import adjust_stock
        make_stock(self.warehouse, self.product, quantity=Decimal("5"))
        with self.assertRaises(ValidationError):
            adjust_stock(
                warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("0"),
                reason="Ajuste prueba",
            )

    def test_transfer_stock_falla_con_misma_bodega(self):
        from apps.inventory.services import transfer_stock_between_warehouses
        make_stock(self.warehouse, self.product, quantity=Decimal("5"))
        with self.assertRaises(ValidationError):
            transfer_stock_between_warehouses(
                origin_warehouse=self.warehouse,
                destination_warehouse=self.warehouse,
                product=self.product,
                quantity=Decimal("2"),
            )


# ---------------------------------------------------------------------------
# Tests de ViewSets de inventario (API)
# ---------------------------------------------------------------------------

class WarehouseViewSetTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="WVS01")
        self.admin = create_superuser(username="wvsadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "wvsadmin", "password": "pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_crear_bodega(self):
        self._auth()
        response = self.client.post(
            "/api/warehouses/",
            {
                "branch": self.branch.id,
                "name": "Bodega API",
                "warehouse_type": "GENERAL",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["data"]["name"], "Bodega API")

    def test_listar_bodegas(self):
        self._auth()
        response = self.client.get("/api/warehouses/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_obtener_bodega_por_uuid(self):
        self._auth()
        warehouse = make_warehouse(self.branch, name="Bodega GET")
        response = self.client.get(f"/api/warehouses/{warehouse.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_actualizar_bodega(self):
        self._auth()
        warehouse = make_warehouse(self.branch, name="Bodega Antigua")
        response = self.client.patch(
            f"/api/warehouses/{warehouse.uuid}/",
            {"name": "Bodega Actualizada"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["name"], "Bodega Actualizada")

    def test_soft_delete_bodega(self):
        self._auth()
        warehouse = make_warehouse(self.branch, name="Bodega Delete")
        response = self.client.delete(f"/api/warehouses/{warehouse.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        warehouse.refresh_from_db()
        self.assertIsNotNone(warehouse.deleted_at)

    def test_sin_autenticacion_no_puede_listar_bodegas(self):
        response = self.client.get("/api/warehouses/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class InventoryStockViewSetTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="ISV01")
        self.warehouse = make_warehouse(self.branch, name="Bodega ISV")
        self.product = make_product(name="Prod ISV")
        self.admin = create_superuser(username="isvadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "isvadmin", "password": "pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_listar_stocks(self):
        self._auth()
        response = self.client.get("/api/inventory-stocks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_accion_low_stock(self):
        self._auth()
        response = self.client.get("/api/inventory-stocks/low_stock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class InventoryLotViewSetTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="ILV01")
        self.warehouse = make_warehouse(self.branch, name="Bodega ILV")
        self.product = make_product(name="Prod ILV")
        self.admin = create_superuser(username="ilvadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "ilvadmin", "password": "pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_crear_lote(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-lots/",
            {
                "warehouse": self.warehouse.id,
                "product": self.product.id,
                "lot_number": "L-2024-001",
                "quantity": "10.000",
                "status": "DISPONIBLE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_accion_expiring_soon(self):
        self._auth()
        # Crear lote que vence en 10 días
        InventoryLot.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            lot_number="SOON",
            quantity=Decimal("5"),
            status="DISPONIBLE",
            expiration_date=date.today() + timedelta(days=10),
        )
        response = self.client.get("/api/inventory-lots/expiring_soon/?days=30")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["data"]
        if isinstance(results, dict):
            results = results.get("results", [])
        self.assertGreaterEqual(len(results), 1)

    def test_accion_expired(self):
        self._auth()
        InventoryLot.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            lot_number="EXPIRED",
            quantity=Decimal("3"),
            status="VENCIDO",
            expiration_date=date.today() - timedelta(days=5),
        )
        response = self.client.get("/api/inventory-lots/expired/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class InventoryMovementActionsTests(TestCase):
    """Tests para las acciones custom del InventoryMovementViewSet."""

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="IMA01")
        self.warehouse = make_warehouse(self.branch, name="Bodega IMA")
        self.product = make_product(name="Prod IMA")
        self.admin = create_superuser(username="imaadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})
        # Stock inicial
        make_stock(self.warehouse, self.product, quantity=Decimal("100"))

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "imaadmin", "password": "pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_reserve_stock_action(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/reserve/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "5.000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_release_stock_action(self):
        self._auth()
        # Primero reservar
        self.client.post(
            "/api/inventory-movements/reserve/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "10.000",
            },
            format="json",
        )
        # Luego liberar
        response = self.client.post(
            "/api/inventory-movements/release/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "5.000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_adjust_stock_action_positivo(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/adjust/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "15.000",
                "reason": "Ajuste de inventario positivo",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_adjust_stock_action_negativo(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/adjust/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "-5.000",
                "reason": "Ajuste de inventario negativo",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_adjust_stock_cero_devuelve_error(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/adjust/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "0.000",
                "reason": "Ajuste nulo",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_decrease_mas_de_lo_disponible_devuelve_400(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/decrease/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "9999.000",
                "reason": "Egreso excesivo",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Tests de inventory/services.py — increase_stock con lote, transfer_between_warehouses
# ---------------------------------------------------------------------------

class IncreaseStockServiceTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="INC01")
        self.warehouse = make_warehouse(self.branch, name="Bodega INC")
        self.product_simple = make_product(name="Prod Simple")
        self.product_lot = make_product(name="Prod Con Lote", requires_lot=True)

    def test_increase_stock_sin_lote(self):
        from apps.inventory.services import increase_stock
        result = increase_stock(
            warehouse=self.warehouse,
            product=self.product_simple,
            quantity=Decimal("10"),
            reason="Ingreso test",
        )
        self.assertIsNotNone(result["stock"])
        self.assertIsNone(result["lot"])
        self.assertIsNotNone(result["movement"])
        self.assertEqual(result["stock"].quantity, Decimal("10"))

    def test_increase_stock_con_lote(self):
        from apps.inventory.services import increase_stock
        result = increase_stock(
            warehouse=self.warehouse,
            product=self.product_lot,
            quantity=Decimal("5"),
            lot_number="L-001",
            reason="Ingreso con lote",
        )
        self.assertIsNotNone(result["lot"])
        self.assertEqual(result["lot"].lot_number, "L-001")
        self.assertEqual(result["lot"].quantity, Decimal("5"))

    def test_increase_stock_lote_acumula_cantidad(self):
        from apps.inventory.services import increase_stock
        increase_stock(
            warehouse=self.warehouse,
            product=self.product_lot,
            quantity=Decimal("3"),
            lot_number="L-ACUM",
        )
        increase_stock(
            warehouse=self.warehouse,
            product=self.product_lot,
            quantity=Decimal("4"),
            lot_number="L-ACUM",
        )
        from apps.inventory.models import InventoryLot
        lot = InventoryLot.objects.get(warehouse=self.warehouse, product=self.product_lot, lot_number="L-ACUM")
        self.assertEqual(lot.quantity, Decimal("7"))

    def test_increase_stock_cero_falla(self):
        from apps.inventory.services import increase_stock
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            increase_stock(
                warehouse=self.warehouse,
                product=self.product_simple,
                quantity=Decimal("0"),
            )

    def test_increase_stock_negativo_falla(self):
        from apps.inventory.services import increase_stock
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            increase_stock(
                warehouse=self.warehouse,
                product=self.product_simple,
                quantity=Decimal("-5"),
            )

    def test_increase_stock_producto_requiere_lote_sin_lote_falla(self):
        from apps.inventory.services import increase_stock
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            increase_stock(
                warehouse=self.warehouse,
                product=self.product_lot,
                quantity=Decimal("5"),
                lot_number=None,   # producto requires_lot=True pero no se pasa lote
            )

    def test_increase_con_expiracion(self):
        from apps.inventory.services import increase_stock
        product_exp = make_product(name="Prod Exp")
        product_exp.requires_expiration_date = True
        product_exp.save()
        result = increase_stock(
            warehouse=self.warehouse,
            product=product_exp,
            quantity=Decimal("2"),
            lot_number="L-EXP",
            expiration_date=date(2025, 12, 31),
        )
        self.assertEqual(result["lot"].expiration_date, date(2025, 12, 31))


class TransferStockServiceTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="TRF01")
        self.w1 = make_warehouse(self.branch, name="W Transfer 1")
        self.w2 = make_warehouse(self.branch, name="W Transfer 2")
        self.product = make_product(name="Prod Transfer")
        make_stock(self.w1, self.product, quantity=Decimal("20"))

    def test_transfer_exitoso_descuenta_origen_aumenta_destino(self):
        from apps.inventory.services import transfer_stock_between_warehouses
        from apps.inventory.models import InventoryStock
        result = transfer_stock_between_warehouses(
            origin_warehouse=self.w1,
            destination_warehouse=self.w2,
            product=self.product,
            quantity=Decimal("8"),
            reason="Transferencia test",
        )
        stock_origen = InventoryStock.objects.get(warehouse=self.w1, product=self.product)
        stock_destino = InventoryStock.objects.get(warehouse=self.w2, product=self.product)
        self.assertEqual(stock_origen.quantity, Decimal("12"))
        self.assertEqual(stock_destino.quantity, Decimal("8"))

    def test_transfer_crea_dos_movimientos(self):
        from apps.inventory.services import transfer_stock_between_warehouses
        from apps.inventory.models import InventoryMovement
        count_before = InventoryMovement.objects.count()
        transfer_stock_between_warehouses(
            origin_warehouse=self.w1,
            destination_warehouse=self.w2,
            product=self.product,
            quantity=Decimal("3"),
        )
        # decrease + increase = 2 movimientos
        self.assertEqual(InventoryMovement.objects.count(), count_before + 2)

    def test_decrease_con_lote_reduce_cantidad_lote(self):
        from apps.inventory.services import decrease_stock
        from apps.inventory.models import InventoryLot
        lot = InventoryLot.objects.create(
            warehouse=self.w1,
            product=self.product,
            lot_number="LOT-DEC",
            quantity=Decimal("10"),
            status=InventoryLot.STATUS_AVAILABLE,
        )
        decrease_stock(
            warehouse=self.w1,
            product=self.product,
            quantity=Decimal("10"),
            lot=lot,
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("0"))
        self.assertEqual(lot.status, InventoryLot.STATUS_CONSUMED)

    def test_decrease_lote_insuficiente_falla(self):
        from apps.inventory.services import decrease_stock
        from apps.inventory.models import InventoryLot
        from django.core.exceptions import ValidationError
        lot = InventoryLot.objects.create(
            warehouse=self.w1,
            product=self.product,
            lot_number="LOT-INSUF",
            quantity=Decimal("2"),
            status=InventoryLot.STATUS_AVAILABLE,
        )
        with self.assertRaises(ValidationError):
            decrease_stock(
                warehouse=self.w1,
                product=self.product,
                quantity=Decimal("5"),
                lot=lot,
            )


# ---------------------------------------------------------------------------
# Tests de la acción increase del InventoryMovementViewSet (API)
# ---------------------------------------------------------------------------

class InventoryIncreaseAPITests(TestCase):

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="INCAPI")
        self.warehouse = make_warehouse(self.branch, name="Bodega IncAPI")
        self.product = make_product(name="Prod IncAPI")
        self.admin = create_superuser(username="incapiadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

    def _auth(self):
        resp = self.client.post("/api/auth/login/", {"username": "incapiadmin", "password": "pass"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_increase_sin_lote(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/increase/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "10.000",
                "reason": "Ingreso manual",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIsNotNone(data["stock"])
        self.assertIsNone(data["lot"])

    def test_increase_con_lote_y_fecha(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/increase/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "5.000",
                "lot_number": "L-API-001",
                "expiration_date": "2026-12-31",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["data"]["lot"])

    def test_increase_warehouse_uuid_invalido(self):
        self._auth()
        import uuid
        response = self.client.post(
            "/api/inventory-movements/increase/",
            {
                "warehouse_uuid": str(uuid.uuid4()),
                "product_uuid": str(self.product.uuid),
                "quantity": "5.000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Tests de inventory/views.py líneas 75-89
# Cubre: low_stock con BranchProduct configurado y stock bajo umbral
# ---------------------------------------------------------------------------

class LowStockActionTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="LSACT01")
        self.warehouse = make_warehouse(self.branch, name="Bodega LS Act")
        self.product = make_product(name="Prod LS Act")
        self.admin = create_superuser(username="lsactadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

        # Configurar BranchProduct con umbral crítico
        from apps.products.models import BranchProduct
        BranchProduct.objects.create(
            branch=self.branch,
            product=self.product,
            min_stock=Decimal("10"),
            critical_stock=Decimal("5"),
            is_active=True,
        )
        # Stock por debajo del crítico
        make_stock(self.warehouse, self.product, quantity=Decimal("3"))

    def _auth(self):
        resp = self.client.post("/api/auth/login/", {"username": "lsactadmin", "password": "pass"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_low_stock_retorna_producto_critico(self):
        self._auth()
        response = self.client.get("/api/inventory-stocks/low_stock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["data"]
        if isinstance(results, dict):
            results = results.get("results", [])
        # Debe incluir nuestro producto crítico
        uuids = [r["product"]["uuid"] if isinstance(r.get("product"), dict) else r.get("product") for r in results]
        self.assertGreater(len(results), 0)

    def test_low_stock_no_incluye_producto_con_stock_suficiente(self):
        self._auth()
        # Producto con stock suficiente
        prod_ok = make_product(name="Prod OK")
        from apps.products.models import BranchProduct
        BranchProduct.objects.create(
            branch=self.branch,
            product=prod_ok,
            critical_stock=Decimal("2"),
            is_active=True,
        )
        make_stock(self.warehouse, prod_ok, quantity=Decimal("50"))

        response = self.client.get("/api/inventory-stocks/low_stock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["data"]
        if isinstance(results, dict):
            results = results.get("results", [])
        # prod_ok no debe aparecer en críticos
        product_uuids_str = str(response.content)
        self.assertNotIn("Prod OK", product_uuids_str)


# ---------------------------------------------------------------------------
# Tests de inventory/views.py líneas 167-168, 179, 184, 214, 258-270, 331-332, 359-360
# Cubre: decrease con lot, _get_supplier con uuid válido, _get_lot con uuid válido,
#        ValidationError en release/reserve, búsqueda de movimientos
# ---------------------------------------------------------------------------

class InventoryMovementViewAdditionalTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="IMVA01")
        self.warehouse = make_warehouse(self.branch, name="Bodega IMVA")
        self.product = make_product(name="Prod IMVA")
        self.supplier = Supplier.objects.create(name="Prov IMVA", rut="76977001-1", is_active=True)
        self.admin = create_superuser(username="imvaadmin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})
        make_stock(self.warehouse, self.product, quantity=Decimal("100"))

    def _auth(self):
        resp = self.client.post("/api/auth/login/", {"username": "imvaadmin", "password": "pass"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_increase_con_supplier_uuid(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/increase/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "5.000",
                "supplier_uuid": str(self.supplier.uuid),
                "lot_number": "LOT-SUPP",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_decrease_con_lot_uuid(self):
        self._auth()
        # Crear lote con stock
        lot = InventoryLot.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            lot_number="LOT-DEC-API",
            quantity=Decimal("20"),
            status=InventoryLot.STATUS_AVAILABLE,
        )
        response = self.client.post(
            "/api/inventory-movements/decrease/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "5.000",
                "lot_uuid": str(lot.uuid),
                "reason": "Egreso con lote",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("15"))

    def test_reserve_insuficiente_devuelve_400(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/reserve/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "999.000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_release_excesivo_devuelve_400(self):
        self._auth()
        response = self.client.post(
            "/api/inventory-movements/release/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(self.product.uuid),
                "quantity": "999.000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_listar_movimientos_con_filtro_tipo(self):
        self._auth()
        response = self.client.get("/api/inventory-movements/?movement_type=INGRESO_COMPRA")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_listar_movimientos_con_search(self):
        self._auth()
        response = self.client.get("/api/inventory-movements/?search=Prod")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# inventory/models.py líneas 164-165, 274
# 164-165: InventoryLot.clean() con requires_expiration_date sin fecha
# 274: InventoryMovement.clean() ingreso sin warehouse_destination
# ---------------------------------------------------------------------------

class InventoryModelCleanRemainingTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="IMCR01")
        self.warehouse = make_warehouse(self.branch, name="Bodega IMCR")
        cat, _ = ProductCategory.objects.get_or_create(name="Cat IMCR")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_IMCR", defaults={"name": "U"})
        self.product_exp = Product.objects.create(
            name="Prod Exp IMCR", category=cat, unit=unit,
            requires_expiration_date=True, is_active=True
        )
        self.product_simple = make_product(name="Prod Simple IMCR")

    def test_lot_clean_falla_si_requiere_fecha_vencimiento_sin_fecha(self):
        """Líneas 164-165: requires_expiration_date=True y expiration_date=None."""
        lot = InventoryLot(
            warehouse=self.warehouse,
            product=self.product_exp,
            lot_number="L-EXP",
            quantity=Decimal("5"),
            expiration_date=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            lot.clean()
        self.assertIn("vencimiento", str(ctx.exception).lower())

    def test_movement_clean_ingreso_sin_warehouse_destination(self):
        """Línea 274: TYPE_PURCHASE_IN sin warehouse_destination → error."""
        movement = InventoryMovement(
            movement_type=InventoryMovement.TYPE_PURCHASE_IN,
            product=self.product_simple,
            quantity=Decimal("5"),
            warehouse_destination=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            movement.clean()
        self.assertIn("destino", str(ctx.exception).lower())

    def test_movement_clean_ajuste_positivo_sin_destino(self):
        """TYPE_ADJUSTMENT_IN también requiere destino."""
        movement = InventoryMovement(
            movement_type=InventoryMovement.TYPE_ADJUSTMENT_IN,
            product=self.product_simple,
            quantity=Decimal("3"),
            warehouse_destination=None,
        )
        with self.assertRaises(ValidationError):
            movement.clean()

    def test_movement_clean_branch_loan_return_sin_destino(self):
        """TYPE_BRANCH_LOAN_RETURN requiere warehouse_destination."""
        movement = InventoryMovement(
            movement_type=InventoryMovement.TYPE_BRANCH_LOAN_RETURN,
            product=self.product_simple,
            quantity=Decimal("3"),
            warehouse_destination=None,
        )
        with self.assertRaises(ValidationError):
            movement.clean()


# ---------------------------------------------------------------------------
# inventory/services.py líneas 23, 120, 138, 217-218, 241, 251-252, 271
# 23: to_decimal(None) → Decimal("0")
# 120: lote existente → lot.supplier se actualiza si se pasa supplier y lot no tenía
# 138: increase_stock con movement_type explícito
# 217-218: decrease_stock → lot.quantity > 0 pero se consume parcial (no STATUS_CONSUMED)
# 241: adjust_stock con cantidad negativa → delega a decrease_stock
# 251-252, 271: transfer_stock_between_warehouses con lot
# ---------------------------------------------------------------------------

class InventoryServicesRemainingTests(TestCase):

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="ISSR01")
        self.w1 = make_warehouse(self.branch, name="W ISSR1")
        self.w2 = make_warehouse(self.branch, name="W ISSR2")
        self.product = make_product(name="Prod ISSR")
        make_stock(self.w1, self.product, quantity=Decimal("100"))
        from apps.suppliers.models import Supplier
        self.supplier = Supplier.objects.create(name="Supplier ISSR", rut="76650001-1", is_active=True)

    def test_to_decimal_none(self):
        """Línea 23: to_decimal(None) → Decimal('0')."""
        from apps.inventory.services import to_decimal
        self.assertEqual(to_decimal(None), Decimal("0"))

    def test_increase_con_supplier_actualiza_lot_supplier(self):
        """Línea 120: si lot ya existe sin supplier y se pasa supplier → se asigna."""
        from apps.inventory.services import increase_stock
        # Primera llamada sin supplier
        increase_stock(
            warehouse=self.w1, product=self.product,
            quantity=Decimal("5"), lot_number="LOT-SUPP-UPD",
            supplier=None,
        )
        # Segunda llamada con supplier → lot.supplier debe actualizarse
        result = increase_stock(
            warehouse=self.w1, product=self.product,
            quantity=Decimal("3"), lot_number="LOT-SUPP-UPD",
            supplier=self.supplier,
        )
        lot = result["lot"]
        self.assertEqual(lot.supplier, self.supplier)

    def test_increase_con_movement_type_explicito(self):
        """Línea 138: movement_type=TYPE_ADJUSTMENT_IN se pasa al movimiento."""
        from apps.inventory.services import increase_stock
        result = increase_stock(
            warehouse=self.w1, product=self.product,
            quantity=Decimal("7"),
            movement_type=InventoryMovement.TYPE_ADJUSTMENT_IN,
            reason="Ajuste test",
        )
        self.assertEqual(result["movement"].movement_type, InventoryMovement.TYPE_ADJUSTMENT_IN)

    def test_decrease_lot_parcial_no_marca_consumido(self):
        """Líneas 217-218: lot.quantity > 0 después de decrease → status permanece AVAILABLE."""
        from apps.inventory.services import decrease_stock
        lot = InventoryLot.objects.create(
            warehouse=self.w1,
            product=self.product,
            lot_number="LOT-PARCIAL",
            quantity=Decimal("20"),
            status=InventoryLot.STATUS_AVAILABLE,
        )
        result = decrease_stock(
            warehouse=self.w1, product=self.product,
            quantity=Decimal("5"), lot=lot,
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("15"))
        self.assertEqual(lot.status, InventoryLot.STATUS_AVAILABLE)

    def test_adjust_negativo_delega_a_decrease(self):
        """Línea 241: adjust_stock cantidad negativa → llama decrease_stock."""
        from apps.inventory.services import adjust_stock
        stock_before = InventoryStock.objects.get(warehouse=self.w1, product=self.product).quantity
        result = adjust_stock(
            warehouse=self.w1, product=self.product,
            quantity=Decimal("-10"),
            reason="Ajuste negativo test",
        )
        stock_after = InventoryStock.objects.get(warehouse=self.w1, product=self.product).quantity
        self.assertEqual(stock_after, stock_before - Decimal("10"))
        self.assertEqual(result["movement"].movement_type, InventoryMovement.TYPE_ADJUSTMENT_OUT)

    def test_transfer_con_lot_pasa_datos_lote(self):
        """Líneas 251-252, 271: transfer_stock_between_warehouses con lot."""
        from apps.inventory.services import transfer_stock_between_warehouses
        lot = InventoryLot.objects.create(
            warehouse=self.w1,
            product=self.product,
            lot_number="LOT-TRANSFER",
            quantity=Decimal("30"),
            status=InventoryLot.STATUS_AVAILABLE,
            supplier=self.supplier,
        )
        result = transfer_stock_between_warehouses(
            origin_warehouse=self.w1,
            destination_warehouse=self.w2,
            product=self.product,
            quantity=Decimal("10"),
            lot=lot,
            reason="Transfer con lote",
        )
        # En destino debe haberse creado lote con mismo lot_number
        dest_lot = InventoryLot.objects.filter(
            warehouse=self.w2, product=self.product, lot_number="LOT-TRANSFER"
        ).first()
        self.assertIsNotNone(dest_lot)
        self.assertEqual(dest_lot.quantity, Decimal("10"))


# ---------------------------------------------------------------------------
# inventory/services.py:120 → lot.supplier update cuando lot ya existe sin supplier
# inventory/services.py:217-218 → decrease lot parcial (cantidad > 0, no CONSUMED)
# inventory/services.py:241 → adjust negativo delega a decrease (rama else)
# inventory/services.py:251-252 → transfer con lot (lot.lot_number, expiration, supplier)
# inventory/services.py:271 → transfer increase_result retorna lot
# inventory/views.py:81,86 → low_stock: branch_product con threshold None, y > threshold
# inventory/views.py:214 → _get_supplier con uuid=None → retorna None
# ---------------------------------------------------------------------------

class InventoryServicesSupplierUpdateTests(TestCase):
    """inventory/services.py línea 120: lot sin supplier + increase con supplier → actualiza."""

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="ISSU01")
        self.warehouse = make_warehouse(self.branch, name="Bodega ISSU")
        self.product = make_product(name="Prod ISSU")
        make_stock(self.warehouse, self.product, quantity=Decimal("0"))
        from apps.suppliers.models import Supplier
        self.supplier = Supplier.objects.create(name="Supp ISSU", rut="76455001-1", is_active=True)

    def test_lot_supplier_se_actualiza_en_segunda_llamada(self):
        """Línea 120: if supplier and not lot.supplier → lot.supplier = supplier."""
        from apps.inventory.services import increase_stock
        # Primera llamada sin supplier → lot creado sin supplier
        increase_stock(
            warehouse=self.warehouse, product=self.product,
            quantity=Decimal("3"), lot_number="SUPP-UPD-LOT",
        )
        # Segunda llamada con supplier → lot.supplier se actualiza
        result = increase_stock(
            warehouse=self.warehouse, product=self.product,
            quantity=Decimal("2"), lot_number="SUPP-UPD-LOT",
            supplier=self.supplier,
        )
        lot = result["lot"]
        lot.refresh_from_db()
        self.assertEqual(lot.supplier, self.supplier)


class InventoryServicesDecreaseLotPartialTests(TestCase):
    """inventory/services.py líneas 217-218: lot parcial → no se marca CONSUMED."""

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="ISDLP01")
        self.warehouse = make_warehouse(self.branch, name="Bodega ISDLP")
        self.product = make_product(name="Prod ISDLP")
        make_stock(self.warehouse, self.product, quantity=Decimal("50"))

    def test_decrease_parcial_lot_mantiene_status_available(self):
        """Líneas 217-218: lot.quantity > 0 → status permanece AVAILABLE."""
        from apps.inventory.services import decrease_stock
        lot = InventoryLot.objects.create(
            warehouse=self.warehouse, product=self.product,
            lot_number="LOT-PARCIAL-DEC",
            quantity=Decimal("20"),
            status=InventoryLot.STATUS_AVAILABLE,
        )
        decrease_stock(
            warehouse=self.warehouse, product=self.product,
            quantity=Decimal("5"), lot=lot,
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("15"))
        self.assertEqual(lot.status, InventoryLot.STATUS_AVAILABLE)


class InventoryServicesAdjustNegativeTests(TestCase):
    """inventory/services.py línea 241: adjust con cantidad negativa → decrease_stock."""

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="ISAN01")
        self.warehouse = make_warehouse(self.branch, name="Bodega ISAN")
        self.product = make_product(name="Prod ISAN")
        make_stock(self.warehouse, self.product, quantity=Decimal("50"))

    def test_adjust_negativo_crea_movimiento_adjustment_out(self):
        """Línea 241: adjust_stock cantidad < 0 → llama decrease → TYPE_ADJUSTMENT_OUT."""
        from apps.inventory.services import adjust_stock
        result = adjust_stock(
            warehouse=self.warehouse, product=self.product,
            quantity=Decimal("-5"), reason="Ajuste negativo real",
        )
        self.assertEqual(
            result["movement"].movement_type, InventoryMovement.TYPE_ADJUSTMENT_OUT
        )
        stock = InventoryStock.objects.get(warehouse=self.warehouse, product=self.product)
        self.assertEqual(stock.quantity, Decimal("45"))


class InventoryServicesTransferWithLotTests(TestCase):
    """inventory/services.py líneas 251-252, 271: transfer con lot."""

    def setUp(self):
        _, self.branch = make_org_and_branch(branch_code="ISTWL01")
        self.w1 = make_warehouse(self.branch, name="W ISTWL1")
        self.w2 = make_warehouse(self.branch, name="W ISTWL2")
        self.product = make_product(name="Prod ISTWL")
        make_stock(self.w1, self.product, quantity=Decimal("50"))
        from apps.suppliers.models import Supplier
        self.supplier = Supplier.objects.create(name="Supp ISTWL", rut="76566001-1", is_active=True)

    def test_transfer_con_lot_crea_lote_en_destino(self):
        """Líneas 251-252: lot.lot_number, lot.expiration_date, lot.supplier."""
        from apps.inventory.services import transfer_stock_between_warehouses
        from datetime import date
        lot = InventoryLot.objects.create(
            warehouse=self.w1, product=self.product,
            lot_number="LOT-XFER-REAL",
            quantity=Decimal("20"),
            status=InventoryLot.STATUS_AVAILABLE,
            supplier=self.supplier,
            expiration_date=date(2026, 12, 31),
        )
        result = transfer_stock_between_warehouses(
            origin_warehouse=self.w1, destination_warehouse=self.w2,
            product=self.product, quantity=Decimal("10"), lot=lot,
        )
        # Línea 271: increase_result["lot"] no es None
        self.assertIsNotNone(result["increase"]["lot"])
        # El lote en destino tiene el mismo número
        dest_lot = InventoryLot.objects.filter(
            warehouse=self.w2, product=self.product, lot_number="LOT-XFER-REAL"
        ).first()
        self.assertIsNotNone(dest_lot)
        self.assertEqual(dest_lot.quantity, Decimal("10"))
        self.assertEqual(dest_lot.supplier, self.supplier)


class InventoryViewsRemainingTests(TestCase):
    """
    inventory/views.py:
    - 81: low_stock → branch_product sin threshold (critical=0, min=0) → threshold falsy → continue
    - 86: stock.available_quantity > threshold → no se incluye en low_stock
    - 214: _get_supplier(None) → return None
    """

    def setUp(self):
        self.client = APIClient()
        _, self.branch = make_org_and_branch(branch_code="IVRT01")
        self.warehouse = make_warehouse(self.branch, name="Bodega IVRT")
        self.admin = create_superuser(username="ivrt_admin", password="pass")
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "ivrt_admin", "password": "pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_low_stock_con_threshold_cero_omite_producto(self):
        """Línea 81: threshold = critical_stock(0) or min_stock(0) = 0 (falsy) → continue."""
        self._auth()
        from apps.products.models import ProductCategory, UnitOfMeasure, Product, BranchProduct
        cat, _ = ProductCategory.objects.get_or_create(name="Cat IVRT")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_IVRT", defaults={"name": "U"})
        prod = Product.objects.create(name="Prod Threshold Cero", category=cat, unit=unit, is_active=True)
        BranchProduct.objects.create(
            branch=self.branch, product=prod,
            critical_stock=Decimal("0"), min_stock=Decimal("0"), is_active=True,
        )
        make_stock(self.warehouse, prod, quantity=Decimal("5"))

        resp = self.client.get("/api/inventory-stocks/low_stock/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.json()["data"]
        if isinstance(results, dict):
            results = results.get("results", [])
        # El producto con threshold=0 no debe aparecer
        names = [str(r) for r in results]
        self.assertNotIn("Prod Threshold Cero", str(names))

    def test_low_stock_con_stock_mayor_a_threshold_no_incluye(self):
        """Línea 86: available_quantity > threshold → no se agrega a low_stock_items."""
        self._auth()
        from apps.products.models import ProductCategory, UnitOfMeasure, Product, BranchProduct
        cat, _ = ProductCategory.objects.get_or_create(name="Cat IVRT2")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_IVRT2", defaults={"name": "U"})
        prod = Product.objects.create(name="Prod Suficiente", category=cat, unit=unit, is_active=True)
        BranchProduct.objects.create(
            branch=self.branch, product=prod,
            critical_stock=Decimal("5"), is_active=True,
        )
        # Stock muy por encima del threshold
        make_stock(self.warehouse, prod, quantity=Decimal("100"))

        resp = self.client.get("/api/inventory-stocks/low_stock/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.json()["data"]
        if isinstance(results, dict):
            results = results.get("results", [])
        # El producto con stock suficiente no debe aparecer
        content = str(resp.content)
        self.assertNotIn("Prod Suficiente", content)

    def test_increase_con_supplier_uuid_none_retorna_none(self):
        """Línea 214: _get_supplier(None) → return None → supplier=None en increase_stock."""
        self._auth()
        from apps.products.models import ProductCategory, UnitOfMeasure, Product
        cat, _ = ProductCategory.objects.get_or_create(name="Cat IVRT3")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_IVRT3", defaults={"name": "U"})
        prod = Product.objects.create(name="Prod Supplier None", category=cat, unit=unit, is_active=True)

        resp = self.client.post(
            "/api/inventory-movements/increase/",
            {
                "warehouse_uuid": str(self.warehouse.uuid),
                "product_uuid": str(prod.uuid),
                "quantity": "5.000",
                "supplier_uuid": None,  # None → _get_supplier retorna None
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.json()["data"]["lot"])
