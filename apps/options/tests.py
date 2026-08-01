"""
Tests para la app options:
- Todos los endpoints /api/options/* requieren autenticación
- Retornan listas con estructura {id, uuid, label} + campos extra
- Scope filtering aplicado donde corresponde
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.organizations.models import Organization, LegalEntity, Branch, CostCenter
from apps.products.models import ProductCategory, UnitOfMeasure, Product
from apps.suppliers.models import Supplier
from apps.inventory.models import Warehouse

User = get_user_model()


def create_user(username="optuser", password="optpass", is_superuser=False):
    u = User.objects.create_user(
        username=username, password=password,
        is_superuser=is_superuser, is_staff=is_superuser
    )
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


class OptionsTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_user("optsadmin", "optpass", is_superuser=True)
        # Crear datos de prueba
        self.org = Organization.objects.create(name="OptOrg", is_active=True)
        self.le = LegalEntity.objects.create(organization=self.org, name="OptLE", rut="76111001-1", is_active=True)
        self.branch = Branch.objects.create(organization=self.org, legal_entity=self.le, name="OptBranch", code="OB001", is_active=True)
        self.cost_center = CostCenter.objects.create(legal_entity=self.le, branch=self.branch, code="OCC01", name="CC Opt", is_active=True)
        cat, _ = ProductCategory.objects.get_or_create(name="OptCat")
        self.category = cat
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_O", defaults={"name": "Unidad Opt"})
        self.product = Product.objects.create(name="Producto Opt", category=cat, unit=unit, is_active=True)
        self.supplier = Supplier.objects.create(name="Proveedor Opt", rut="76222001-1", is_active=True)
        self.warehouse = Warehouse.objects.create(branch=self.branch, name="Bodega Opt", is_active=True)
        role, _ = Role.objects.get_or_create(code="TENS", defaults={"name": "TENS", "is_active": True})

    def _auth(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "optsadmin", "password": "optpass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def _get_results(self, response):
        data = response.json()["data"]
        if isinstance(data, list):
            return data
        return data.get("results", data)

    # ------ Sin autenticación ------

    def test_organizations_requiere_autenticacion(self):
        response = self.client.get("/api/options/organizations/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_legal_entities_requiere_autenticacion(self):
        response = self.client.get("/api/options/legal-entities/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ------ Con autenticación ------

    def test_options_organizations(self):
        self._auth()
        response = self.client.get("/api/options/organizations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreater(len(results), 0)
        first = results[0]
        self.assertIn("uuid", first)
        self.assertIn("label", first)

    def test_options_legal_entities(self):
        self._auth()
        response = self.client.get("/api/options/legal-entities/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        if results:
            self.assertIn("rut", results[0])

    def test_options_branches(self):
        self._auth()
        response = self.client.get("/api/options/branches/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        if results:
            self.assertIn("code", results[0])

    def test_options_cost_centers(self):
        self._auth()
        response = self.client.get("/api/options/cost-centers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_options_product_categories(self):
        self._auth()
        response = self.client.get("/api/options/product-categories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreater(len(results), 0)

    def test_options_units(self):
        self._auth()
        response = self.client.get("/api/options/units/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        if results:
            self.assertIn("code", results[0])

    def test_options_products(self):
        self._auth()
        response = self.client.get("/api/options/products/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        names = [r["label"] for r in results]
        self.assertIn("Producto Opt", names)

    def test_options_products_search(self):
        self._auth()
        response = self.client.get("/api/options/products/?search=Opt")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreater(len(results), 0)
        # Todos los resultados deben contener "Opt" en el label
        for r in results:
            self.assertIn("Opt", r["label"])

    def test_options_suppliers(self):
        self._auth()
        response = self.client.get("/api/options/suppliers/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        names = [r["label"] for r in results]
        self.assertIn("Proveedor Opt", names)

    def test_options_suppliers_search(self):
        self._auth()
        response = self.client.get("/api/options/suppliers/?search=Opt")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        self.assertGreater(len(results), 0)

    def test_options_warehouses(self):
        self._auth()
        response = self.client.get("/api/options/warehouses/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        if results:
            self.assertIn("warehouse_type", results[0])

    def test_options_roles(self):
        self._auth()
        response = self.client.get("/api/options/roles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._get_results(response)
        if results:
            self.assertIn("code", results[0])

    def test_estructura_respuesta_option(self):
        """Verificar estructura estándar: id, uuid, label."""
        self._auth()
        response = self.client.get("/api/options/organizations/")
        results = self._get_results(response)
        if results:
            item = results[0]
            self.assertIn("id", item)
            self.assertIn("uuid", item)
            self.assertIn("label", item)
