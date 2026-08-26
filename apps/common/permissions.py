from rest_framework.permissions import BasePermission, SAFE_METHODS


def get_user_role_codes(user):
    if not user or not user.is_authenticated:
        return []
    return list(
        user.role_assignments.filter(is_active=True)
        .select_related("role")
        .values_list("role__code", flat=True)
    )


def user_has_any_role(user, allowed_roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    roles = get_user_role_codes(user)
    return any(role in roles for role in allowed_roles)


def user_has_permission_key(user, permission_key):
    """
    Verifica si el usuario tiene un permission_key, leyendo RolePermission (BD)
    con fallback a defaults hardcodeados para roles sin configuración.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    # Importación lazy para evitar circular imports
    from apps.accounts.models import RolePermission

    role_codes = get_user_role_codes(user)
    if not role_codes:
        return False

    # Permisos guardados en BD por rol
    saved = {}
    for rp in RolePermission.objects.filter(
        role__code__in=role_codes
    ).select_related("role"):
        saved.setdefault(rp.role.code, set()).add(rp.permission_key)

    ADMIN_GERENTE_ROLES = {"ADMIN", "GERENTE"}

    # Defaults del sistema para roles no configurados — granulares
    DEFAULTS = {
        "can_view_dashboard": ADMIN_GERENTE_ROLES,
        # Organización
        "can_view_organizations":     ADMIN_GERENTE_ROLES,
        "can_create_organizations":   ADMIN_GERENTE_ROLES,
        "can_edit_organizations":     ADMIN_GERENTE_ROLES,
        "can_delete_organizations":   ADMIN_GERENTE_ROLES,
        # Productos
        "can_view_products":          ADMIN_GERENTE_ROLES,
        "can_create_products":        ADMIN_GERENTE_ROLES,
        "can_edit_products":          ADMIN_GERENTE_ROLES,
        "can_delete_products":        ADMIN_GERENTE_ROLES,
        # Proveedores
        "can_view_suppliers":         ADMIN_GERENTE_ROLES,
        "can_create_suppliers":       ADMIN_GERENTE_ROLES,
        "can_edit_suppliers":         ADMIN_GERENTE_ROLES,
        "can_delete_suppliers":       ADMIN_GERENTE_ROLES,
        # Inventario — Movimientos
        "can_view_inventory":         ADMIN_GERENTE_ROLES,
        "can_create_inventory":       ADMIN_GERENTE_ROLES,
        "can_edit_inventory":         ADMIN_GERENTE_ROLES,
        "can_delete_inventory":       ADMIN_GERENTE_ROLES,
        # Inventario — Bodegas
        "can_view_warehouses":        ADMIN_GERENTE_ROLES,
        "can_create_warehouses":      ADMIN_GERENTE_ROLES,
        "can_edit_warehouses":        ADMIN_GERENTE_ROLES,
        "can_delete_warehouses":      ADMIN_GERENTE_ROLES,
        # Compras — solicitudes
        "can_view_supply_requests":   ADMIN_GERENTE_ROLES,
        "can_create_supply_request":  ADMIN_GERENTE_ROLES,
        "can_edit_supply_request":    ADMIN_GERENTE_ROLES,
        "can_approve_supply_request": ADMIN_GERENTE_ROLES,
        # Compras — órdenes
        "can_view_purchase_orders":   ADMIN_GERENTE_ROLES,
        "can_create_purchase_orders": ADMIN_GERENTE_ROLES,
        "can_edit_purchase_orders":   ADMIN_GERENTE_ROLES,
        "can_delete_purchase_orders": ADMIN_GERENTE_ROLES,
        "can_receive_purchase":       ADMIN_GERENTE_ROLES,
        # Traspasos
        "can_view_transfers":         ADMIN_GERENTE_ROLES,
        "can_create_transfers":       ADMIN_GERENTE_ROLES,
        "can_edit_transfers":         ADMIN_GERENTE_ROLES,
        "can_delete_transfers":       ADMIN_GERENTE_ROLES,
        # Finanzas
        "can_view_finance":           ADMIN_GERENTE_ROLES,
        "can_create_finance":         ADMIN_GERENTE_ROLES,
        "can_edit_finance":           ADMIN_GERENTE_ROLES,
        "can_delete_finance":         ADMIN_GERENTE_ROLES,
        # Ingresos
        "can_view_revenue": ADMIN_GERENTE_ROLES,
        "can_create_revenue": ADMIN_GERENTE_ROLES,
        "can_edit_revenue": ADMIN_GERENTE_ROLES,
        "can_delete_revenue": ADMIN_GERENTE_ROLES,
        # Evaluaciones
        "can_view_evaluations":       ADMIN_GERENTE_ROLES,
        "can_create_evaluations":     ADMIN_GERENTE_ROLES,
        "can_edit_evaluations":       ADMIN_GERENTE_ROLES,
        "can_delete_evaluations":     ADMIN_GERENTE_ROLES,
        # Reportes / usuarios / auditoría
        "can_view_reports":           ADMIN_GERENTE_ROLES,
        "can_view_users":             ADMIN_GERENTE_ROLES,
        "can_create_users":           ADMIN_GERENTE_ROLES,
        "can_edit_users":             ADMIN_GERENTE_ROLES,
        "can_delete_users":           ADMIN_GERENTE_ROLES,
        "can_view_roles":             ADMIN_GERENTE_ROLES,
        "can_create_roles":           ADMIN_GERENTE_ROLES,
        "can_edit_roles":             ADMIN_GERENTE_ROLES,
        "can_delete_roles":           ADMIN_GERENTE_ROLES,
        "can_view_audit":             ADMIN_GERENTE_ROLES,
        # Mantenedor
        "can_view_maintenance":       ADMIN_GERENTE_ROLES,
        "can_create_maintenance":     ADMIN_GERENTE_ROLES,
        "can_edit_maintenance":       ADMIN_GERENTE_ROLES,
        "can_delete_maintenance":     ADMIN_GERENTE_ROLES,
        # Aliases legacy para compatibilidad con ViewSets existentes
        # "can_manage_organizations":   ADMIN_GERENTE_ROLES,
        # "can_manage_catalogs":        ADMIN_GERENTE_ROLES,
        # "can_view_catalogs":          ADMIN_GERENTE_ROLES,
        # "can_manage_products":        ADMIN_GERENTE_ROLES,
        # "can_manage_suppliers":       ADMIN_GERENTE_ROLES,
        # "can_manage_inventory":       ADMIN_GERENTE_ROLES,
        # "can_manage_purchase_orders": ADMIN_GERENTE_ROLES,
        # "can_manage_transfers":       ADMIN_GERENTE_ROLES,
        # "can_manage_finance":         ADMIN_GERENTE_ROLES,
        # "can_manage_users":           ADMIN_GERENTE_ROLES,
    }

    for code in role_codes:
        if code in saved:
            print(f"DEBUG: code {code} in saved, permissions: {saved[code]}")
            if permission_key in saved[code]:
                return True
        else:
            print(f"DEBUG: code {code} NOT in saved, checking defaults for {permission_key}")
            if code in DEFAULTS.get(permission_key, set()):
                return True

    print(f"DEBUG: returning False for permission_key {permission_key}")
    return False

class CanManageEvaluationQuestions(BasePermission):
    """
    Permisos CRUD para preguntas de Evaluaciones.

    GET / HEAD / OPTIONS
        -> can_view_evaluations

    POST
        -> can_create_evaluations

    PUT / PATCH
        -> can_edit_evaluations

    DELETE
        -> can_delete_evaluations
    """

    def has_permission(
        self,
        request,
        view,
    ):
        if (
            not request.user
            or not request.user.is_authenticated
        ):
            return False

        if request.method in SAFE_METHODS:
            permission_key = (
                "can_view_evaluations"
            )

        elif request.method == "POST":
            permission_key = (
                "can_create_evaluations"
            )

        elif request.method in (
            "PUT",
            "PATCH",
        ):
            permission_key = (
                "can_edit_evaluations"
            )

        elif request.method == "DELETE":
            permission_key = (
                "can_delete_evaluations"
            )

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )
    
class HasAnyRole(BasePermission):
    allowed_roles = []

    def has_permission(self, request, view):
        return user_has_any_role(request.user, self.allowed_roles)


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return user_has_any_role(request.user, ["ADMIN"])


class CanEditRoles(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return user_has_permission_key(request.user, "can_edit_roles")


class CanManageUserProfilesAndRoles(BasePermission):
    """
    Permisos para gestionar perfiles de usuarios y asignaciones de roles.
    Permite:
    - Lectura (GET): si tiene 'can_view_users'
    - Creación (POST): si tiene 'can_create_users' o 'can_edit_users'
    - Modificación (PUT/PATCH): si tiene 'can_edit_users'
    - Eliminación (DELETE): si tiene 'can_edit_users' o 'can_delete_users'
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_users"

        elif request.method == "POST":
            return (
                user_has_permission_key(request.user, "can_create_users") or
                user_has_permission_key(request.user, "can_edit_users")
            )

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_users"

        elif request.method == "DELETE":
            return (
                user_has_permission_key(request.user, "can_edit_users") or
                user_has_permission_key(request.user, "can_delete_users")
            )

        else:
            return False

        return user_has_permission_key(request.user, permission_key)


class IsAdminOrGerente(HasAnyRole):
    allowed_roles = ["ADMIN", "GERENTE"]


class PermissionKeyRequired(BasePermission):
    """
    Permiso genérico que verifica un permission_key en la BD (RolePermission).
    read_key: permiso requerido para GET/HEAD/OPTIONS
    write_key: permiso requerido para POST/PUT/PATCH/DELETE
    Si write_key es None → solo read_key aplica a todos los métodos.
    """
    read_key  = None
    write_key = None

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            key = self.read_key or self.write_key
        else:
            key = self.write_key or self.read_key
        if not key:
            return request.user and request.user.is_authenticated
        return user_has_permission_key(request.user, key)


# ── Clases de conveniencia por módulo ─────────────────────────────────────────

class CanManageCatalogs(PermissionKeyRequired):
    read_key  = "can_view_catalogs"
    write_key = "can_manage_catalogs"


class CanManageProducts(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_products"

        elif request.method == "POST":
            permission_key = "can_create_products"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_products"

        elif request.method == "DELETE":
            permission_key = "can_delete_products"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )


class CanManageSuppliers(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_suppliers"

        elif request.method == "POST":
            permission_key = "can_create_suppliers"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_suppliers"

        elif request.method == "DELETE":
            permission_key = "can_delete_suppliers"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key
        )


class CanViewInventory(PermissionKeyRequired):
    read_key  = "can_view_inventory"
    write_key = "can_view_inventory"


class CanManageInventory(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return (
                user_has_permission_key(request.user, "can_view_inventory") or
                user_has_permission_key(request.user, "can_view_warehouses")
            )

        elif request.method == "POST":
            permission_key = "can_create_inventory"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_inventory"

        elif request.method == "DELETE":
            permission_key = "can_delete_inventory"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key
        )

class CanManageWarehouses(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return (
                user_has_permission_key(request.user, "can_view_warehouses") or
                user_has_permission_key(request.user, "can_view_inventory")
            )

        elif request.method == "POST":
            permission_key = "can_create_warehouses"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_warehouses"

        elif request.method == "DELETE":
            permission_key = "can_delete_warehouses"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key
        )
    
class CanCreateSupplyRequest(PermissionKeyRequired):
    read_key  = "can_create_supply_request"
    write_key = "can_create_supply_request"


class CanApproveSupplyRequest(PermissionKeyRequired):
    read_key  = "can_approve_supply_request"
    write_key = "can_approve_supply_request"


class CanManagePurchasing(PermissionKeyRequired):
    # Lectura (GET): solo roles que pueden ver solicitudes
    read_key  = "can_create_supply_request"
    # Escritura (POST/PATCH/DELETE): el ViewSet delega a ensure_action_permission
    # para las acciones específicas. A nivel ViewSet basta con can_create_supply_request.
    write_key = "can_create_supply_request"

class CanAccessSupplyRequests(BasePermission):
    """
    Solicitudes de compra.

    GET/HEAD/OPTIONS -> can_view_supply_requests
    POST             -> can_create_supply_request
    PUT/PATCH        -> can_edit_supply_request
    DELETE           -> no permitido actualmente
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_supply_requests"

        elif request.method == "POST":
            permission_key = "can_create_supply_request"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_supply_request"

        elif request.method == "DELETE":
            return False

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )


class CanAccessPurchaseOrders(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_purchase_orders"

        elif request.method == "POST":
            permission_key = "can_create_purchase_orders"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_purchase_orders"

        elif request.method == "DELETE":
            permission_key = "can_delete_purchase_orders"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )
    
class CanManageEvaluations(BasePermission):
    """
    Permisos granulares del módulo Evaluaciones.
    """

    VIEW_ACTIONS = {
        "list",
        "retrieve",
        "questions",
        "qr",
        "responses_summary",
    }

    CREATE_ACTIONS = {
        "create",
    }

    EDIT_ACTIONS = {
        "update",
        "partial_update",
        "toggle_active",
        "publish_google_form",
        "resync_google_form",
        "sync_responses",
    }

    DELETE_ACTIONS = {
        "destroy",
    }

    def has_permission(
        self,
        request,
        view,
    ):
        if (
            not request.user
            or not request.user.is_authenticated
        ):
            return False

        action = getattr(
            view,
            "action",
            None,
        )

        if action in self.VIEW_ACTIONS:
            permission_key = (
                "can_view_evaluations"
            )

        elif action in self.CREATE_ACTIONS:
            permission_key = (
                "can_create_evaluations"
            )

        elif action in self.EDIT_ACTIONS:
            permission_key = (
                "can_edit_evaluations"
            )

        elif action in self.DELETE_ACTIONS:
            permission_key = (
                "can_delete_evaluations"
            )

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )

class CanAccessPurchaseReceipts(BasePermission):
    """
    Permisos granulares para Recepciones de compra.

    GET / HEAD / OPTIONS
        -> can_view_purchase_receipts

    POST
        -> can_create_purchase_receipts

    PUT / PATCH
        -> can_edit_purchase_receipts

    DELETE
        -> can_delete_purchase_receipts
    """

    def has_permission(
        self,
        request,
        view,
    ):
        if (
            not request.user
            or not request.user.is_authenticated
        ):
            return False

        if request.method in SAFE_METHODS:
            permission_key = (
                "can_view_purchase_receipts"
            )

        elif request.method == "POST":
            permission_key = (
                "can_create_purchase_receipts"
            )

        elif request.method in (
            "PUT",
            "PATCH",
        ):
            permission_key = (
                "can_edit_purchase_receipts"
            )

        elif request.method == "DELETE":
            permission_key = (
                "can_delete_purchase_receipts"
            )

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )
    
class CanAccessSupplierClaims(BasePermission):
    """
    Permisos granulares para Reclamos de proveedores.

    GET / HEAD / OPTIONS
        -> can_view_supplier_claims

    POST
        -> can_create_supplier_claims

    PUT / PATCH
        -> can_edit_supplier_claims

    DELETE
        -> can_delete_supplier_claims
    """

    def has_permission(
        self,
        request,
        view,
    ):
        if (
            not request.user
            or not request.user.is_authenticated
        ):
            return False

        if request.method in SAFE_METHODS:
            permission_key = (
                "can_view_supplier_claims"
            )

        elif request.method == "POST":
            permission_key = (
                "can_create_supplier_claims"
            )

        elif request.method in (
            "PUT",
            "PATCH",
        ):
            permission_key = (
                "can_edit_supplier_claims"
            )

        elif request.method == "DELETE":
            permission_key = (
                "can_delete_supplier_claims"
            )

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )

class CanProcessPurchaseReceipt(BasePermission):
    """
    Permiso específico para procesar
    una recepción de compra.
    """

    def has_permission(
        self,
        request,
        view,
    ):
        if (
            not request.user
            or not request.user.is_authenticated
        ):
            return False

        return user_has_permission_key(
            request.user,
            "can_process_purchase_receipts",
        )

class CanApprovePurchaseOrder(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return user_has_permission_key(request.user, "can_approve_purchase_orders")


class CanManageTransfers(BasePermission):
    """
    Permisos granulares para el CRUD principal de Traspasos.

    GET / HEAD / OPTIONS
        -> can_view_transfers

    POST
        -> can_create_transfers

    PUT / PATCH
        -> can_edit_transfers

    DELETE
        -> can_delete_transfers
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_transfers"

        elif request.method == "POST":
            permission_key = "can_create_transfers"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_transfers"

        elif request.method == "DELETE":
            permission_key = "can_delete_transfers"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )


