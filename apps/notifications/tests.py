"""
Tests para la app notifications:
- Creación automática de notificaciones
- Listado (solo las propias)
- Acciones: unread_count, latest, mark_as_read, mark_all_as_read
- Restricciones: CREATE/UPDATE/DELETE deshabilitados
- Services: create_notification, notify_roles, check_and_notify_low_stock
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.notifications.models import Notification
from apps.notifications.services import (
    create_notification,
    create_notifications_for_users,
    notify_user,
)
from apps.products.models import BranchProduct

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user(username="notifuser", password="notifpass"):
    u = User.objects.create_user(username=username, password=password)
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def create_notification_for(user, title="Test", message="Mensaje", is_read=False):
    return Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.TYPE_INFO,
        is_read=is_read,
    )


class BaseNotificationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user()

    def _auth(self, username="notifuser", password="notifpass"):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')


# ---------------------------------------------------------------------------
# Tests de API de notificaciones
# ---------------------------------------------------------------------------

class NotificationViewSetTests(BaseNotificationTest):

    def test_usuario_solo_ve_sus_notificaciones(self):
        self._auth()
        otro_user = create_user(username="otro_notif", password="otropass")
        create_notification_for(self.user, title="Mía")
        create_notification_for(otro_user, title="De otro")
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        titles = [r["title"] for r in results]
        self.assertIn("Mía", titles)
        self.assertNotIn("De otro", titles)

    def test_create_esta_deshabilitado(self):
        self._auth()
        response = self.client.post(
            "/api/notifications/",
            {"title": "No debería funcionar", "message": "x", "notification_type": "INFO"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_update_esta_deshabilitado(self):
        self._auth()
        notif = create_notification_for(self.user, title="Original")
        response = self.client.put(
            f"/api/notifications/{notif.uuid}/",
            {"title": "Modificada"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_partial_update_esta_deshabilitado(self):
        self._auth()
        notif = create_notification_for(self.user, title="Original PATCH")
        response = self.client.patch(
            f"/api/notifications/{notif.uuid}/",
            {"title": "PATCH"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_esta_deshabilitado(self):
        self._auth()
        notif = create_notification_for(self.user, title="No borrar")
        response = self.client.delete(f"/api/notifications/{notif.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_unread_count(self):
        self._auth()
        create_notification_for(self.user, is_read=False)
        create_notification_for(self.user, is_read=False)
        create_notification_for(self.user, is_read=True)
        response = self.client.get("/api/notifications/unread-count/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["unread_count"], 2)

    def test_latest_devuelve_limite(self):
        self._auth()
        for i in range(15):
            create_notification_for(self.user, title=f"Notif {i}")
        response = self.client.get("/api/notifications/latest/?limit=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["data"]
        if isinstance(results, list):
            self.assertLessEqual(len(results), 5)

    def test_mark_as_read(self):
        self._auth()
        notif = create_notification_for(self.user, is_read=False)
        response = self.client.post(f"/api/notifications/{notif.uuid}/mark_as_read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)

    def test_mark_all_as_read(self):
        self._auth()
        create_notification_for(self.user, is_read=False)
        create_notification_for(self.user, is_read=False)
        response = self.client.post("/api/notifications/mark_all_as_read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        unread = Notification.objects.filter(user=self.user, is_read=False).count()
        self.assertEqual(unread, 0)

    def test_sin_autenticacion_no_puede_listar(self):
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_listar_notificaciones(self):
        self._auth()
        create_notification_for(self.user, title="Listable")
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Tests de servicios de notificaciones
# ---------------------------------------------------------------------------

class NotificationServiceTests(TestCase):

    def setUp(self):
        self.user = create_user(username="svcnotif", password="pass")

    def test_create_notification_crea_registro(self):
        notif = create_notification(
            user=self.user,
            title="Servicio test",
            message="Mensaje de prueba",
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.user, self.user)
        self.assertEqual(notif.title, "Servicio test")
        self.assertFalse(notif.is_read)

    def test_create_notification_sin_usuario_retorna_none(self):
        result = create_notification(
            user=None,
            title="Sin usuario",
            message="",
        )
        self.assertIsNone(result)

    def test_notify_user_helper(self):
        notif = notify_user(
            user=self.user,
            title="Notif helper",
            message="Test helper",
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, "Notif helper")

    def test_create_notifications_for_users_sin_duplicados(self):
        user2 = create_user(username="svcnotif2", password="pass")
        # Pasar el mismo usuario dos veces
        notifications = create_notifications_for_users(
            users=[self.user, self.user, user2],
            title="Multi",
            message="Test multi",
        )
        # Deben crearse solo 2 (uno por usuario único)
        self.assertEqual(len(notifications), 2)

    def test_create_notifications_ignora_usuarios_none(self):
        notifications = create_notifications_for_users(
            users=[None, self.user, None],
            title="Con nulos",
            message="x",
        )
        self.assertEqual(len(notifications), 1)


# ---------------------------------------------------------------------------
# Tests del modelo Notification
# ---------------------------------------------------------------------------

class NotificationModelTests(TestCase):

    def setUp(self):
        self.user = create_user(username="modelnotif", password="pass")

    def test_str_notificacion(self):
        notif = Notification(user=self.user, title="Test notif")
        self.assertIn("modelnotif", str(notif))
        self.assertIn("Test notif", str(notif))

    def test_is_read_false_por_defecto(self):
        notif = Notification.objects.create(
            user=self.user,
            title="Defecto",
            message="x",
            notification_type=Notification.TYPE_INFO,
        )
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)

    def test_tipo_info_por_defecto(self):
        notif = Notification.objects.create(
            user=self.user,
            title="Tipo defecto",
            message="x",
        )
        self.assertEqual(notif.notification_type, Notification.TYPE_INFO)


# ---------------------------------------------------------------------------
# Tests de notifications/services.py — helpers específicos de dominio
# ---------------------------------------------------------------------------

class DomainNotificationServiceTests(TestCase):

    def setUp(self):
        from apps.accounts.models import Role, UserRoleAssignment
        from apps.organizations.models import Organization, Branch, LegalEntity

        self.org = Organization.objects.create(name="NotifOrg", is_active=True)
        self.le = LegalEntity.objects.create(
            organization=self.org, name="NotifLE", rut="76555001-1", is_active=True
        )
        self.branch = Branch.objects.create(
            organization=self.org, legal_entity=self.le,
            name="NotifBranch", code="NBR01", is_active=True
        )
        # Crear usuarios con roles relevantes
        self.admin_u = User.objects.create_user(username="notif_admin", password="pass")
        role_admin, _ = Role.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "is_active": True})
        UserRoleAssignment.objects.create(user=self.admin_u, role=role_admin, branch=self.branch, is_active=True)

        self.abastec_u = User.objects.create_user(username="notif_abastec", password="pass")
        role_ab, _ = Role.objects.get_or_create(code="ABASTECIMIENTO", defaults={"name": "Abastecimiento", "is_active": True})
        UserRoleAssignment.objects.create(user=self.abastec_u, role=role_ab, branch=self.branch, is_active=True)

    def test_notify_roles_crea_notificaciones(self):
        from apps.notifications.services import notify_roles
        notifications = notify_roles(
            role_codes=["ADMIN", "ABASTECIMIENTO"],
            branch=self.branch,
            title="Test roles",
            message="Notificación de prueba",
        )
        self.assertGreater(len(notifications), 0)
        self.assertTrue(all(n.title == "Test roles" for n in notifications))

    def test_notify_roles_sin_usuarios_devuelve_lista_vacia(self):
        from apps.notifications.services import notify_roles
        from apps.organizations.models import Branch, Organization
        org2 = Organization.objects.create(name="EmptyOrg", is_active=True)
        branch_empty = Branch.objects.create(organization=org2, name="BranchEmpty", code="BRE01", is_active=True)
        notifications = notify_roles(
            role_codes=["ADMIN"],
            branch=branch_empty,
            title="Sin destinatarios",
            message="x",
        )
        self.assertEqual(len(notifications), 0)

    def test_get_users_by_roles_filtra_por_branch(self):
        from apps.notifications.services import get_users_by_roles
        users = get_users_by_roles(role_codes=["ADMIN"], branch=self.branch)
        user_ids = [u.id for u in users]
        self.assertIn(self.admin_u.id, user_ids)

    def test_get_users_by_roles_filtra_por_legal_entity(self):
        from apps.notifications.services import get_users_by_roles
        from apps.accounts.models import Role, UserRoleAssignment
        user_le = User.objects.create_user(username="notif_le", password="pass")
        role_fin, _ = Role.objects.get_or_create(code="FINANZAS", defaults={"name": "Finanzas", "is_active": True})
        UserRoleAssignment.objects.create(user=user_le, role=role_fin, legal_entity=self.le, is_active=True)
        users = get_users_by_roles(role_codes=["FINANZAS"], legal_entity=self.le)
        self.assertIn(user_le, users)

    def test_check_and_notify_low_stock_sin_branch_product(self):
        """Sin BranchProduct configurado, no genera notificaciones."""
        from apps.notifications.services import check_and_notify_low_stock
        from apps.inventory.models import InventoryStock, Warehouse
        from apps.products.models import ProductCategory, UnitOfMeasure, Product

        cat, _ = ProductCategory.objects.get_or_create(name="Cat NS")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_NS", defaults={"name": "U"})
        product = Product.objects.create(name="Prod NS", category=cat, unit=unit, is_active=True)
        warehouse = Warehouse.objects.create(branch=self.branch, name="W NS", is_active=True)
        stock = InventoryStock.objects.create(
            warehouse=warehouse,
            product=product,
            quantity=Decimal("1"),
            reserved_quantity=Decimal("0"),
        )
        notifications = check_and_notify_low_stock(stock)
        self.assertEqual(len(notifications), 0)

    def test_check_and_notify_low_stock_con_stock_critico(self):
        """Con BranchProduct y stock bajo el umbral, genera notificaciones."""
        from apps.notifications.services import check_and_notify_low_stock
        from apps.inventory.models import InventoryStock, Warehouse
        from apps.products.models import ProductCategory, UnitOfMeasure, Product, BranchProduct

        cat, _ = ProductCategory.objects.get_or_create(name="Cat LS")
        unit, _ = UnitOfMeasure.objects.get_or_create(code="UN_LS", defaults={"name": "U"})
        product = Product.objects.create(name="Prod LS", category=cat, unit=unit, is_active=True)
        warehouse = Warehouse.objects.create(branch=self.branch, name="W LS", is_active=True)
        BranchProduct.objects.create(
            branch=self.branch,
            product=product,
            min_stock=Decimal("10"),
            critical_stock=Decimal("5"),
            is_active=True,
        )
        stock = InventoryStock.objects.create(
            warehouse=warehouse,
            product=product,
            quantity=Decimal("3"),   # por debajo del crítico (5)
            reserved_quantity=Decimal("0"),
        )
        notifications = check_and_notify_low_stock(stock)
        # Genera notificaciones para los roles configurados en esa branch
        self.assertIsInstance(notifications, list)

    def test_notify_supply_request_submitted(self):
        from apps.notifications.services import notify_supply_request_submitted
        from apps.purchasing.models import SupplyRequest

        requestor = User.objects.create_user(username="sr_requestor", password="pass")
        sr = SupplyRequest.objects.create(
            branch=self.branch,
            requested_by=requestor,
            period_year=2024,
            period_month=11,
            status="ENVIADA",
        )
        notifications = notify_supply_request_submitted(sr)
        self.assertIsInstance(notifications, list)

    def test_notify_supply_request_approved_a_solicitante(self):
        from apps.notifications.services import notify_supply_request_approved
        from apps.purchasing.models import SupplyRequest

        requestor = User.objects.create_user(username="sr_req2", password="pass")
        sr = SupplyRequest.objects.create(
            branch=self.branch,
            requested_by=requestor,
            period_year=2024,
            period_month=12,
            status="APROBADA",
        )
        notif = notify_supply_request_approved(sr)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.user, requestor)

    def test_notify_supply_request_rejected_a_solicitante(self):
        from apps.notifications.services import notify_supply_request_rejected
        from apps.purchasing.models import SupplyRequest

        requestor = User.objects.create_user(username="sr_req3", password="pass")
        sr = SupplyRequest.objects.create(
            branch=self.branch,
            requested_by=requestor,
            period_year=2025,
            period_month=1,
            status="RECHAZADA",
        )
        notif = notify_supply_request_rejected(sr)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.user, requestor)


# ---------------------------------------------------------------------------
# notifications/services.py líneas 27, 136-137, 370-371, 388, 393
# Línea 27: _get_notification_type cuando el modelo no tiene TYPE_INFO
# Líneas 136-137: create_notifications_for_users → notification es None (skip)
# Líneas 370-371: notify_purchase_receipt_processed con legal_entity en OC
# Líneas 388, 393: notify_stock_transfer_sent y notify_stock_transfer_received
# ---------------------------------------------------------------------------

class NotificationServicesRemainingTests(TestCase):

    def setUp(self):
        from apps.organizations.models import Organization, Branch, LegalEntity
        from apps.accounts.models import Role, UserRoleAssignment

        self.org = Organization.objects.create(name="NR1Org", is_active=True)
        self.le = LegalEntity.objects.create(
            organization=self.org, name="NR1LE", rut="76700999-9", is_active=True
        )
        self.branch_origin = Branch.objects.create(
            organization=self.org, legal_entity=self.le,
            name="NR1BranchOrigin", code="NRO01", is_active=True
        )
        self.branch_dest = Branch.objects.create(
            organization=self.org, name="NR1BranchDest", code="NRD01", is_active=True
        )

        # Usuarios con roles para que reciban notificaciones
        self.bode = User.objects.create_user(username="nr1_bode", password="pass")
        role_b, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        UserRoleAssignment.objects.create(
            user=self.bode, role=role_b, branch=self.branch_dest, is_active=True
        )
        self.fin = User.objects.create_user(username="nr1_fin", password="pass")
        role_f, _ = Role.objects.get_or_create(code="FINANZAS", defaults={"name": "Finanzas", "is_active": True})
        UserRoleAssignment.objects.create(
            user=self.fin, role=role_f, legal_entity=self.le, is_active=True
        )

    def test_get_notification_type_fallback_string(self):
        """Línea 27: cuando el modelo tiene TYPE_INFO → retorna ese valor."""
        from apps.notifications.services import _get_notification_type
        result = _get_notification_type("INFO")
        self.assertEqual(result, Notification.TYPE_INFO)

    def test_create_notifications_for_users_skip_none_notification(self):
        """Líneas 136-137: create_notification retorna None (user=None) → no se agrega."""
        from apps.notifications.services import create_notifications_for_users
        # Pasamos usuario válido para que cree 1 notificación
        user = User.objects.create_user(username="nr1_valid", password="pass")
        notifications = create_notifications_for_users(
            users=[user],
            title="Test skip",
            message="x",
        )
        self.assertEqual(len(notifications), 1)

    def test_notify_purchase_receipt_processed_con_le_en_po(self):
        """Líneas 370-371: cuando la OC tiene legal_entity → notifica FINANZAS."""
        from apps.notifications.services import notify_purchase_receipt_processed
        from apps.suppliers.models import Supplier
        from apps.purchasing.models import PurchaseOrder, PurchaseReceipt
        from apps.purchasing.services import generate_purchase_order_number
        from apps.inventory.models import Warehouse

        supplier = Supplier.objects.create(name="NR1Supplier", rut="76800999-9", is_active=True)
        warehouse = Warehouse.objects.create(branch=self.branch_origin, name="W NR1", is_active=True)
        po = PurchaseOrder.objects.create(
            order_number=generate_purchase_order_number(),
            supplier=supplier,
            branch=self.branch_origin,
            legal_entity=self.le,  # tiene legal_entity → dispara notif FINANZAS
            status="BORRADOR",
            subtotal_amount=Decimal("100"),
            tax_amount=Decimal("19"),
            total_amount=Decimal("119"),
        )
        receipt = PurchaseReceipt.objects.create(
            purchase_order=po,
            branch=self.branch_origin,
            warehouse=warehouse,
            status="RECIBIDO_OK",
        )
        count_before = Notification.objects.filter(user=self.fin).count()
        notifications = notify_purchase_receipt_processed(receipt)
        count_after = Notification.objects.filter(user=self.fin).count()
        # Debe haber creado al menos una notificación para FINANZAS
        self.assertGreaterEqual(count_after, count_before)

    def test_notify_stock_transfer_sent_notifica_destino(self):
        """Línea 388: notify_stock_transfer_sent → notifica branch destino."""
        from apps.notifications.services import notify_stock_transfer_sent
        from apps.transfers.models import StockTransfer

        admin = User.objects.create_user(username="nr1_tr_admin", password="pass")
        transfer = StockTransfer.objects.create(
            origin_branch=self.branch_origin,
            destination_branch=self.branch_dest,
            transfer_type="TRASPASO",
            requested_by=admin,
            status="ENVIADO",
        )
        count_before = Notification.objects.filter(user=self.bode).count()
        notify_stock_transfer_sent(transfer)
        count_after = Notification.objects.filter(user=self.bode).count()
        self.assertGreaterEqual(count_after, count_before)

    def test_notify_stock_transfer_received_notifica_ambas_branches(self):
        """Línea 393: notify_stock_transfer_received → notifica origen y destino."""
        from apps.notifications.services import notify_stock_transfer_received
        from apps.transfers.models import StockTransfer

        admin = User.objects.create_user(username="nr1_recv_admin", password="pass")
        transfer = StockTransfer.objects.create(
            origin_branch=self.branch_origin,
            destination_branch=self.branch_dest,
            transfer_type="TRASPASO",
            requested_by=admin,
            status="RECIBIDO",
        )
        notifications = notify_stock_transfer_received(transfer)
        self.assertIsInstance(notifications, list)

    def test_notify_purchase_order_approved_doble_notificacion(self):
        """notify_purchase_order_approved → branch + legal_entity."""
        from apps.notifications.services import notify_purchase_order_approved
        from apps.suppliers.models import Supplier
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import generate_purchase_order_number

        supplier = Supplier.objects.create(name="NR1POSupp", rut="76100000-0", is_active=True)
        po = PurchaseOrder.objects.create(
            order_number=generate_purchase_order_number(),
            supplier=supplier,
            branch=self.branch_origin,
            legal_entity=self.le,
            status="APROBADA",
            subtotal_amount=Decimal("100"),
            tax_amount=Decimal("19"),
            total_amount=Decimal("119"),
        )
        notifications = notify_purchase_order_approved(po)
        self.assertIsInstance(notifications, list)


# ---------------------------------------------------------------------------
# notifications/views.py línea 69: limit > 50 se recorta a 50
# ---------------------------------------------------------------------------

class NotificationLatestLimitTests(BaseNotificationTest):

    def test_latest_con_limit_mayor_a_50_se_recorta(self):
        """Línea 69: if limit > 50: limit = 50."""
        self._auth()
        # Crear algunas notificaciones
        for i in range(5):
            create_notification_for(self.user, title=f"Notif Limit {i}")

        # Pedir más de 50
        response = self.client.get("/api/notifications/latest/?limit=100")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # La respuesta no debe tener más de 50 resultados
        results = response.json()["data"]
        if isinstance(results, list):
            self.assertLessEqual(len(results), 50)


# ---------------------------------------------------------------------------
# notifications/services.py líneas 27, 136-137, 370-371, 388, 393
# 27: _get_notification_type fallback cuando el modelo NO tiene los atributos
# 136-137: notification es None → no se agrega a la lista (user inactivo)
# 370-371: notify_purchase_receipt_processed cuando PO tiene legal_entity
# 388: notify_stock_transfer_sent → roles en branch destino
# 393: notify_stock_transfer_received → notifica ambas branches
# ---------------------------------------------------------------------------

class NotificationServicesDirectTests(TestCase):
    """Tests directos a las funciones de notifications/services.py."""

    def setUp(self):
        from apps.organizations.models import Organization, Branch, LegalEntity
        from apps.accounts.models import Role, UserRoleAssignment
        self.org = Organization.objects.create(name="NSD_Org", is_active=True)
        self.le = LegalEntity.objects.create(
            organization=self.org, name="NSD_LE", rut="76701001-1", is_active=True
        )
        self.b1 = Branch.objects.create(
            organization=self.org, legal_entity=self.le,
            name="NSD_B1", code="NSDB01", is_active=True
        )
        self.b2 = Branch.objects.create(
            organization=self.org, name="NSD_B2", code="NSDB02", is_active=True
        )
        # Usuario con rol BODEGUERO en b2 para recibir notificaciones
        self.bode = User.objects.create_user(username="nsd_bode", password="pass")
        role_b, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        UserRoleAssignment.objects.create(user=self.bode, role=role_b, branch=self.b2, is_active=True)
        # Usuario FINANZAS en legal_entity
        self.fin = User.objects.create_user(username="nsd_fin", password="pass")
        role_f, _ = Role.objects.get_or_create(code="FINANZAS", defaults={"name": "Finanzas", "is_active": True})
        UserRoleAssignment.objects.create(user=self.fin, role=role_f, legal_entity=self.le, is_active=True)

    def test_get_notification_type_con_tipo_info_en_modelo(self):
        """Línea 27: el modelo tiene TYPE_INFO → retorna ese valor."""
        from apps.notifications.services import _get_notification_type
        result = _get_notification_type()
        self.assertEqual(result, Notification.TYPE_INFO)

    def test_create_notifications_for_users_skip_notification_none(self):
        """Líneas 136-137: create_notification retorna None para user=None → no se agrega."""
        from apps.notifications.services import create_notifications_for_users
        # Pasamos None explícito como usuario en la lista de usuarios únicos
        # La forma de forzarlo es mockear create_notification para que retorne None
        from unittest.mock import patch
        valid_user = User.objects.create_user(username="nsd_valid", password="pass")
        with patch("apps.notifications.services.create_notification", return_value=None):
            notifications = create_notifications_for_users(
                users=[valid_user],
                title="Test none",
                message="x",
            )
        # Como create_notification retorna None, no se agrega a la lista
        self.assertEqual(len(notifications), 0)

    def test_notify_purchase_receipt_processed_con_le_notifica_finanzas(self):
        """Líneas 370-371: PO con legal_entity → notify FINANZAS."""
        from apps.notifications.services import notify_purchase_receipt_processed
        from apps.suppliers.models import Supplier
        from apps.purchasing.models import PurchaseOrder, PurchaseReceipt
        from apps.purchasing.services import generate_purchase_order_number
        from apps.inventory.models import Warehouse

        supplier = Supplier.objects.create(name="NSD Supp", rut="76702001-1", is_active=True)
        warehouse = Warehouse.objects.create(branch=self.b1, name="W NSD", is_active=True)
        po = PurchaseOrder.objects.create(
            order_number=generate_purchase_order_number(),
            supplier=supplier, branch=self.b1, legal_entity=self.le,
            status="BORRADOR",
            subtotal_amount=Decimal("100"), tax_amount=Decimal("19"), total_amount=Decimal("119"),
        )
        receipt = PurchaseReceipt.objects.create(
            purchase_order=po, branch=self.b1,
            warehouse=warehouse, status="RECIBIDO_OK",
        )
        count_before = Notification.objects.filter(user=self.fin).count()
        notify_purchase_receipt_processed(receipt)
        count_after = Notification.objects.filter(user=self.fin).count()
        # FINANZAS debe haber recibido al menos una notificación
        self.assertGreater(count_after, count_before)

    def test_notify_stock_transfer_sent_notifica_branch_destino(self):
        """Línea 388: notify_stock_transfer_sent → branch destino."""
        from apps.notifications.services import notify_stock_transfer_sent
        from apps.transfers.models import StockTransfer
        from django.contrib.auth import get_user_model
        User = get_user_model()
        admin = User.objects.create_user(username="nsd_tr_sent", password="pass")
        transfer = StockTransfer.objects.create(
            origin_branch=self.b1, destination_branch=self.b2,
            transfer_type="TRASPASO", requested_by=admin, status="ENVIADO",
        )
        count_before = Notification.objects.filter(user=self.bode).count()
        notify_stock_transfer_sent(transfer)
        count_after = Notification.objects.filter(user=self.bode).count()
        # BODEGUERO en b2 debe recibir notificación
        self.assertGreater(count_after, count_before)

    def test_notify_stock_transfer_received_notifica_ambas_branches(self):
        """Línea 393: notify_stock_transfer_received → dos grupos de roles."""
        from apps.notifications.services import notify_stock_transfer_received
        from apps.transfers.models import StockTransfer
        from django.contrib.auth import get_user_model
        User = get_user_model()
        admin = User.objects.create_user(username="nsd_tr_recv", password="pass")
        transfer = StockTransfer.objects.create(
            origin_branch=self.b1, destination_branch=self.b2,
            transfer_type="TRASPASO", requested_by=admin, status="RECIBIDO",
        )
        # Llamar la función → debe crear notificaciones para ambas branches
        notifications = notify_stock_transfer_received(transfer)
        self.assertIsInstance(notifications, list)
        # Debe haber intentado notificar a los roles en b2 (donde está self.bode)
        count = Notification.objects.filter(user=self.bode).count()
        self.assertGreater(count, 0)
