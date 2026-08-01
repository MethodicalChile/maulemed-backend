"""
Tests para la app suppliers:
- Supplier, SupplierProduct, SupplierProductPrice
- Permisos: CanManageSuppliers (lectura: ADMIN/GERENTE/ABASTECIMIENTO/FINANZAS)
- Validaciones y constraints
"""
from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.products.models import ProductCategory, UnitOfMeasure, Product
from apps.suppliers.models import Supplier, SupplierProduct, SupplierProductPrice

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_superuser(username="supadmin", password="suppass"):
    u = User.objects.create_user(username=username, password=password, is_superuser=True, is_staff=True)
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def make_user_role(username, password, role_code):
    user = User.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(code=role_code, defaults={"name": role_code, "is_active": True})
    UserRoleAssignment.objects.create(user=user, role=role, is_active=True)
    UserProfile.objects.get_or_create(user=user, defaults={})
    return user


def make_supplier(name="Proveedor Test", rut="76100001-1"):
    return Supplier.objects.create(name=name, rut=rut, is_active=True)


def make_product(name="Prod Sup"):
    cat, _ = ProductCategory.objects.get_or_create(name="Cat Sup")
    unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_S", defaults={"name": "Unidad"})
    return Product.objects.create(name=name, category=cat, unit=unit, is_active=True)


class BaseSupplierTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = make_superuser()

    def _auth(self, username="supadmin", password="suppass"):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def _auth_admin(self):
        self._auth()


# ---------------------------------------------------------------------------
# Tests de Supplier
# ---------------------------------------------------------------------------

class SupplierTests(BaseSupplierTest):

    def test_crear_proveedor(self):
        self._auth_admin()
        response = self.client.post(
            "/api/suppliers/",
            {
                "name": "Proveedor Nuevo",
                "rut": "76200001-1",
                "email": "proveedor@test.com",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["data"]["name"], "Proveedor Nuevo")

    def test_rut_unico_proveedor(self):
        self._auth_admin()
        make_supplier(name="Prov Existente", rut="76300001-1")
        response = self.client.post(
            "/api/suppliers/",
            {"name": "Otro", "rut": "76300001-1", "is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_listar_proveedores(self):
        self._auth_admin()
        response = self.client.get("/api/suppliers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_obtener_proveedor_por_uuid(self):
        self._auth_admin()
        supplier = make_supplier(name="Prov GET", rut="76400001-1")
        response = self.client.get(f"/api/suppliers/{supplier.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_actualizar_proveedor(self):
        self._auth_admin()
        supplier = make_supplier(name="Prov Original", rut="76500001-5")
        response = self.client.patch(
            f"/api/suppliers/{supplier.uuid}/",
            {"name": "Prov Actualizado"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["name"], "Prov Actualizado")

    def test_soft_delete_proveedor(self):
        self._auth_admin()
        supplier = make_supplier(name="Prov Borrar", rut="76600001-9")
        response = self.client.delete(f"/api/suppliers/{supplier.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        supplier.refresh_from_db()
        self.assertIsNotNone(supplier.deleted_at)

    def test_buscar_proveedor_por_nombre(self):
        self._auth_admin()
        make_supplier(name="Proveedor Buscable", rut="76700001-7")
        response = self.client.get("/api/suppliers/?search=Buscable")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        names = [s["name"] for s in results]
        self.assertIn("Proveedor Buscable", names)

    def test_str_proveedor(self):
        supplier = Supplier(name="Proveedor STR")
        self.assertEqual(str(supplier), "Proveedor STR")

    def test_sin_autenticacion_no_puede_listar(self):
        response = self.client.get("/api/suppliers/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bodeguero_no_puede_leer_proveedores(self):
        """BODEGUERO no está en read_roles de CanManageSuppliers."""
        make_user_role("bode_sup", "pass123", "BODEGUERO")
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "bode_sup", "password": "pass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')
        response = self.client.get("/api/suppliers/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_finanzas_puede_leer_proveedores(self):
        """FINANZAS está en read_roles de CanManageSuppliers."""
        make_user_role("fin_sup", "pass123", "FINANZAS")
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "fin_sup", "password": "pass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')
        response = self.client.get("/api/suppliers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Tests de SupplierProduct
# ---------------------------------------------------------------------------

class SupplierProductTests(BaseSupplierTest):

    def setUp(self):
        super().setUp()
        self.supplier = make_supplier(name="Prov SP", rut="76800001-8")
        self.product = make_product("Prod SP")

    def test_crear_supplier_product(self):
        self._auth_admin()
        response = self.client.post(
            "/api/supplier-products/",
            {
                "supplier": self.supplier.id,
                "product": self.product.id,
                "last_price": "1500.00",
                "currency": "CLP",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unique_supplier_product(self):
        self._auth_admin()
        SupplierProduct.objects.create(
            supplier=self.supplier,
            product=self.product,
            is_active=True,
        )
        response = self.client.post(
            "/api/supplier-products/",
            {
                "supplier": self.supplier.id,
                "product": self.product.id,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_listar_supplier_products(self):
        self._auth_admin()
        response = self.client.get("/api/supplier-products/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_str_supplier_product(self):
        sp = SupplierProduct(supplier=self.supplier, product=self.product)
        self.assertIn("Prov SP", str(sp))
        self.assertIn("Prod SP", str(sp))


# ---------------------------------------------------------------------------
# Tests de SupplierProductPrice
# ---------------------------------------------------------------------------

class SupplierProductPriceTests(BaseSupplierTest):

    def setUp(self):
        super().setUp()
        supplier = make_supplier(name="Prov PP", rut="76900001-0")
        product = make_product("Prod PP")
        self.supplier_product = SupplierProduct.objects.create(
            supplier=supplier,
            product=product,
            is_active=True,
        )

    def test_crear_precio_proveedor(self):
        self._auth_admin()
        response = self.client.post(
            "/api/supplier-product-prices/",
            {
                "supplier_product": self.supplier_product.id,
                "price": "2500.00",
                "currency": "CLP",
                "valid_from": str(date.today()),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["data"]["price"], "2500.00")

    def test_listar_precios(self):
        self._auth_admin()
        response = self.client.get("/api/supplier-product-prices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_str_precio(self):
        price = SupplierProductPrice(
            supplier_product=self.supplier_product,
            price=Decimal("1000"),
            valid_from=date.today(),
        )
        self.assertIn("1000", str(price))
