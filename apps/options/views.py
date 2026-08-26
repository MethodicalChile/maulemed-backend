from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.common.responses import api_response
from apps.common.scopes import (
    apply_branch_scope,
    apply_legal_entity_scope,
    apply_organization_scope,
)

from apps.accounts.models import Role
from apps.organizations.models import Organization, LegalEntity, Branch, CostCenter
from apps.products.models import ProductCategory, UnitOfMeasure, Product
from apps.suppliers.models import Supplier
from apps.inventory.models import Warehouse, InventoryLot


# ── Límites de opciones ───────────────────────────────────────────────────────
OPTIONS_DEFAULT_LIMIT = 100
OPTIONS_MAX_LIMIT     = 200


def get_limit(request):
    """Lee ?limit= de la request, acotado a OPTIONS_MAX_LIMIT."""
    try:
        limit = int(request.GET.get("limit", OPTIONS_DEFAULT_LIMIT))
        return max(1, min(limit, OPTIONS_MAX_LIMIT))
    except (TypeError, ValueError):
        return OPTIONS_DEFAULT_LIMIT


def serialize_option(obj, label=None, extra=None):
    data = {
        "id":    obj.id,
        "uuid":  str(obj.uuid),
        "label": label if label is not None else str(obj),
        "name":  label if label is not None else str(obj),
    }
    if extra:
        data.update(extra)
    return data


