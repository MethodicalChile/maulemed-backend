"""
Tests para la app accounts:
- Autenticación JWT (login, refresh, me)
- Roles CRUD (solo ADMIN)
- UserProfile CRUD
- UserRoleAssignment CRUD
- Permisos y scopes
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import Role, UserProfile, UserRoleAssignment
from apps.organizations.models import Organization, LegalEntity, Branch

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user(username="testuser", password="testpass123", **kwargs):
    return User.objects.create_user(username=username, password=password, **kwargs)


def create_admin_user(username="admin", password="adminpass123"):
    user = User.objects.create_user(username=username, password=password, is_superuser=True, is_staff=True)
    return user


def create_role(code="BODEGUERO", name="Bodeguero"):
    role, _ = Role.objects.get_or_create(code=code, defaults={"name": name})
    return role


def assign_role(user, role, branch=None, organization=None, legal_entity=None):
    return UserRoleAssignment.objects.create(
        user=user,
        role=role,
        branch=branch,
        organization=organization,
        legal_entity=legal_entity,
        is_active=True,
    )


def create_organization(name="Org Test"):
    return Organization.objects.create(name=name, is_active=True)


def create_branch(organization, name="Sucursal Test", code="SCT01"):
    return Branch.objects.create(organization=organization, name=name, code=code, is_active=True)


# ---------------------------------------------------------------------------
# Tests de autenticación JWT
# ---------------------------------------------------------------------------

class AuthLoginTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(username="loginuser", password="secret123")

    def test_login_correcto_devuelve_tokens_y_usuario(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "loginuser", "password": "secret123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "loginuser")

    def test_login_incorrecto_devuelve_401(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "loginuser", "password": "wrongpass"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_usuario_inexistente_devuelve_401(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "noexiste", "password": "whatever"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_sin_datos_devuelve_400(self):
        response = self.client.post("/api/auth/login/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AuthRefreshTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(username="refreshuser", password="secret123")

    def _get_tokens(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "refreshuser", "password": "secret123"},
            format="json",
        )
        return response.json()["data"]

    def test_refresh_token_valido_devuelve_nuevo_access(self):
        tokens = self._get_tokens()
        response = self.client.post(
            "/api/auth/refresh/",
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.json()["data"])

    def test_refresh_token_invalido_devuelve_401(self):
        response = self.client.post(
            "/api/auth/refresh/",
            {"refresh": "token.invalido.aqui"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AuthMeTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(username="meuser", password="secret123")
        self.admin = create_admin_user(username="meadmin", password="adminpass")
        # Crear profile para los usuarios
        UserProfile.objects.get_or_create(user=self.user, defaults={})
        UserProfile.objects.get_or_create(user=self.admin, defaults={})

    def _authenticate(self, username, password):
        response = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        token = response.json()["data"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_me_usuario_autenticado_devuelve_datos(self):
        self._authenticate("meuser", "secret123")
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertIn("user", data)
        self.assertIn("roles", data)
        self.assertIn("permissions", data)
        self.assertIn("menu", data)
        self.assertEqual(data["user"]["username"], "meuser")

    def test_me_sin_autenticacion_devuelve_401(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_admin_tiene_permiso_can_view_audit(self):
        self._authenticate("meadmin", "adminpass")
        response = self.client.get("/api/auth/me/")
        data = response.json()["data"]
        self.assertTrue(data["permissions"]["can_view_audit"])

    def test_me_usuario_sin_roles_no_tiene_can_view_audit(self):
        self._authenticate("meuser", "secret123")
        response = self.client.get("/api/auth/me/")
        data = response.json()["data"]
        self.assertFalse(data["permissions"]["can_view_audit"])


# ---------------------------------------------------------------------------
# Tests de Roles
# ---------------------------------------------------------------------------

class RoleTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_admin_user()
        self.regular = create_user(username="regular", password="pass123")

    def _auth_admin(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "admin", "password": "adminpass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def _auth_regular(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "regular", "password": "pass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_admin_puede_listar_roles(self):
        self._auth_admin()
        response = self.client.get("/api/roles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_puede_crear_rol(self):
        self._auth_admin()
        response = self.client.post(
            "/api/roles/",
            {"code": "CALIDAD", "name": "Calidad", "is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["data"]["code"], "CALIDAD")

    def test_usuario_sin_admin_no_puede_crear_rol(self):
        self._auth_regular()
        response = self.client.post(
            "/api/roles/",
            {"code": "NUEVO", "name": "Nuevo", "is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_sin_autenticacion_no_puede_listar_roles(self):
        response = self.client.get("/api/roles/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_puede_actualizar_rol(self):
        self._auth_admin()
        role = create_role(code="MARKETING", name="Marketing")
        response = self.client.patch(
            f"/api/roles/{role.uuid}/",
            {"name": "Marketing Actualizado"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["name"], "Marketing Actualizado")

    def test_admin_puede_eliminar_rol_logicamente(self):
        self._auth_admin()
        role = create_role(code="RRHH", name="Recursos Humanos")
        response = self.client.delete(f"/api/roles/{role.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verificar que fue soft-deleted (no aparece en listado activo)
        role.refresh_from_db()
        self.assertIsNotNone(role.deleted_at)

    def test_obtener_rol_por_uuid(self):
        self._auth_admin()
        role = create_role(code="FINANZAS", name="Finanzas")
        response = self.client.get(f"/api/roles/{role.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["code"], "FINANZAS")

    def test_uuid_inexistente_devuelve_404(self):
        self._auth_admin()
        import uuid
        response = self.client.get(f"/api/roles/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Tests de UserProfile
# ---------------------------------------------------------------------------

class UserProfileTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_admin_user()
        self.regular = create_user(username="profuser", password="pass123")

    def _auth_admin(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "admin", "password": "adminpass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_admin_puede_listar_perfiles(self):
        self._auth_admin()
        response = self.client.get("/api/user-profiles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_puede_crear_perfil(self):
        self._auth_admin()
        response = self.client.post(
            "/api/user-profiles/",
            {
                "user": self.regular.id,
                "rut": "12345678-9",
                "phone": "+56912345678",
                "position": "Bodeguero",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_perfil_tiene_uuid_en_respuesta(self):
        self._auth_admin()
        profile = UserProfile.objects.create(user=self.regular, is_active=True)
        response = self.client.get(f"/api/user-profiles/{profile.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("uuid", response.json()["data"])


# ---------------------------------------------------------------------------
# Tests de UserRoleAssignment
# ---------------------------------------------------------------------------

class UserRoleAssignmentTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_admin_user()
        self.user = create_user(username="assignuser", password="pass123")
        self.role = create_role(code="ABASTECIMIENTO", name="Abastecimiento")
        self.org = create_organization()
        self.branch = create_branch(self.org)

    def _auth_admin(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "admin", "password": "adminpass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_admin_puede_crear_asignacion_de_rol(self):
        self._auth_admin()
        response = self.client.post(
            "/api/user-role-assignments/",
            {
                "user": self.user.id,
                "role": str(self.role.uuid),
                "branch": str(self.branch.uuid),
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_asignacion_duplicada_falla(self):
        """Unique constraint user+role+org+entity+branch."""
        self._auth_admin()
        UserRoleAssignment.objects.create(
            user=self.user,
            role=self.role,
            branch=self.branch,
            is_active=True,
        )
        response = self.client.post(
            "/api/user-role-assignments/",
            {
                "user": self.user.id,
                "role": str(self.role.uuid),
                "branch": str(self.branch.uuid),
                "is_active": True,
            },
            format="json",
        )
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

    def test_admin_puede_listar_asignaciones(self):
        self._auth_admin()
        response = self.client.get("/api/user-role-assignments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Tests del modelo Role
# ---------------------------------------------------------------------------

class RoleModelTests(TestCase):

    def test_str_rol(self):
        role = Role(code="ADMIN", name="Administrador")
        self.assertEqual(str(role), "Administrador")

    def test_rol_activo_por_defecto(self):
        role = Role.objects.create(code="TENS2", name="TENS2")
        self.assertTrue(role.is_active)


# ---------------------------------------------------------------------------
# Tests del modelo UserRoleAssignment
# ---------------------------------------------------------------------------

class UserRoleAssignmentModelTests(TestCase):

    def test_str_asignacion(self):
        user = create_user(username="modeluser", password="pass")
        role = create_role(code="DOCTOR", name="Doctor")
        assignment = UserRoleAssignment(user=user, role=role)
        self.assertIn("modeluser", str(assignment))
        self.assertIn("Doctor", str(assignment))


# ---------------------------------------------------------------------------
# Tests de formato de respuesta
# ---------------------------------------------------------------------------

class ResponseFormatTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = create_admin_user()

    def _auth_admin(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "admin", "password": "adminpass123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_respuesta_lista_tiene_estructura_estandar(self):
        self._auth_admin()
        response = self.client.get("/api/roles/")
        body = response.json()
        self.assertIn("data", body)
        self.assertIn("status", body)
        self.assertIn("message", body)

    def test_respuesta_paginada_tiene_metadatos(self):
        """Con paginación, data incluye count/total_pages/results."""
        self._auth_admin()
        response = self.client.get("/api/roles/")
        data = response.json()["data"]
        # Si hay paginación activa
        if isinstance(data, dict):
            self.assertIn("results", data)


# ---------------------------------------------------------------------------
# Tests de accounts/views.py — endpoint /me/ con roles asignados (líneas 104-131)
# ---------------------------------------------------------------------------

class MeWithRolesTests(TestCase):
    """Cubrir el bloque de construcción de permisos y menú en la vista me()."""

    def setUp(self):
        self.client = APIClient()
        org = create_organization("MeOrg")
        branch = create_branch(org, name="MeBranch", code="MEB01")
        le = LegalEntity.objects.create(organization=org, name="MeLE", rut="76789001-1", is_active=True)

        # Usuario ABASTECIMIENTO con todos los permisos de compras/inventario
        self.user_ab = create_user(username="me_ab", password="pass")
        UserProfile.objects.get_or_create(user=self.user_ab, defaults={})
        role_ab, _ = Role.objects.get_or_create(code="ABASTECIMIENTO", defaults={"name": "Abastecimiento", "is_active": True})
        assign_role(self.user_ab, role_ab, branch=branch)

        # Usuario FINANZAS
        self.user_fin = create_user(username="me_fin", password="pass")
        UserProfile.objects.get_or_create(user=self.user_fin, defaults={})
        role_fin, _ = Role.objects.get_or_create(code="FINANZAS", defaults={"name": "Finanzas", "is_active": True})
        assign_role(self.user_fin, role_fin, branch=branch)

        # Usuario BODEGUERO
        self.user_bode = create_user(username="me_bode", password="pass")
        UserProfile.objects.get_or_create(user=self.user_bode, defaults={})
        role_bode, _ = Role.objects.get_or_create(code="BODEGUERO", defaults={"name": "Bodeguero", "is_active": True})
        assign_role(self.user_bode, role_bode, branch=branch)

    def _auth(self, username, password):
        resp = self.client.post("/api/auth/login/", {"username": username, "password": password}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_abastecimiento_tiene_permiso_compras(self):
        self._auth("me_ab", "pass")
        resp = self.client.get("/api/auth/me/")
        perms = resp.json()["data"]["permissions"]
        self.assertTrue(perms["can_manage_catalogs"])
        self.assertTrue(perms["can_approve_supply_request"])
        self.assertTrue(perms["can_manage_purchase_orders"])
        self.assertTrue(perms["can_manage_inventory"])
        self.assertFalse(perms["can_manage_finance"])

    def test_finanzas_tiene_permiso_finanzas(self):
        self._auth("me_fin", "pass")
        resp = self.client.get("/api/auth/me/")
        perms = resp.json()["data"]["permissions"]
        self.assertTrue(perms["can_manage_finance"])
        self.assertTrue(perms["can_view_reports"])
        self.assertFalse(perms["can_view_audit"])

    def test_bodeguero_puede_ver_inventario_no_finanzas(self):
        self._auth("me_bode", "pass")
        resp = self.client.get("/api/auth/me/")
        perms = resp.json()["data"]["permissions"]
        self.assertTrue(perms["can_view_inventory"])
        self.assertFalse(perms["can_manage_finance"])
        self.assertFalse(perms["can_view_audit"])

    def test_me_devuelve_scopes_con_branches(self):
        self._auth("me_ab", "pass")
        resp = self.client.get("/api/auth/me/")
        data = resp.json()["data"]
        self.assertIn("scopes", data)
        self.assertIn("branches", data["scopes"])
        # Debe tener al menos 1 branch en su scope
        self.assertGreater(len(data["scopes"]["branches"]), 0)

    def test_me_menu_visible_segun_permisos(self):
        self._auth("me_fin", "pass")
        resp = self.client.get("/api/auth/me/")
        menu = resp.json()["data"]["menu"]
        keys = [item["key"] for item in menu]
        self.assertIn("finance", keys)
        # Auditoría NO debe aparecer para FINANZAS
        self.assertNotIn("audit", keys)


# ---------------------------------------------------------------------------
# Línea 33: UserProfile.__str__ cuando full_name está vacío → retorna username
# Línea 70: UserRoleAssignmentSerializer.validate → qs.exclude(pk=self.instance.pk) en UPDATE
# Líneas 114, 122: me() con scope de organization y legal_entity en el loop
# ---------------------------------------------------------------------------

class UserProfileStrTests(TestCase):
    """Línea 33: __str__ retorna username cuando no hay full name."""

    def test_str_retorna_username_si_no_hay_nombre(self):
        user = User.objects.create_user(username="nofullname", password="pass")
        profile = UserProfile.objects.create(user=user)
        self.assertEqual(str(profile), "nofullname")

    def test_str_retorna_full_name_cuando_existe(self):
        user = User.objects.create_user(
            username="withname", password="pass",
            first_name="Ana", last_name="García"
        )
        profile = UserProfile.objects.create(user=user)
        self.assertEqual(str(profile), "Ana García")


class UserRoleAssignmentSerializerUpdateTests(TestCase):
    """Línea 70: qs.exclude(pk=self.instance.pk) — validación en actualización."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="ser_upd_admin", password="pass", is_superuser=True, is_staff=True
        )
        self.user = User.objects.create_user(username="ser_upd_user", password="pass")
        self.role = Role.objects.create(code="CALIDAD", name="Calidad", is_active=True)
        org = create_organization("SerUpdOrg")
        self.branch = create_branch(org, name="SerUpdBranch", code="SU001")

    def _auth_admin(self):
        resp = self.client.post("/api/auth/login/", {"username": "ser_upd_admin", "password": "pass"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_update_asignacion_propia_no_falla(self):
        """Al actualizar la propia asignación, exclude(pk=instance.pk) evita falso positivo."""
        assignment = UserRoleAssignment.objects.create(
            user=self.user, role=self.role, branch=self.branch, is_active=True
        )
        self._auth_admin()
        resp = self.client.patch(
            f"/api/user-role-assignments/{assignment.uuid}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.json()["data"]["is_active"])


class MeWithOrganizationAndLegalEntityScopeTests(TestCase):
    """Líneas 114 y 122: me() cuando el usuario tiene scope de organization y legal_entity."""

    def setUp(self):
        self.client = APIClient()
        org = create_organization("MeOrgScope")
        le = LegalEntity.objects.create(organization=org, name="MeLEScope", rut="76999777-7", is_active=True)
        branch = Branch.objects.create(
            organization=org, legal_entity=le, name="MeBranchScope", code="MBS01", is_active=True
        )

        # Usuario con scope en organization
        self.user_org_scope = create_user(username="me_org_scope", password="pass")
        UserProfile.objects.get_or_create(user=self.user_org_scope, defaults={})
        role, _ = Role.objects.get_or_create(code="GERENTE", defaults={"name": "Gerente", "is_active": True})
        assign_role(self.user_org_scope, role, organization=org)

        # Usuario con scope en legal_entity
        self.user_le_scope = create_user(username="me_le_scope", password="pass")
        UserProfile.objects.get_or_create(user=self.user_le_scope, defaults={})
        role_ab, _ = Role.objects.get_or_create(code="ABASTECIMIENTO", defaults={"name": "Abastecimiento", "is_active": True})
        assign_role(self.user_le_scope, role_ab, legal_entity=le)

    def _auth(self, username, password="pass"):
        resp = self.client.post("/api/auth/login/", {"username": username, "password": password}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.json()["data"]["access"]}')

    def test_me_con_scope_organization_incluye_organizations(self):
        """Línea 114: if getattr(assignment, 'organization', None) → organizations.append."""
        self._auth("me_org_scope")
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(len(data["scopes"]["organizations"]), 0)
        # Primer org debe tener uuid y name
        org_entry = data["scopes"]["organizations"][0]
        self.assertIn("uuid", org_entry)
        self.assertIn("name", org_entry)

    def test_me_con_scope_legal_entity_incluye_legal_entities(self):
        """Línea 122: if getattr(assignment, 'legal_entity', None) → legal_entities.append."""
        self._auth("me_le_scope")
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()["data"]
        self.assertGreater(len(data["scopes"]["legal_entities"]), 0)
        le_entry = data["scopes"]["legal_entities"][0]
        self.assertIn("uuid", le_entry)
        self.assertIn("rut", le_entry)