class CanApproveTransfer(BasePermission):
    """
    Permiso para acciones de flujo que modifican un traspaso.

    Ejemplos:
    - aprobar
    - rechazar
    - enviar
    - recibir
    - cerrar

    Todas estas operaciones requieren:
        can_edit_transfers
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return user_has_permission_key(
            request.user,
            "can_edit_transfers",
        )


class CanManageFinance(BasePermission):
    """
    Permisos granulares para el módulo de Finanzas.

    GET / HEAD / OPTIONS
        -> can_view_finance

    POST
        -> can_create_finance

    PUT / PATCH
        -> can_edit_finance

    DELETE
        -> can_delete_finance
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_finance"

        elif request.method == "POST":
            permission_key = "can_create_finance"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_finance"

        elif request.method == "DELETE":
            permission_key = "can_delete_finance"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )

class CanManageRevenue(BasePermission):
    """
    Permisos granulares para el módulo de Ingresos.

    GET / HEAD / OPTIONS
        -> can_view_revenue

    POST
        -> can_create_revenue

    PUT / PATCH
        -> can_edit_revenue

    DELETE
        -> can_delete_revenue
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_revenue"

        elif request.method == "POST":
            permission_key = "can_create_revenue"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_revenue"

        elif request.method == "DELETE":
            permission_key = "can_delete_revenue"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )
    
class CanManageDocuments(BasePermission):
    """
    Permiso para acceder y utilizar
    la funcionalidad de carga/análisis
    de documentos.
    """

    def has_permission(
        self,
        request,
        view,
    ):
        if (
            not request.user
            or not request.user.is_authenticated
        ):
            return False

        return user_has_permission_key(
            request.user,
            "can_access_document_preview",
        )

class CanViewAudit(PermissionKeyRequired):
    read_key  = "can_view_audit"
    write_key = "can_view_audit"

class CanManageMaintenance(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_maintenance"

        elif request.method == "POST":
            permission_key = "can_create_maintenance"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_maintenance"

        elif request.method == "DELETE":
            permission_key = "can_delete_maintenance"

        else:
            return False

        return user_has_permission_key(request.user, permission_key)
    
class CanManageOrganizations(BasePermission):

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            permission_key = "can_view_organizations"

        elif request.method == "POST":
            permission_key = "can_create_organizations"

        elif request.method in ("PUT", "PATCH"):
            permission_key = "can_edit_organizations"

        elif request.method == "DELETE":
            permission_key = "can_delete_organizations"

        else:
            return False

        return user_has_permission_key(
            request.user,
            permission_key,
        )