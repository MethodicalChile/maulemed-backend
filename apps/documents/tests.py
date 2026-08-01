"""
Tests para la app documents:
- Document: CRUD
- Permisos: CanManageDocuments
- uploaded_by se asigna automáticamente
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.documents.models import Document

User = get_user_model()


def make_superuser(username="docadmin", password="docpass"):
    u = User.objects.create_user(username=username, password=password, is_superuser=True, is_staff=True)
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def make_user_role(username, password, role_code):
    user = User.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(code=role_code, defaults={"name": role_code, "is_active": True})
    UserRoleAssignment.objects.create(user=user, role=role, is_active=True)
    UserProfile.objects.get_or_create(user=user, defaults={})
    return user


class DocumentTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = make_superuser()

    def _auth(self, username="docadmin", password="docpass"):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_crear_documento(self):
        self._auth()
        response = self.client.post(
            "/api/documents/",
            {
                "document_type": Document.TYPE_INVOICE,
                "file_name": "factura_001.pdf",
                "file_url": "https://storage.example.com/factura_001.pdf",
                "file_size": 204800,
                "mime_type": "application/pdf",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()["data"]
        self.assertEqual(data["file_name"], "factura_001.pdf")
        # uploaded_by se asigna automáticamente al usuario autenticado
        self.assertIsNotNone(data.get("uploaded_by"))

    def test_listar_documentos(self):
        self._auth()
        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_obtener_documento_por_uuid(self):
        self._auth()
        doc = Document.objects.create(
            document_type=Document.TYPE_OTHER,
            file_name="test.pdf",
            uploaded_by=self.admin,
        )
        response = self.client.get(f"/api/documents/{doc.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["file_name"], "test.pdf")

    def test_actualizar_documento(self):
        self._auth()
        doc = Document.objects.create(
            document_type=Document.TYPE_OTHER,
            file_name="original.pdf",
            uploaded_by=self.admin,
        )
        response = self.client.patch(
            f"/api/documents/{doc.uuid}/",
            {"file_name": "actualizado.pdf"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["file_name"], "actualizado.pdf")

    def test_soft_delete_documento(self):
        self._auth()
        doc = Document.objects.create(
            document_type=Document.TYPE_OTHER,
            file_name="borrar.pdf",
            uploaded_by=self.admin,
        )
        response = self.client.delete(f"/api/documents/{doc.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertIsNotNone(doc.deleted_at)

    def test_filtrar_por_tipo_documento(self):
        self._auth()
        Document.objects.create(
            document_type=Document.TYPE_INVOICE,
            file_name="factura.pdf",
            uploaded_by=self.admin,
        )
        Document.objects.create(
            document_type=Document.TYPE_OTHER,
            file_name="otro.pdf",
            uploaded_by=self.admin,
        )
        response = self.client.get(f"/api/documents/?document_type={Document.TYPE_INVOICE}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_sin_autenticacion_no_puede_listar(self):
        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_secretaria_no_puede_gestionar_documentos(self):
        """SECRETARIA no está en CanManageDocuments."""
        make_user_role("sec_doc", "pass123", "SECRETARIA")
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "sec_doc", "password": "pass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')
        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bodeguero_puede_gestionar_documentos(self):
        """BODEGUERO está en CanManageDocuments."""
        make_user_role("bode_doc", "pass123", "BODEGUERO")
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "bode_doc", "password": "pass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')
        response = self.client.get("/api/documents/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_str_documento_con_nombre(self):
        doc = Document(file_name="archivo.pdf")
        self.assertEqual(str(doc), "archivo.pdf")


class DocumentModelTests(TestCase):

    def test_tipos_documento_disponibles(self):
        tipos = [choice[0] for choice in Document.DOCUMENT_TYPE_CHOICES]
        self.assertIn(Document.TYPE_INVOICE, tipos)
        self.assertIn(Document.TYPE_PURCHASE_ORDER_PDF, tipos)
        self.assertIn(Document.TYPE_DISPATCH_GUIDE, tipos)
        self.assertIn(Document.TYPE_CREDIT_NOTE, tipos)
        self.assertIn(Document.TYPE_OTHER, tipos)
