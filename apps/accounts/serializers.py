from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.organizations.models import Organization, LegalEntity, Branch
from .models import UserProfile, Role, UserRoleAssignment

User = get_user_model()


# ── Helpers para campos con UUID ──────────────────────────────────────────────

class UUIDRelatedField(serializers.Field):
    """
    Campo que acepta un UUID y resuelve al objeto correspondiente.
    Si required=False (default), devuelve None si no se proporciona.
    """
    def __init__(self, model, **kwargs):
        self.model = model
        # Solo poner default=None cuando NO es required
        if not kwargs.get("required", False):
            kwargs.setdefault("allow_null", True)
            kwargs.setdefault("default", None)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return str(value.uuid) if value else None

    def to_internal_value(self, data):
        if not data:
            return None
        try:
            return self.model.objects.get(uuid=data)
        except self.model.DoesNotExist:
            raise serializers.ValidationError(f"No se encontró el objeto con uuid={data}.")
        except Exception:
            raise serializers.ValidationError("UUID inválido.")


# ── User ──────────────────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "full_name", "is_active", "is_staff", "is_superuser",
        ]
        read_only_fields = ["id", "is_staff", "is_superuser"]

    def get_full_name(self, obj):
        return obj.get_full_name()


class UserCreateSerializer(serializers.ModelSerializer):
    password         = serializers.CharField(write_only=True, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model  = User
        fields = ["username", "email", "first_name", "last_name",
                  "password", "password_confirm", "is_active"]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ["username", "email", "first_name", "last_name", "is_active"]

    def validate_username(self, value):
        qs = User.objects.filter(username=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe un usuario con ese nombre de usuario.")
        return value


class UserPasswordSerializer(serializers.Serializer):
    password         = serializers.CharField(write_only=True, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        validate_password(attrs["password"])
        return attrs


# ── Role ──────────────────────────────────────────────────────────────────────

class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model   = Role
        exclude = ["id", "deleted_at"]

    def validate_code(self, value):
        value = value.strip().upper().replace(" ", "_")
        if not value.replace("_", "").isalnum():
            raise serializers.ValidationError(
                "El código solo puede contener letras, números y guiones bajos."
            )
        # Verificar unicidad incluyendo registros soft-deleted (deleted_at no nulo).
        # Si existe un registro eliminado con el mismo código, ofrecemos restaurarlo
        # en vez de crear uno nuevo (evita IntegrityError 500).
        existing = Role.all_objects.filter(code=value)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        active = existing.filter(deleted_at__isnull=True)
        if active.exists():
            raise serializers.ValidationError(
                f"Ya existe un rol activo con el código '{value}'."
            )
        deleted = existing.filter(deleted_at__isnull=False)
        if deleted.exists():
            raise serializers.ValidationError(
                f"Existe un rol eliminado con el código '{value}'. "
                f"Contacta al administrador para restaurarlo en lugar de crear uno nuevo."
            )
        return value


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfileSerializer(serializers.ModelSerializer):
    user_detail         = UserSerializer(source="user", read_only=True)
    organization_detail = serializers.SerializerMethodField(read_only=True)
    # Acepta UUID para organización
    organization        = UUIDRelatedField(model=Organization, required=False)
    # Acepta ID numérico para user (viene del backend al crear)
    user                = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False
    )

    class Meta:
        model   = UserProfile
        exclude = ["id", "deleted_at"]

    def get_organization_detail(self, obj):
        if obj.organization:
            return {"uuid": str(obj.organization.uuid), "name": obj.organization.name}
        return None


# ── UserRoleAssignment ────────────────────────────────────────────────────────

class UserRoleAssignmentSerializer(serializers.ModelSerializer):
    """
    Acepta UUIDs en los campos FK de organización/entidad/sucursal.
    El campo `role` acepta UUID; `user` acepta ID numérico.
    Todos los campos de scope son opcionales.
    """
    # Lectura
    role_detail = RoleSerializer(source="role", read_only=True)
    user_detail = UserSerializer(source="user", read_only=True)

    # Escritura — role acepta UUID
    role         = UUIDRelatedField(model=Role,         required=True)
    # user acepta ID numérico (Django user PK)
    user         = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False
    )
    # Scope opcional — acepta UUID o null
    organization = UUIDRelatedField(model=Organization, required=False)
    legal_entity = UUIDRelatedField(model=LegalEntity,  required=False)
    branch       = UUIDRelatedField(model=Branch,       required=False)

    class Meta:
        model   = UserRoleAssignment
        exclude = ["id", "deleted_at"]
        extra_kwargs = {
            "legal_entity": {"required": False, "allow_null": True},
            "organization": {"required": False, "allow_null": True},
            "branch":       {"required": False, "allow_null": True},
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["role"]         = str(instance.role.uuid)         if instance.role         else None
        data["user"]         = instance.user.id                if instance.user         else None
        data["organization"] = str(instance.organization.uuid) if instance.organization else None
        data["legal_entity"] = str(instance.legal_entity.uuid) if instance.legal_entity else None
        data["branch"]       = str(instance.branch.uuid)       if instance.branch       else None
        return data

    def validate(self, attrs):
        user         = attrs.get("user")         or (self.instance and self.instance.user)
        role         = attrs.get("role")         or (self.instance and self.instance.role)
        organization = attrs.get("organization") or (self.instance and getattr(self.instance, "organization", None))
        legal_entity = attrs.get("legal_entity") or (self.instance and getattr(self.instance, "legal_entity", None))
        branch       = attrs.get("branch")       or (self.instance and getattr(self.instance, "branch", None))

        qs = UserRoleAssignment.objects.filter(
            user=user, role=role,
            organization=organization,
            legal_entity=legal_entity,
            branch=branch,
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Ya existe una asignación de rol para este usuario con el mismo alcance."
            )
        return attrs


# ── Me ────────────────────────────────────────────────────────────────────────

class MeSerializer(serializers.Serializer):
    user    = UserSerializer()
    profile = UserProfileSerializer(allow_null=True)
    roles   = serializers.ListField()
    scopes  = serializers.ListField()
