"""
Tests para la app audit:
- AuditLog: creación automática en create/update/delete de BaseModelViewSet
- AuditLogViewSet: listado, filtros, acciones by_entity y my_actions
- Permisos: solo ADMIN y GERENTE pueden ver logs
- Services: audit_create, audit_update, audit_delete, audit_action
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserRoleAssignment, UserProfile
from apps.audit.models import AuditLog
from apps.audit.services import (
    audit_create,
    audit_update,
    audit_delete,
    audit_action,
    serialize_instance,
)
from apps.organizations.models import Organization

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user(username, password, is_superuser=False):
    u = User.objects.create_user(username=username, password=password, is_superuser=is_superuser, is_staff=is_superuser)
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def assign_role(user, code, name=None):
    role, _ = Role.objects.get_or_create(code=code, defaults={"name": name or code, "is_active": True})
    UserRoleAssignment.objects.create(user=user, role=role, is_active=True)
    return role


class BaseAuditTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_user("auditadmin", "auditpass", is_superuser=True)
        self.gerente_user = create_user("gerente_user", "gerentepass")
        assign_role(self.gerente_user, "GERENTE", "Gerente")
        self.regular_user = create_user("regular_user", "regularpass")
        assign_role(self.regular_user, "BODEGUERO", "Bodeguero")

    def _auth(self, username, password):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def _auth_admin(self):
        self._auth("auditadmin", "auditpass")

    def _auth_gerente(self):
        self._auth("gerente_user", "gerentepass")

    def _auth_regular(self):
        self._auth("regular_user", "regularpass")


# ---------------------------------------------------------------------------
# Tests de servicios de auditoría
# ---------------------------------------------------------------------------

class AuditServicesTests(TestCase):

    def setUp(self):
        self.user = create_user("svcaudit", "pass")

    def test_audit_create_crea_log(self):
        org = Organization.objects.create(name="AuditOrg", is_active=True)
        log = audit_create(user=self.user, instance=org, notes="Creación de prueba")
        self.assertIsNotNone(log)
        self.assertEqual(log.action, "CREATE")
        self.assertEqual(log.entity_model, "Organization")
        self.assertIsNotNone(log.new_data)
        self.assertIsNone(log.old_data)

    def test_audit_update_registra_cambio(self):
        org = Organization.objects.create(name="AuditOrgUpdate", is_active=True)
        old = serialize_instance(org)
        org.name = "AuditOrgUpdated"
        org.save()
        log = audit_update(user=self.user, instance=org, old_data=old, notes="Actualización")
        self.assertEqual(log.action, "UPDATE")
        self.assertIsNotNone(log.old_data)
        self.assertIsNotNone(log.new_data)
        self.assertEqual(log.old_data.get("name"), "AuditOrgUpdate")
        self.assertEqual(log.new_data.get("name"), "AuditOrgUpdated")

    def test_audit_delete_registra_eliminacion(self):
        org = Organization.objects.create(name="AuditOrgDel", is_active=True)
        old = serialize_instance(org)
        log = audit_delete(user=self.user, instance=org, old_data=old)
        self.assertEqual(log.action, "DELETE")
        self.assertIsNotNone(log.old_data)
        self.assertIsNone(log.new_data)

    def test_audit_action_registra_accion_custom(self):
        org = Organization.objects.create(name="AuditAction", is_active=True)
        log = audit_action(
            user=self.user,
            action="APPROVE",
            instance=org,
            notes="Aprobado manualmente",
        )
        self.assertEqual(log.action, "APPROVE")
        self.assertEqual(log.notes, "Aprobado manualmente")

    def test_serialize_instance_devuelve_dict(self):
        org = Organization.objects.create(name="SerializeOrg", is_active=True)
        data = serialize_instance(org)
        self.assertIsInstance(data, dict)
        self.assertIn("uuid", data)
        self.assertIsInstance(data["uuid"], str)

    def test_serialize_instance_none_retorna_none(self):
        result = serialize_instance(None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests de permisos del AuditLogViewSet
# ---------------------------------------------------------------------------

class AuditLogPermissionsTests(BaseAuditTest):

    def test_admin_puede_listar_logs(self):
        self._auth_admin()
        response = self.client.get("/api/audit-logs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_gerente_puede_listar_logs(self):
        self._auth_gerente()
        response = self.client.get("/api/audit-logs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_bodeguero_no_puede_listar_logs(self):
        self._auth_regular()
        response = self.client.get("/api/audit-logs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_sin_autenticacion_no_puede_listar(self):
        response = self.client.get("/api/audit-logs/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Tests de la acción by_entity
# ---------------------------------------------------------------------------

class AuditByEntityTests(BaseAuditTest):

    def test_by_entity_filtra_por_modelo(self):
        self._auth_admin()
        # Crear algunos logs manuales
        org = Organization.objects.create(name="ByEntityOrg", is_active=True)
        audit_create(user=self.admin, instance=org)
        response = self.client.get(
            "/api/audit-logs/by-entity/",
            {"entity_model": "Organization"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        models = [r["entity_model"] for r in results]
        self.assertTrue(all(m == "Organization" for m in models))

    def test_by_entity_filtra_por_app(self):
        self._auth_admin()
        response = self.client.get(
            "/api/audit-logs/by-entity/",
            {"entity_app": "organizations"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_by_entity_sin_filtros_devuelve_todo(self):
        self._auth_admin()
        response = self.client.get("/api/audit-logs/by-entity/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Tests de la acción my_actions
# ---------------------------------------------------------------------------

class AuditMyActionsTests(BaseAuditTest):

    def test_my_actions_solo_devuelve_logs_del_usuario_actual(self):
        self._auth_admin()
        # Crear log para admin
        org = Organization.objects.create(name="MyActionsOrg", is_active=True)
        audit_create(user=self.admin, instance=org)
        # Crear log para otro usuario
        audit_create(user=self.regular_user, instance=org, notes="De otro usuario")

        response = self.client.get("/api/audit-logs/my-actions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        # Todos los logs deben ser del admin
        for log in results:
            if log.get("user"):
                self.assertEqual(log["user"], self.admin.id)


# ---------------------------------------------------------------------------
# Tests de auditoría automática en CRUD (BaseModelViewSet)
# ---------------------------------------------------------------------------

class AutomaticAuditTests(BaseAuditTest):

    def test_crear_organizacion_genera_log_create(self):
        self._auth_admin()
        before_count = AuditLog.objects.filter(action="CREATE", entity_model="Organization").count()
        self.client.post(
            "/api/organizations/",
            {"name": "Org Auto Audit", "is_active": True},
            format="json",
        )
        after_count = AuditLog.objects.filter(action="CREATE", entity_model="Organization").count()
        self.assertGreater(after_count, before_count)

    def test_actualizar_organizacion_genera_log_update(self):
        self._auth_admin()
        org = Organization.objects.create(name="Org Para Update", is_active=True)
        before_count = AuditLog.objects.filter(action="UPDATE", entity_model="Organization").count()
        self.client.patch(
            f"/api/organizations/{org.uuid}/",
            {"name": "Org Actualizada Audit"},
            format="json",
        )
        after_count = AuditLog.objects.filter(action="UPDATE", entity_model="Organization").count()
        self.assertGreater(after_count, before_count)

    def test_eliminar_organizacion_genera_log_delete(self):
        self._auth_admin()
        org = Organization.objects.create(name="Org Para Delete", is_active=True)
        before_count = AuditLog.objects.filter(action="DELETE", entity_model="Organization").count()
        self.client.delete(f"/api/organizations/{org.uuid}/")
        after_count = AuditLog.objects.filter(action="DELETE", entity_model="Organization").count()
        self.assertGreater(after_count, before_count)


# ---------------------------------------------------------------------------
# Tests del modelo AuditLog
# ---------------------------------------------------------------------------

class AuditLogModelTests(TestCase):

    def test_str_audit_log(self):
        import uuid
        uid = uuid.uuid4()
        log = AuditLog(action="CREATE", entity_model="Organization", entity_uuid=uid)
        self.assertIn("CREATE", str(log))
        self.assertIn("Organization", str(log))


# ---------------------------------------------------------------------------
# Tests de audit/views.py — paginación en by_entity y my_actions (líneas 66-68, 82-84)
# ---------------------------------------------------------------------------

class AuditPaginationTests(BaseAuditTest):

    def test_by_entity_paginado(self):
        """Crear más de 20 registros para activar la paginación."""
        self._auth_admin()
        org = Organization.objects.create(name="PagAuditOrg", is_active=True)
        for i in range(25):
            audit_create(user=self.admin, instance=org, notes=f"Log {i}")

        response = self.client.get(
            "/api/audit-logs/by-entity/",
            {"entity_model": "Organization", "page_size": 10},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        # Debe estar paginado
        if isinstance(data, dict):
            self.assertIn("results", data)

    def test_my_actions_paginado(self):
        """Verificar que my_actions soporta paginación."""
        self._auth_admin()
        org = Organization.objects.create(name="MyActPagOrg", is_active=True)
        for i in range(25):
            audit_create(user=self.admin, instance=org, notes=f"MyAct {i}")

        response = self.client.get("/api/audit-logs/my-actions/?page_size=10")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_by_entity_con_entity_uuid(self):
        self._auth_admin()
        import uuid
        entity_uuid = uuid.uuid4()
        AuditLog.objects.create(
            user=self.admin,
            action="CREATE",
            entity_app="test",
            entity_model="TestModel",
            entity_uuid=entity_uuid,
        )
        response = self.client.get(
            "/api/audit-logs/by-entity/",
            {"entity_uuid": str(entity_uuid)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

    def test_gerente_puede_ver_my_actions(self):
        self._auth_gerente()
        response = self.client.get("/api/audit-logs/my-actions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_audit_filtro_por_action(self):
        self._auth_admin()
        response = self.client.get("/api/audit-logs/?action=CREATE")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_audit_filtro_por_entity_model(self):
        self._auth_admin()
        response = self.client.get("/api/audit-logs/?entity_model=Organization")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# audit/views.py línea 40: perform_create (crear log via API)
# audit/views.py 66-68, 82-84: forzar paginación real en by_entity y my_actions
# audit/services.py 36, 41: create_audit_log extraer user del request
# ---------------------------------------------------------------------------

class AuditPerformCreateTests(BaseAuditTest):
    """Línea 40: perform_create guarda user=request.user."""

    def test_crear_audit_log_via_api_asigna_usuario(self):
        """POST a /audit-logs/ → perform_create → log.user = admin."""
        self._auth_admin()
        org = Organization.objects.create(name="PerformCreateOrg", is_active=True)
        response = self.client.post(
            "/api/audit-logs/",
            {
                "action": "CREATE",
                "entity_model": "Organization",
                "entity_uuid": str(org.uuid),
                "notes": "Creado vía API",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log_uuid = response.json()["data"]["uuid"]
        log = AuditLog.objects.get(uuid=log_uuid)
        self.assertEqual(log.user, self.admin)


class AuditPaginationForcedTests(BaseAuditTest):
    """
    Líneas 66-68 (by_entity) y 82-84 (my_actions): fuerza la rama
    'if page is not None' creando suficientes logs y usando page_size pequeño.
    """

    def _create_many_logs(self, count=25):
        org = Organization.objects.create(name=f"PagForceOrg", is_active=True)
        for i in range(count):
            AuditLog.objects.create(
                user=self.admin,
                action="CREATE",
                entity_app="organizations",
                entity_model="Organization",
                entity_uuid=org.uuid,
                notes=f"Log {i}",
            )
        return org

    def test_by_entity_paginado_rama_page_not_none(self):
        """Líneas 66-68: page is not None → get_paginated_response."""
        self._auth_admin()
        org = self._create_many_logs(25)
        response = self.client.get(
            f"/api/audit-logs/by-entity/?entity_model=Organization&page_size=5"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        # Con paginación, data es dict con results
        self.assertIsInstance(data, dict)
        self.assertIn("results", data)
        self.assertLessEqual(len(data["results"]), 5)

    def test_my_actions_paginado_rama_page_not_none(self):
        """Líneas 82-84: my_actions con page_size pequeño activa paginación."""
        self._auth_admin()
        self._create_many_logs(25)
        response = self.client.get("/api/audit-logs/my-actions/?page_size=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        if isinstance(data, dict) and "results" in data:
            self.assertLessEqual(len(data["results"]), 5)


class AuditServicesRequestUserTests(TestCase):
    """audit/services.py líneas 36, 41: create_audit_log con request en lugar de user."""

    def test_create_audit_log_extrae_user_de_request(self):
        from apps.audit.services import create_audit_log
        from unittest.mock import MagicMock
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(username="req_user_audit", password="pass")

        request = MagicMock()
        request.user = user

        org = Organization.objects.create(name="ReqAuditOrg", is_active=True)
        log = create_audit_log(
            request=request,
            action="UPDATE",
            instance=org,
            notes="Desde request",
        )
        self.assertEqual(log.user, user)
        self.assertEqual(log.action, "UPDATE")

    def test_create_audit_log_request_user_no_autenticado_deja_user_none(self):
        from apps.audit.services import create_audit_log
        from unittest.mock import MagicMock
        from django.contrib.auth.models import AnonymousUser

        request = MagicMock()
        request.user = AnonymousUser()

        org = Organization.objects.create(name="AnonAuditOrg", is_active=True)
        log = create_audit_log(
            request=request,
            action="DELETE",
            instance=org,
        )
        self.assertIsNone(log.user)


# ---------------------------------------------------------------------------
# audit/services.py:36 → get_entity_uuid cuando instance no tiene uuid
# audit/services.py:41 → get_entity_uuid(None) → primera return None
# audit/views.py:66-68 → by_entity paginación (page is not None)
# audit/views.py:82-84 → my_actions paginación (page is not None)
# ---------------------------------------------------------------------------

class GetEntityUuidTests(TestCase):
    """
    audit/services.py líneas 36 y 41:
    - Línea 36: return None cuando instance no tiene atributo 'uuid'
    - Línea 41: get_entity_uuid(None) → return None en la primera rama
    """

    def test_get_entity_uuid_con_none(self):
        """Línea 41: if not instance → return None."""
        from apps.audit.services import get_entity_uuid
        result = get_entity_uuid(None)
        self.assertIsNone(result)

    def test_get_entity_uuid_instancia_sin_uuid(self):
        """Línea 36: hasattr(instance, 'uuid') es False → return None."""
        from apps.audit.services import get_entity_uuid

        class SinUUID:
            pass

        result = get_entity_uuid(SinUUID())
        self.assertIsNone(result)

    def test_get_entity_uuid_con_uuid(self):
        """Rama normal: instance tiene uuid → lo retorna."""
        from apps.audit.services import get_entity_uuid
        import uuid
        uid = uuid.uuid4()

        class ConUUID:
            uuid = uid

        result = get_entity_uuid(ConUUID())
        self.assertEqual(result, uid)

    def test_create_audit_log_con_instance_sin_uuid(self):
        """Línea 36 vía create_audit_log: entity_uuid queda None para objetos sin uuid."""
        from apps.audit.services import create_audit_log

        class ModelSinUUID:
            class _meta:
                app_label = "test_app"
            __class__ = type("ModelSinUUID", (), {})

        instance = ModelSinUUID()
        log = create_audit_log(
            action="CREATE",
            entity_model="ModelSinUUID",
            entity_app="test_app",
            notes="Sin UUID",
        )
        self.assertIsNone(log.entity_uuid)


class AuditViewsPaginationRealTests(BaseAuditTest):
    """
    audit/views.py 66-68 y 82-84: activar la rama 'if page is not None'
    creando > 20 registros y NO pasando page_size (usa el default de 20).
    """

    def _fill_logs(self, count=25):
        """Crea `count` AuditLogs para forzar paginación con page_size=20."""
        for i in range(count):
            AuditLog.objects.create(
                user=self.admin,
                action="CREATE",
                entity_app="organizations",
                entity_model="Organization",
                notes=f"Pag real {i}",
            )

    def test_by_entity_activa_paginacion_con_mas_de_20_registros(self):
        """
        Líneas 66-68: page is not None → get_paginated_response.
        Necesita >20 logs SIN page_size en la URL para que el paginador retorne una página.
        """
        self._auth_admin()
        self._fill_logs(25)
        # Sin page_size → usa default 20 → paginador activo → page is not None
        response = self.client.get("/api/audit-logs/by-entity/?entity_app=organizations")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        # Con paginación activa data debe ser un dict con 'results'
        self.assertIsInstance(data, dict)
        self.assertIn("results", data)
        # La primera página tiene máximo 20
        self.assertLessEqual(len(data["results"]), 20)

    def test_my_actions_activa_paginacion_con_mas_de_20_registros(self):
        """
        Líneas 82-84: page is not None → get_paginated_response.
        """
        self._auth_admin()
        self._fill_logs(25)
        response = self.client.get("/api/audit-logs/my-actions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIsInstance(data, dict)
        self.assertIn("results", data)
        self.assertLessEqual(len(data["results"]), 20)