# ── Endpoints ─────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_options(request):
    qs     = Organization.objects.filter(is_active=True).order_by("name")
    qs     = apply_organization_scope(qs, request.user, organization_field="self")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search)
    limit = get_limit(request)
    data = [
        serialize_option(obj, label=obj.name, extra={"rut": obj.rut})
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de organizaciones obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def legal_entity_options(request):
    qs     = LegalEntity.objects.select_related("organization").filter(is_active=True).order_by("name")
    qs     = apply_legal_entity_scope(qs, request.user, legal_entity_field="self")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search)
    limit = get_limit(request)
    data = [
        serialize_option(
            obj, label=obj.name,
            extra={
                "rut":               obj.rut,
                "organization_uuid": str(obj.organization.uuid) if obj.organization else None,
            },
        )
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de razones sociales obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def branch_options(request):
    qs     = Branch.objects.select_related("organization", "legal_entity").filter(is_active=True).order_by("name")
    qs     = apply_branch_scope(qs, request.user, branch_field="self")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search)
    limit = get_limit(request)
    data = [
        serialize_option(
            obj, label=obj.name,
            extra={
                "code":               obj.code,
                "city":               obj.city,
                "organization_uuid":  str(obj.organization.uuid)  if obj.organization  else None,
                "legal_entity_uuid":  str(obj.legal_entity.uuid)  if obj.legal_entity  else None,
            },
        )
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de sucursales obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cost_center_options(request):
    qs = CostCenter.objects.select_related("legal_entity", "branch").filter(is_active=True)
    scoped_by_branch = apply_branch_scope(qs.filter(branch__isnull=False),  request.user, branch_field="branch")
    scoped_by_entity = apply_legal_entity_scope(qs.filter(branch__isnull=True), request.user, legal_entity_field="legal_entity")
    qs = (scoped_by_branch | scoped_by_entity).distinct().order_by("code")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(code__icontains=search)
        qs = qs.distinct()
    limit = get_limit(request)
    data = [
        serialize_option(
            obj, label=f"{obj.code} - {obj.name}",
            extra={
                "code":               obj.code,
                "legal_entity_uuid":  str(obj.legal_entity.uuid) if obj.legal_entity else None,
                "branch_uuid":        str(obj.branch.uuid)        if obj.branch        else None,
            },
        )
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de centros de costo obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def product_category_options(request):
    qs     = ProductCategory.objects.filter(is_active=True).order_by("name")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search)
    limit = get_limit(request)
    data = [serialize_option(obj, label=obj.name) for obj in qs[:limit]]
    return api_response(data=data, message="Opciones de categorías obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unit_options(request):
    qs     = UnitOfMeasure.objects.all().order_by("code")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(code__icontains=search)
    limit = get_limit(request)
    data = [
        serialize_option(obj, label=f"{obj.code} - {obj.name}", extra={"code": obj.code})
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de unidades de medida obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def product_options(request):
    qs     = Product.objects.select_related("category", "unit").filter(is_active=True).order_by("name")
    search = request.GET.get("search")
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(internal_code__icontains=search) |
            Q(sku__icontains=search)
        )
    limit = get_limit(request)
    data = [
        serialize_option(
            obj, label=obj.name,
            extra={
                "internal_code":            obj.internal_code,
                "sku":                      obj.sku,
                "category_uuid":            str(obj.category.uuid) if obj.category else None,
                "unit_uuid":                str(obj.unit.uuid)     if obj.unit     else None,
                "requires_lot":             obj.requires_lot,
                "requires_expiration_date": obj.requires_expiration_date,
                "is_medication":            obj.is_medication,
                "is_controlled":            obj.is_controlled,
            },
        )
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de productos obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def supplier_options(request):
    qs     = Supplier.objects.filter(is_active=True).order_by("name")
    search = request.GET.get("search")
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=search) | Q(rut__icontains=search))
    limit = get_limit(request)
    data = [
        serialize_option(
            obj, label=obj.name,
            extra={"rut": obj.rut, "email": obj.email, "phone": obj.phone},
        )
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de proveedores obtenidas correctamente.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def warehouse_options(request):
    qs     = Warehouse.objects.select_related("branch").filter(is_active=True).order_by("name")
    qs     = apply_branch_scope(qs, request.user, branch_field="branch")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(branch__name__icontains=search)
        qs = qs.distinct()
    limit = get_limit(request)
    data = [
        serialize_option(
            obj, label=f"{obj.branch.name} - {obj.name}",
            extra={
                "warehouse_type": obj.warehouse_type,
                "branch_uuid":    str(obj.branch.uuid) if obj.branch else None,
            },
        )
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de bodegas obtenidas correctamente.")

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inventory_lot_options(request):
    qs = (
        InventoryLot.objects
        .select_related(
            "warehouse",
            "warehouse__branch",
            "product",
            "supplier",
        )
        .filter(
            deleted_at__isnull=True,
            quantity__gt=0,
            status=InventoryLot.STATUS_AVAILABLE,
        )
        .order_by(
            "product__name",
            "lot_number",
        )
    )

    qs = apply_branch_scope(
        qs,
        request.user,
        branch_field="warehouse__branch",
    )

    product_uuid = request.GET.get("product")
    if product_uuid:
        qs = qs.filter(
            product__uuid=product_uuid,
        )

    warehouse_uuid = request.GET.get("warehouse")
    if warehouse_uuid:
        qs = qs.filter(
            warehouse__uuid=warehouse_uuid,
        )

    branch_uuid = request.GET.get("branch")
    if branch_uuid:
        qs = qs.filter(
            warehouse__branch__uuid=branch_uuid,
        )

    search = request.GET.get("search")

    if search:
        from django.db.models import Q

        qs = qs.filter(
            Q(lot_number__icontains=search)
            | Q(product__name__icontains=search)
            | Q(product__internal_code__icontains=search)
        )

    limit = get_limit(request)

    data = [
        serialize_option(
            obj,
            label=(
                f"{obj.product.name} - "
                f"{obj.lot_number or 'Sin lote'} - "
                f"Stock: {obj.quantity}"
            ),
            extra={
                "lot_number": obj.lot_number,
                "expiration_date": (
                    obj.expiration_date.isoformat()
                    if obj.expiration_date
                    else None
                ),
                "quantity": str(obj.quantity),
                "status": obj.status,

                "product": str(obj.product.uuid),
                "product_uuid": str(obj.product.uuid),

                "warehouse_uuid": str(
                    obj.warehouse.uuid
                ),

                "warehouse_name": (
                    obj.warehouse.name
                    if obj.warehouse
                    else None
                ),

                "branch_uuid": (
                    str(obj.warehouse.branch.uuid)
                    if obj.warehouse
                    and obj.warehouse.branch
                    else None
                ),

                "branch_name": (
                    obj.warehouse.branch.name
                    if obj.warehouse
                    and obj.warehouse.branch
                    else None
                ),

                "supplier_uuid": (
                    str(obj.supplier.uuid)
                    if obj.supplier
                    else None
                ),
            },
        )
        for obj in qs[:limit]
    ]

    return api_response(
        data=data,
        message=(
            "Opciones de lotes de inventario "
            "obtenidas correctamente."
        ),
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def role_options(request):
    qs     = Role.objects.filter(is_active=True).order_by("name")
    search = request.GET.get("search")
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(code__icontains=search)
    limit = get_limit(request)
    data = [
        serialize_option(obj, label=obj.name, extra={"code": obj.code})
        for obj in qs[:limit]
    ]
    return api_response(data=data, message="Opciones de roles obtenidas correctamente.")
