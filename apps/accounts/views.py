import logging
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ViewSet
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import IsAdminRole
from apps.common.responses import api_response, api_error

from rest_framework_simplejwt.tokens import RefreshToken

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .models import UserProfile, Role, UserRoleAssignment, RolePermission

from .serializers import (
    UserSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    UserPasswordSerializer,
    UserProfileSerializer,
    RoleSerializer,
    UserRoleAssignmentSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Auth — Login / Refresh
# ──────────────────────────────────────────────────────────────────────────────

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        logger.info(f"Login exitoso usuario={self.user.username}")
        data["user"] = {
            "id": self.user.id,
            "username": self.user.username,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "is_staff": self.user.is_staff,
            "is_superuser": self.user.is_superuser,
        }
        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    # Limita los intentos de login a 10/minuto por IP (ver settings.DEFAULT_THROTTLE_RATES)
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        return api_response(
            data=response.data,
            status_code=response.status_code,
            message="Login realizado correctamente.",
        )


class CustomTokenRefreshView(TokenRefreshView):
    throttle_scope = "token_refresh"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        return api_response(
            data=response.data,
            status_code=response.status_code,
            message="Token renovado correctamente.",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Gestión de usuarios (admin)
# ──────────────────────────────────────────────────────────────────────────────

class UserManagementViewSet(ViewSet):
    permission_classes = [IsAdminRole]

    def _user_detail(self, user):
        profile = getattr(user, "profile", None)
        assignments = user.role_assignments.filter(is_active=True).select_related(
            "role", "organization", "legal_entity", "branch"
        )
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.get_full_name(),
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "profile": UserProfileSerializer(profile).data if profile else None,
            "role_assignments": UserRoleAssignmentSerializer(assignments, many=True).data,
        }

    def list(self, request):
        qs = User.objects.prefetch_related(
            "profile", "role_assignments__role",
            "role_assignments__organization", "role_assignments__branch",
        ).order_by("first_name", "last_name", "username")

        # Búsqueda por nombre, apellido, username o email
        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(username__icontains=search) |
                Q(email__icontains=search)
            )

        # Filtro por estado activo
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")

        # Paginación manual compatible con StandardResultsSetPagination
        total = qs.count()
        try:
            page      = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except (ValueError, TypeError):
            page, page_size = 1, 20

        offset = (page - 1) * page_size
        users  = qs[offset: offset + page_size]

        return api_response(
            data={
                "count":       total,
                "page":        page,
                "page_size":   page_size,
                "total_pages": (total + page_size - 1) // page_size,
                "results":     [self._user_detail(u) for u in users],
            },
            message="Usuarios obtenidos correctamente.",
        )

    def retrieve(self, request, pk=None):
        try:
            user = User.objects.prefetch_related(
                "profile", "role_assignments__role",
                "role_assignments__organization", "role_assignments__branch",
            ).get(pk=pk)
        except User.DoesNotExist:
            return api_error(message="Usuario no encontrado.", status_code=404)
        return api_response(data=self._user_detail(user))

    def create(self, request):
        serializer = UserCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_error(data=serializer.errors, message="Datos inválidos.")
        user = serializer.save()
        logger.info(f"Usuario creado: {user.username} por admin={request.user.username}")
        return api_response(data=self._user_detail(user),
                            status_code=status.HTTP_201_CREATED,
                            message="Usuario creado correctamente.")

    def partial_update(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return api_error(message="Usuario no encontrado.", status_code=404)
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        if not serializer.is_valid():
            return api_error(data=serializer.errors, message="Datos inválidos.")
        serializer.save()
        return api_response(data=self._user_detail(user), message="Usuario actualizado correctamente.")

    def destroy(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return api_error(message="Usuario no encontrado.", status_code=404)
        if user == request.user:
            return api_error(message="No puedes desactivarte a ti mismo.", status_code=400)
        user.is_active = False
        user.save(update_fields=["is_active"])
        logger.info(f"Usuario desactivado: {user.username} por admin={request.user.username}")
        return api_response(message="Usuario desactivado correctamente.")

    @action(detail=True, methods=["post"], url_path="set_password")
    def set_password(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return api_error(message="Usuario no encontrado.", status_code=404)
        serializer = UserPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return api_error(data=serializer.errors, message="Datos inválidos.")
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        logger.info(f"Contraseña cambiada para: {user.username} por admin={request.user.username}")
        return api_response(message="Contraseña actualizada correctamente.")

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return api_error(message="Usuario no encontrado.", status_code=404)
        user.is_active = True
        user.save(update_fields=["is_active"])
        return api_response(data=self._user_detail(user), message="Usuario activado correctamente.")


# ──────────────────────────────────────────────────────────────────────────────
# ViewSets de catálogos de cuentas
# ──────────────────────────────────────────────────────────────────────────────

class RoleViewSet(BaseModelViewSet):
    queryset = Role.objects.all().order_by("name")
    serializer_class = RoleSerializer
    permission_classes = [IsAdminRole]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["name", "code", "is_active"]

    def create(self, request, *args, **kwargs):
        """
        Si existe un rol soft-deleted con el mismo código, lo restaura
        en vez de crear uno nuevo (evita IntegrityError por UNIQUE constraint).
        """
        from apps.common.responses import api_response as _ok
        from apps.audit.services import audit_action

        code = request.data.get("code", "").strip().upper().replace(" ", "_")

        deleted_role = Role.all_objects.filter(
            code=code,
            deleted_at__isnull=False,
        ).first()

        if deleted_role:
            # Restaurar el registro eliminado con los nuevos datos
            deleted_role.deleted_at   = None
            deleted_role.name         = request.data.get("name", deleted_role.name)
            deleted_role.description  = request.data.get("description", deleted_role.description)
            deleted_role.is_active    = request.data.get("is_active", True)
            deleted_role.save(update_fields=["deleted_at", "name", "description", "is_active", "updated_at"])

            audit_action(
                request=request,
                action="RESTORE",
                instance=deleted_role,
                notes=f"Rol restaurado desde soft-delete por {request.user.username}.",
            )

            return _ok(
                data=RoleSerializer(deleted_role).data,
                status_code=201,
                message="Rol restaurado correctamente (existía como eliminado).",
            )

        # Flujo normal de creación
        return super().create(request, *args, **kwargs)


class UserProfileViewSet(BaseModelViewSet):
    queryset = UserProfile.objects.select_related("user", "organization").order_by("id")
    serializer_class = UserProfileSerializer
    permission_classes = [IsAdminRole]


class UserRoleAssignmentViewSet(BaseModelViewSet):
    queryset = UserRoleAssignment.objects.select_related(
        "user", "role", "organization", "legal_entity", "branch",
    ).order_by("id")
    serializer_class = UserRoleAssignmentSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["user", "role", "organization", "branch", "is_active"]


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints del usuario autenticado (propios)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_my_password(request):
    """Permite al usuario autenticado cambiar su propia contraseña."""
    serializer = UserPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return api_error(data=serializer.errors, message="Datos inválidos.")
    request.user.set_password(serializer.validated_data["password"])
    request.user.save(update_fields=["password"])
    logger.info(f"Contraseña cambiada por el propio usuario={request.user.username}")
    return api_response(message="Contraseña actualizada correctamente.")


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_my_profile(request):
    """Permite al usuario autenticado actualizar su propio perfil y nombre."""
    user = request.user

    # Actualizar first_name / last_name del User si vienen en el payload
    user_fields = {}
    if "first_name" in request.data:
        user_fields["first_name"] = request.data["first_name"] or ""
    if "last_name" in request.data:
        user_fields["last_name"] = request.data["last_name"] or ""
    if user_fields:
        for field, value in user_fields.items():
            setattr(user, field, value)
        user.save(update_fields=list(user_fields.keys()))

    # Actualizar campos del perfil
    profile = getattr(user, "profile", None)
    allowed_fields = {"phone", "position", "rut"}
    allowed = {k: v for k, v in request.data.items() if k in allowed_fields}
    if profile:
        for field, value in allowed.items():
            setattr(profile, field, value)
        profile.save(update_fields=list(allowed.keys()))
        return api_response(data=UserProfileSerializer(profile).data,
                            message="Perfil actualizado correctamente.")
    return api_error(message="El usuario no tiene perfil.", status_code=404)


# ──────────────────────────────────────────────────────────────────────────────
# Matriz de permisos por rol (referencia visual)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAdminRole])
def role_permissions_matrix(request):
    """
    Matriz granular: un permiso por acción (ver / crear / editar / eliminar).
    """
    db_roles = list(
        Role.objects.filter(is_active=True)
        .values("uuid", "code", "name")
        .order_by("name")
    )
    role_codes = [r["code"] for r in db_roles]

    saved_perms = {}
    for rp in RolePermission.objects.filter(role__code__in=role_codes).select_related("role"):
        saved_perms.setdefault(rp.role.code, set()).add(rp.permission_key)

    # ── Defaults granulares del sistema ───────────────────────────────────────
    ADMIN_GERENTE   = {"ADMIN", "GERENTE"}
    ADMIN_GER_ABAST = {"ADMIN", "GERENTE", "ABASTECIMIENTO"}
    CATALOG_READERS = {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"}
    SUP_READERS     = {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS"}
    INV_READERS     = {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"}
    INV_WRITERS     = {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"}
    TRANSFER_ROLES  = {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"}
    PURCHASE_REQERS = {"ADMIN","GERENTE","ABASTECIMIENTO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"}

    SYSTEM_DEFAULTS = {
        # Dashboard
        "can_view_dashboard":             set(role_codes),
        # Organización
        "can_view_organizations":         ADMIN_GERENTE,
        "can_create_organizations":       ADMIN_GERENTE,
        "can_edit_organizations":         ADMIN_GERENTE,
        "can_delete_organizations":       {"ADMIN"},
        # Productos
        "can_view_products":              CATALOG_READERS,
        "can_create_products":            ADMIN_GER_ABAST,
        "can_edit_products":              ADMIN_GER_ABAST,
        "can_delete_products":            ADMIN_GER_ABAST,
        # Proveedores
        "can_view_suppliers":             SUP_READERS,
        "can_create_suppliers":           ADMIN_GER_ABAST,
        "can_edit_suppliers":             ADMIN_GER_ABAST,
        "can_delete_suppliers":           ADMIN_GER_ABAST,
        # Inventario
        "can_view_inventory":             INV_READERS,
        "can_create_inventory":           INV_WRITERS,
        "can_edit_inventory":             INV_WRITERS,
        "can_delete_inventory":           ADMIN_GER_ABAST,
        # Compras — Solicitudes
        "can_view_supply_requests":       CATALOG_READERS,
        "can_create_supply_request":      PURCHASE_REQERS,
        "can_edit_supply_request":        ADMIN_GER_ABAST,
        "can_approve_supply_request":     ADMIN_GER_ABAST,
        # Compras — Órdenes
        "can_view_purchase_orders":       SUP_READERS,
        "can_create_purchase_orders":     ADMIN_GER_ABAST,
        "can_edit_purchase_orders":       ADMIN_GER_ABAST,
        "can_delete_purchase_orders":     ADMIN_GERENTE,
        "can_receive_purchase":           INV_WRITERS,
        # Traspasos
        "can_view_transfers":             TRANSFER_ROLES,
        "can_create_transfers":           TRANSFER_ROLES,
        "can_edit_transfers":             TRANSFER_ROLES,
        "can_delete_transfers":           ADMIN_GER_ABAST,
        # Finanzas
        "can_view_finance":               {"ADMIN","GERENTE","FINANZAS"},
        "can_create_finance":             {"ADMIN","GERENTE","FINANZAS"},
        "can_edit_finance":               {"ADMIN","GERENTE","FINANZAS"},
        "can_delete_finance":             ADMIN_GERENTE,
        # Evaluaciones
        "can_view_evaluations":           set(role_codes),
        "can_create_evaluations":         ADMIN_GERENTE,
        "can_edit_evaluations":           ADMIN_GERENTE,
        "can_delete_evaluations":         {"ADMIN"},
        # Reportes
        "can_view_reports":               {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL"},
        # Usuarios
        "can_view_users":                 {"ADMIN"},
        "can_create_users":               {"ADMIN"},
        "can_edit_users":                 {"ADMIN"},
        "can_delete_users":               {"ADMIN"},
        # Roles
        "can_view_roles":                 {"ADMIN"},
        "can_create_roles":               {"ADMIN"},
        "can_edit_roles":                 {"ADMIN"},
        "can_delete_roles":               {"ADMIN"},
        # Auditoría
        "can_view_audit":                 ADMIN_GERENTE,
    }

    def has_perm(role_code, perm_key):
        if role_code in saved_perms:
            return perm_key in saved_perms[role_code]
        return role_code in SYSTEM_DEFAULTS.get(perm_key, set())

    MODULE_STRUCTURE = [
        {"module": "Dashboard", "key": "dashboard", "permissions": [
            {"action": "Ver dashboard",          "key": "can_view_dashboard"},
        ]},
        {"module": "Organización", "key": "organizations", "permissions": [
            {"action": "Ver",     "key": "can_view_organizations"},
            {"action": "Crear",   "key": "can_create_organizations"},
            {"action": "Editar",  "key": "can_edit_organizations"},
            {"action": "Eliminar","key": "can_delete_organizations"},
        ]},
        {"module": "Productos", "key": "products", "permissions": [
            {"action": "Ver",     "key": "can_view_products"},
            {"action": "Crear",   "key": "can_create_products"},
            {"action": "Editar",  "key": "can_edit_products"},
            {"action": "Eliminar","key": "can_delete_products"},
        ]},
        {"module": "Proveedores", "key": "suppliers", "permissions": [
            {"action": "Ver",     "key": "can_view_suppliers"},
            {"action": "Crear",   "key": "can_create_suppliers"},
            {"action": "Editar",  "key": "can_edit_suppliers"},
            {"action": "Eliminar","key": "can_delete_suppliers"},
        ]},
        {"module": "Inventario", "key": "inventory", "permissions": [
            {"action": "Ver",                  "key": "can_view_inventory"},
            {"action": "Registrar movimientos","key": "can_create_inventory"},
            {"action": "Editar movimientos",   "key": "can_edit_inventory"},
            {"action": "Eliminar movimientos", "key": "can_delete_inventory"},
        ]},
        {"module": "Compras — Solicitudes", "key": "supply_requests", "permissions": [
            {"action": "Ver solicitudes",    "key": "can_view_supply_requests"},
            {"action": "Crear solicitud",    "key": "can_create_supply_request"},
            {"action": "Editar solicitud",   "key": "can_edit_supply_request"},
            {"action": "Aprobar solicitud",  "key": "can_approve_supply_request"},
        ]},
        {"module": "Compras — Órdenes", "key": "purchase_orders", "permissions": [
            {"action": "Ver órdenes",         "key": "can_view_purchase_orders"},
            {"action": "Crear orden",         "key": "can_create_purchase_orders"},
            {"action": "Editar orden",        "key": "can_edit_purchase_orders"},
            {"action": "Eliminar orden",      "key": "can_delete_purchase_orders"},
            {"action": "Recibir compra",      "key": "can_receive_purchase"},
        ]},
        {"module": "Traspasos", "key": "transfers", "permissions": [
            {"action": "Ver",     "key": "can_view_transfers"},
            {"action": "Crear",   "key": "can_create_transfers"},
            {"action": "Editar",  "key": "can_edit_transfers"},
            {"action": "Eliminar","key": "can_delete_transfers"},
        ]},
        {"module": "Finanzas", "key": "finance", "permissions": [
            {"action": "Ver",     "key": "can_view_finance"},
            {"action": "Crear",   "key": "can_create_finance"},
            {"action": "Editar",  "key": "can_edit_finance"},
            {"action": "Eliminar","key": "can_delete_finance"},
        ]},
        {"module": "Evaluaciones", "key": "evaluations", "permissions": [
            {"action": "Ver",     "key": "can_view_evaluations"},
            {"action": "Crear",   "key": "can_create_evaluations"},
            {"action": "Editar",  "key": "can_edit_evaluations"},
            {"action": "Eliminar","key": "can_delete_evaluations"},
        ]},
        {"module": "Reportes", "key": "reports", "permissions": [
            {"action": "Ver reportes", "key": "can_view_reports"},
        ]},
        {"module": "Usuarios", "key": "users", "permissions": [
            {"action": "Ver",     "key": "can_view_users"},
            {"action": "Crear",   "key": "can_create_users"},
            {"action": "Editar",  "key": "can_edit_users"},
            {"action": "Eliminar","key": "can_delete_users"},
        ]},
        {"module": "Roles", "key": "roles", "permissions": [
            {"action": "Ver",     "key": "can_view_roles"},
            {"action": "Crear",   "key": "can_create_roles"},
            {"action": "Editar",  "key": "can_edit_roles"},
            {"action": "Eliminar","key": "can_delete_roles"},
        ]},
        {"module": "Auditoría", "key": "audit", "permissions": [
            {"action": "Ver logs", "key": "can_view_audit"},
        ]},
    ]

    matrix = []
    for mod in MODULE_STRUCTURE:
        perms = []
        for p in mod["permissions"]:
            roles_with = [c for c in role_codes if has_perm(c, p["key"])]
            perms.append({**p, "roles": roles_with})
        matrix.append({**mod, "permissions": perms})

    return api_response(
        data={"roles": db_roles, "matrix": matrix},
        message="Matriz de permisos obtenida correctamente.",
    )


@api_view(["POST"])
@permission_classes([IsAdminRole])
def update_role_permission(request):
    """
    Activa o desactiva un permiso para un rol.
    Body: { "role_uuid": "...", "permission_key": "...", "granted": true/false }
    """
    role_uuid      = request.data.get("role_uuid")
    permission_key = request.data.get("permission_key")
    granted        = request.data.get("granted", True)

    try:
        role = Role.objects.get(uuid=role_uuid)
    except Role.DoesNotExist:
        return api_error(message="Rol no encontrado.", status_code=404)

    if not permission_key:
        return api_error(message="permission_key es requerido.", status_code=400)

    if granted:
        RolePermission.objects.get_or_create(role=role, permission_key=permission_key)
    else:
        RolePermission.objects.filter(role=role, permission_key=permission_key).delete()

    logger.info(f"Permiso {permission_key} {'otorgado' if granted else 'revocado'} al rol {role.code}")
    return api_response(message="Permiso actualizado correctamente.")


# ──────────────────────────────────────────────────────────────────────────────
# /auth/me/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    assignments = user.role_assignments.filter(is_active=True).select_related(
        "role", "organization", "legal_entity", "branch"
    )

    roles, organizations, legal_entities, branches = [], [], [], []

    for a in assignments:
        if a.role:
            roles.append({"uuid": str(a.role.uuid), "code": a.role.code, "name": a.role.name})
        if getattr(a, "organization", None):
            organizations.append({"uuid": str(a.organization.uuid), "name": a.organization.name})
        if getattr(a, "legal_entity", None):
            legal_entities.append({"uuid": str(a.legal_entity.uuid), "name": a.legal_entity.name, "rut": a.legal_entity.rut})
        if getattr(a, "branch", None):
            branches.append({"uuid": str(a.branch.uuid), "name": a.branch.name, "code": a.branch.code})

    role_codes = list({r["code"] for r in roles})
    is_admin   = user.is_superuser or "ADMIN" in role_codes
    is_gerente = "GERENTE" in role_codes

    # ── Leer permisos desde RolePermission (editables por el admin) ────────
    # Para cada rol del usuario obtenemos sus permisos guardados en BD.
    # Si el rol no tiene entradas en RolePermission → usamos defaults del sistema.
    saved_perms_by_role = {}  # { role_code: set(permission_key) }
    for rp in RolePermission.objects.filter(
        role__code__in=role_codes
    ).select_related("role"):
        saved_perms_by_role.setdefault(rp.role.code, set()).add(rp.permission_key)

    # Defaults granulares para roles sin configuración en BD
    ADMIN_GERENTE   = {"ADMIN", "GERENTE"}
    ADMIN_GER_ABAST = {"ADMIN", "GERENTE", "ABASTECIMIENTO"}
    CATALOG_READERS = {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"}
    SUP_READERS     = {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS"}
    INV_READERS     = {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"}
    INV_WRITERS     = {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"}
    TRANSFER_ROLES  = {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"}
    PURCHASE_REQERS = {"ADMIN","GERENTE","ABASTECIMIENTO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"}
    FINANCE_ROLES   = {"ADMIN","GERENTE","FINANZAS"}

    DEFAULTS = {
        "can_view_dashboard":         set(role_codes),
        # Organización
        "can_view_organizations":     ADMIN_GERENTE,
        "can_create_organizations":   ADMIN_GERENTE,
        "can_edit_organizations":     ADMIN_GERENTE,
        "can_delete_organizations":   {"ADMIN"},
        # Productos
        "can_view_products":          CATALOG_READERS,
        "can_create_products":        ADMIN_GER_ABAST,
        "can_edit_products":          ADMIN_GER_ABAST,
        "can_delete_products":        ADMIN_GER_ABAST,
        # Proveedores
        "can_view_suppliers":         SUP_READERS,
        "can_create_suppliers":       ADMIN_GER_ABAST,
        "can_edit_suppliers":         ADMIN_GER_ABAST,
        "can_delete_suppliers":       ADMIN_GER_ABAST,
        # Inventario
        "can_view_inventory":         INV_READERS,
        "can_create_inventory":       INV_WRITERS,
        "can_edit_inventory":         INV_WRITERS,
        "can_delete_inventory":       ADMIN_GER_ABAST,
        # Compras — solicitudes
        "can_view_supply_requests":   CATALOG_READERS,
        "can_create_supply_request":  PURCHASE_REQERS,
        "can_edit_supply_request":    ADMIN_GER_ABAST,
        "can_approve_supply_request": ADMIN_GER_ABAST,
        # Compras — órdenes
        "can_view_purchase_orders":   SUP_READERS,
        "can_create_purchase_orders": ADMIN_GER_ABAST,
        "can_edit_purchase_orders":   ADMIN_GER_ABAST,
        "can_delete_purchase_orders": ADMIN_GERENTE,
        "can_receive_purchase":       INV_WRITERS,
        # Traspasos
        "can_view_transfers":         TRANSFER_ROLES,
        "can_create_transfers":       TRANSFER_ROLES,
        "can_edit_transfers":         TRANSFER_ROLES,
        "can_delete_transfers":       ADMIN_GER_ABAST,
        # Finanzas
        "can_view_finance":           FINANCE_ROLES,
        "can_create_finance":         FINANCE_ROLES,
        "can_edit_finance":           FINANCE_ROLES,
        "can_delete_finance":         ADMIN_GERENTE,
        # Evaluaciones
        "can_view_evaluations":       set(role_codes),
        "can_create_evaluations":     ADMIN_GERENTE,
        "can_edit_evaluations":       ADMIN_GERENTE,
        "can_delete_evaluations":     {"ADMIN"},
        # Reportes
        "can_view_reports":           {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL"},
        # Usuarios
        "can_view_users":             {"ADMIN"},
        "can_create_users":           {"ADMIN"},
        "can_edit_users":             {"ADMIN"},
        "can_delete_users":           {"ADMIN"},
        # Roles
        "can_view_roles":             {"ADMIN"},
        "can_create_roles":           {"ADMIN"},
        "can_edit_roles":             {"ADMIN"},
        "can_delete_roles":           {"ADMIN"},
        # Auditoría
        "can_view_audit":             ADMIN_GERENTE,
    }

    def user_has_perm(perm_key):
        if user.is_superuser:
            return True
        for code in role_codes:
            if code in saved_perms_by_role:
                if perm_key in saved_perms_by_role[code]:
                    return True
            else:
                if code in DEFAULTS.get(perm_key, set()):
                    return True
        return False

    permissions = {
        "can_view_dashboard":         True,
        # Productos
        "can_view_products":          user_has_perm("can_view_products"),
        "can_create_products":        user_has_perm("can_create_products"),
        "can_edit_products":          user_has_perm("can_edit_products"),
        "can_delete_products":        user_has_perm("can_delete_products"),
        # Proveedores
        "can_view_suppliers":         user_has_perm("can_view_suppliers"),
        "can_create_suppliers":       user_has_perm("can_create_suppliers"),
        "can_edit_suppliers":         user_has_perm("can_edit_suppliers"),
        "can_delete_suppliers":       user_has_perm("can_delete_suppliers"),
        # Inventario
        "can_view_inventory":         user_has_perm("can_view_inventory"),
        "can_create_inventory":       user_has_perm("can_create_inventory"),
        "can_edit_inventory":         user_has_perm("can_edit_inventory"),
        "can_delete_inventory":       user_has_perm("can_delete_inventory"),
        # Compras
        "can_view_supply_requests":   user_has_perm("can_view_supply_requests"),
        "can_create_supply_request":  user_has_perm("can_create_supply_request"),
        "can_edit_supply_request":    user_has_perm("can_edit_supply_request"),
        "can_approve_supply_request": user_has_perm("can_approve_supply_request"),
        "can_view_purchase_orders":   user_has_perm("can_view_purchase_orders"),
        "can_create_purchase_orders": user_has_perm("can_create_purchase_orders"),
        "can_edit_purchase_orders":   user_has_perm("can_edit_purchase_orders"),
        "can_delete_purchase_orders": user_has_perm("can_delete_purchase_orders"),
        "can_receive_purchase":       user_has_perm("can_receive_purchase"),
        # Traspasos
        "can_view_transfers":         user_has_perm("can_view_transfers"),
        "can_create_transfers":       user_has_perm("can_create_transfers"),
        "can_edit_transfers":         user_has_perm("can_edit_transfers"),
        "can_delete_transfers":       user_has_perm("can_delete_transfers"),
        # Finanzas
        "can_view_finance":           user_has_perm("can_view_finance"),
        "can_create_finance":         user_has_perm("can_create_finance"),
        "can_edit_finance":           user_has_perm("can_edit_finance"),
        "can_delete_finance":         user_has_perm("can_delete_finance"),
        # Evaluaciones
        "can_view_evaluations":       user_has_perm("can_view_evaluations"),
        "can_create_evaluations":     user_has_perm("can_create_evaluations"),
        "can_edit_evaluations":       user_has_perm("can_edit_evaluations"),
        "can_delete_evaluations":     user_has_perm("can_delete_evaluations"),
        # Reportes
        "can_view_reports":           user_has_perm("can_view_reports"),
        # Organización
        "can_view_organizations":     user_has_perm("can_view_organizations"),
        "can_create_organizations":   user_has_perm("can_create_organizations"),
        "can_edit_organizations":     user_has_perm("can_edit_organizations"),
        "can_delete_organizations":   user_has_perm("can_delete_organizations"),
        # Usuarios / Roles
        "can_view_users":             is_admin,
        "can_create_users":           is_admin,
        "can_edit_users":             is_admin,
        "can_delete_users":           is_admin,
        "can_view_roles":             is_admin,
        "can_create_roles":           is_admin,
        "can_edit_roles":             is_admin,
        "can_delete_roles":           is_admin,
        # Auditoría
        "can_view_audit":             user_has_perm("can_view_audit"),
        # Legacy — mantenidos para compatibilidad con el router existente
        "can_manage_catalogs":        user_has_perm("can_edit_products"),
        "can_view_catalogs":          user_has_perm("can_view_products"),
        "can_manage_suppliers":       user_has_perm("can_edit_suppliers"),
        "can_manage_inventory":       user_has_perm("can_edit_inventory"),
        "can_manage_purchase_orders": user_has_perm("can_edit_purchase_orders"),
        "can_manage_transfers":       user_has_perm("can_edit_transfers"),
        "can_manage_finance":         user_has_perm("can_edit_finance"),
        "can_manage_users":           is_admin,
        "can_manage_organizations":   user_has_perm("can_edit_organizations"),
    }

    menu = [
        {"key": "dashboard",     "label": "Dashboard",     "path": "/dashboard",     "visible": True},
        {"key": "organizations", "label": "Organización",  "path": "/organizations", "visible": user_has_perm("can_view_organizations")},
        {"key": "products",      "label": "Productos",     "path": "/products",      "visible": user_has_perm("can_view_products")},
        {"key": "suppliers",     "label": "Proveedores",   "path": "/suppliers",     "visible": user_has_perm("can_view_suppliers")},
        {"key": "inventory",     "label": "Inventario",    "path": "/inventory",     "visible": user_has_perm("can_view_inventory")},
        {"key": "purchasing",    "label": "Compras",       "path": "/purchasing",    "visible": user_has_perm("can_view_supply_requests") or user_has_perm("can_view_purchase_orders")},
        {"key": "transfers",     "label": "Traspasos",     "path": "/transfers",     "visible": user_has_perm("can_view_transfers")},
        {"key": "finance",       "label": "Finanzas",      "path": "/finance",       "visible": user_has_perm("can_view_finance")},
        {"key": "evaluations",   "label": "Evaluaciones",  "path": "/evaluations",   "visible": True},
        {"key": "reports",       "label": "Reportes",      "path": "/reports",       "visible": user_has_perm("can_view_reports")},
        {"key": "users",         "label": "Usuarios",      "path": "/users",         "visible": is_admin},
        {"key": "roles",         "label": "Roles",         "path": "/roles",         "visible": is_admin},
        {"key": "audit",         "label": "Auditoría",     "path": "/audit",         "visible": user_has_perm("can_view_audit")},
    ]

    data = {
        "user": {
            "id": user.id,
            "uuid": str(user.profile.uuid) if hasattr(user, "profile") else None,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        },
        "roles": roles,
        "role_codes": role_codes,
        "scopes": {
            "organizations": organizations,
            "legal_entities": legal_entities,
            "branches": branches,
        },
        "permissions": permissions,
        "menu": [item for item in menu if item["visible"]],
    }

    return api_response(data=data, message="Usuario autenticado obtenido correctamente.")


@api_view(["POST"])
@permission_classes([AllowAny])
def google_login(request):
    """
    Valida un ID Token de Google y entrega los JWT internos de MauleMed.

    El usuario debe existir previamente en MauleMed y su correo debe coincidir
    con el correo verificado de Google.
    """
    credential = request.data.get("credential")

    if not credential:
        return api_error(
            message="No se recibió la credencial de Google.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not settings.GOOGLE_CLIENT_ID:
        logger.error("GOOGLE_CLIENT_ID no está configurado.")

        return api_error(
            message="El acceso con Google no está configurado en el servidor.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        google_user = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except (ValueError, GoogleAuthError):
        logger.warning(
            "Intento de login con una credencial de Google inválida."
        )

        return api_error(
            message="La credencial de Google es inválida o expiró.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    email = (google_user.get("email") or "").strip().lower()
    email_verified = google_user.get("email_verified")

    if not email or not email_verified:
        return api_error(
            message="Google no entregó un correo verificado.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    users = User.objects.filter(email__iexact=email)

    if not users.exists():
        logger.warning(
            "Login Google rechazado. Correo no registrado: %s",
            email,
        )

        return api_error(
            message=(
                "No existe un usuario MauleMed asociado "
                "a esta cuenta de Google."
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if users.count() > 1:
        logger.error(
            "Existen varios usuarios asociados al correo: %s",
            email,
        )

        return api_error(
            message=(
                "El correo está asociado a más de un usuario. "
                "Contacte al administrador."
            ),
            status_code=status.HTTP_409_CONFLICT,
        )

    user = users.first()

    if not user.is_active:
        return api_error(
            message="El usuario se encuentra deshabilitado.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    refresh = RefreshToken.for_user(user)

    logger.info(
        "Login Google exitoso. Usuario: %s",
        user.username,
    )

    return api_response(
        data={
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
        },
        message="Login con Google realizado correctamente.",
    )