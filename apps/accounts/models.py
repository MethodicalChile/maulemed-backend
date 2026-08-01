from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.organizations.models import Organization, LegalEntity, Branch


class UserProfile(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    rut      = models.CharField(max_length=20, blank=True, null=True, unique=True)
    phone    = models.CharField(max_length=50, blank=True, null=True)
    position = models.CharField(max_length=120, blank=True, null=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL,
        related_name="user_profiles", blank=True, null=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "user_profiles"

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Role(BaseModel):
    """
    Rol del sistema. El código es libre — lo define el admin.
    Los roles base del sistema se crean via fixtures/seed.
    """
    code        = models.CharField(max_length=50, unique=True)
    name        = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    is_active   = models.BooleanField(default=True)

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.name


class RolePermission(BaseModel):
    """
    Permisos asignados a un rol. Persiste qué permission_key tiene cada rol.
    Si existe una fila role+permission_key → el rol tiene ese permiso.
    """
    role           = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission_key = models.CharField(max_length=100)

    class Meta:
        db_table = "role_permissions"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission_key"], name="uq_role_permission")
        ]

    def __str__(self):
        return f"{self.role.code} → {self.permission_key}"


class UserRoleAssignment(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_assignments")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="role_assignments",
        blank=True, null=True,
    )
    legal_entity = models.ForeignKey(
        LegalEntity, on_delete=models.CASCADE, related_name="role_assignments",
        blank=True, null=True,
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name="role_assignments",
        blank=True, null=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "user_role_assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "organization", "legal_entity", "branch"],
                name="uq_user_role_scope",
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.role}"
