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

    # Defaults del sistema para roles no configurados — granulares
    DEFAULTS = {
        "can_view_dashboard":         set(role_codes),
        # Organización
        "can_view_organizations":     {"ADMIN","GERENTE"},
        "can_create_organizations":   {"ADMIN","GERENTE"},
        "can_edit_organizations":     {"ADMIN","GERENTE"},
        "can_delete_organizations":   {"ADMIN"},
        # Productos
        "can_view_products":          {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"},
        "can_create_products":        {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_edit_products":          {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_delete_products":        {"ADMIN","GERENTE","ABASTECIMIENTO"},
        # Proveedores
        "can_view_suppliers":         {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS"},
        "can_create_suppliers":       {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_edit_suppliers":         {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_delete_suppliers":       {"ADMIN","GERENTE","ABASTECIMIENTO"},
        # Inventario
        "can_view_inventory":         {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"},
        "can_create_inventory":       {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_edit_inventory":         {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_delete_inventory":       {"ADMIN","GERENTE","ABASTECIMIENTO"},
        # Compras — solicitudes
        "can_view_supply_requests":   {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA"},
        "can_create_supply_request":  {"ADMIN","GERENTE","ABASTECIMIENTO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA"},
        "can_edit_supply_request":    {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_approve_supply_request": {"ADMIN","GERENTE","ABASTECIMIENTO"},
        # Compras — órdenes
        "can_view_purchase_orders":   {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS"},
        "can_create_purchase_orders": {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_edit_purchase_orders":   {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_delete_purchase_orders": {"ADMIN","GERENTE"},
        "can_receive_purchase":       {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        # Traspasos
        "can_view_transfers":         {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_create_transfers":       {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_edit_transfers":         {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_delete_transfers":       {"ADMIN","GERENTE","ABASTECIMIENTO"},
        # Finanzas
        "can_view_finance":           {"ADMIN","GERENTE","FINANZAS"},
        "can_create_finance":         {"ADMIN","GERENTE","FINANZAS"},
        "can_edit_finance":           {"ADMIN","GERENTE","FINANZAS"},
        "can_delete_finance":         {"ADMIN","GERENTE"},
        # Evaluaciones
        "can_view_evaluations":       set(role_codes),
        "can_create_evaluations":     {"ADMIN","GERENTE"},
        "can_edit_evaluations":       {"ADMIN","GERENTE"},
        "can_delete_evaluations":     {"ADMIN"},
        # Reportes / usuarios / auditoría
        "can_view_reports":           {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL"},
        "can_view_users":             {"ADMIN"},
        "can_create_users":           {"ADMIN"},
        "can_edit_users":             {"ADMIN"},
        "can_delete_users":           {"ADMIN"},
        "can_view_roles":             {"ADMIN"},
        "can_create_roles":           {"ADMIN"},
        "can_edit_roles":             {"ADMIN"},
        "can_delete_roles":           {"ADMIN"},
        "can_view_audit":             {"ADMIN","GERENTE"},
        # Aliases legacy para compatibilidad con ViewSets existentes
        "can_manage_organizations":   {"ADMIN","GERENTE"},
        "can_manage_catalogs":        {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_view_catalogs":          {"ADMIN","GERENTE","ABASTECIMIENTO","FINANZAS","BODEGUERO","JEFA_SUCURSAL","SECRETARIA","TENS","TECNOLOGA_MEDICA","DOCTOR"},
        "can_manage_products":        {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_manage_suppliers":       {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_manage_inventory":       {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_manage_purchase_orders": {"ADMIN","GERENTE","ABASTECIMIENTO"},
        "can_manage_transfers":       {"ADMIN","GERENTE","ABASTECIMIENTO","BODEGUERO","JEFA_SUCURSAL","TENS","TECNOLOGA_MEDICA"},
        "can_manage_finance":         {"ADMIN","GERENTE","FINANZAS"},
        "can_manage_users":           {"ADMIN"},
    }

    for code in role_codes:
        if code in saved:
            if permission_key in saved[code]:
                return True
        else:
            if code in DEFAULTS.get(permission_key, set()):
                return True

    return False


class HasAnyRole(BasePermission):
    allowed_roles = []

    def has_permission(self, request, view):
        return user_has_any_role(request.user, self.allowed_roles)


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return user_has_any_role(request.user, ["ADMIN"])


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


class CanManageProducts(PermissionKeyRequired):
    read_key  = "can_view_products"
    write_key = "can_manage_products"


class CanManageSuppliers(PermissionKeyRequired):
    read_key  = "can_view_suppliers"
    write_key = "can_manage_suppliers"


class CanViewInventory(PermissionKeyRequired):
    read_key  = "can_view_inventory"
    write_key = "can_view_inventory"


class CanManageInventory(PermissionKeyRequired):
    read_key  = "can_view_inventory"
    write_key = "can_manage_inventory"


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


class CanApprovePurchaseOrder(PermissionKeyRequired):
    read_key  = "can_manage_purchase_orders"
    write_key = "can_manage_purchase_orders"


class CanReceivePurchase(PermissionKeyRequired):
    read_key  = "can_receive_purchase"
    write_key = "can_receive_purchase"


class CanManageTransfers(PermissionKeyRequired):
    read_key  = "can_manage_transfers"
    write_key = "can_manage_transfers"


class CanApproveTransfer(PermissionKeyRequired):
    read_key  = "can_manage_transfers"
    write_key = "can_manage_transfers"


class CanManageFinance(PermissionKeyRequired):
    read_key  = "can_manage_finance"
    write_key = "can_manage_finance"


class CanManageDocuments(PermissionKeyRequired):
    read_key  = "can_manage_inventory"
    write_key = "can_manage_inventory"


class CanViewAudit(PermissionKeyRequired):
    read_key  = "can_view_audit"
    write_key = "can_view_audit"


class CanManageOrganizations(PermissionKeyRequired):
    read_key  = "can_view_organizations"
    write_key = "can_manage_organizations"
