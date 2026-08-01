from apps.common.permissions import get_user_role_codes


GLOBAL_ROLES = ["ADMIN"]


def user_is_global(user):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    roles = get_user_role_codes(user)
    return any(role in roles for role in GLOBAL_ROLES)


def get_user_scope_ids(user):
    if not user or not user.is_authenticated:
        return {
            "is_global": False,
            "organization_ids": [],
            "legal_entity_ids": [],
            "branch_ids": [],
        }

    if user_is_global(user):
        return {
            "is_global": True,
            "organization_ids": [],
            "legal_entity_ids": [],
            "branch_ids": [],
        }

    assignments = user.role_assignments.filter(is_active=True).select_related(
        "organization",
        "legal_entity",
        "branch",
    )

    organization_ids = []
    legal_entity_ids = []
    branch_ids = []

    for assignment in assignments:
        if assignment.organization_id:
            organization_ids.append(assignment.organization_id)

        if assignment.legal_entity_id:
            legal_entity_ids.append(assignment.legal_entity_id)

        if assignment.branch_id:
            branch_ids.append(assignment.branch_id)

    return {
        "is_global": False,
        "organization_ids": list(set(organization_ids)),
        "legal_entity_ids": list(set(legal_entity_ids)),
        "branch_ids": list(set(branch_ids)),
    }


def apply_branch_scope(queryset, user, branch_field="branch"):
    scope = get_user_scope_ids(user)

    if scope["is_global"]:
        return queryset

    branch_ids = scope["branch_ids"]
    legal_entity_ids = scope["legal_entity_ids"]
    organization_ids = scope["organization_ids"]

    if branch_field == "self":
        if branch_ids:
            return queryset.filter(id__in=branch_ids)

        if legal_entity_ids:
            return queryset.filter(legal_entity_id__in=legal_entity_ids)

        if organization_ids:
            return queryset.filter(organization_id__in=organization_ids)

        return queryset.none()

    if branch_ids:
        return queryset.filter(**{f"{branch_field}_id__in": branch_ids})

    if legal_entity_ids:
        return queryset.filter(**{f"{branch_field}__legal_entity_id__in": legal_entity_ids})

    if organization_ids:
        return queryset.filter(**{f"{branch_field}__organization_id__in": organization_ids})

    return queryset.none()


def apply_legal_entity_scope(queryset, user, legal_entity_field="legal_entity"):
    scope = get_user_scope_ids(user)

    if scope["is_global"]:
        return queryset

    legal_entity_ids = scope["legal_entity_ids"]
    organization_ids = scope["organization_ids"]

    if legal_entity_field == "self":
        if legal_entity_ids:
            return queryset.filter(id__in=legal_entity_ids)

        if organization_ids:
            return queryset.filter(organization_id__in=organization_ids)

        return queryset.none()

    if legal_entity_ids:
        return queryset.filter(**{f"{legal_entity_field}_id__in": legal_entity_ids})

    if organization_ids:
        return queryset.filter(**{f"{legal_entity_field}__organization_id__in": organization_ids})

    return queryset.none()


def apply_organization_scope(queryset, user, organization_field="organization"):
    scope = get_user_scope_ids(user)

    if scope["is_global"]:
        return queryset

    organization_ids = scope["organization_ids"]

    if organization_field == "self":
        if organization_ids:
            return queryset.filter(id__in=organization_ids)

        return queryset.none()

    if organization_ids:
        return queryset.filter(**{f"{organization_field}_id__in": organization_ids})

    return queryset.none()
