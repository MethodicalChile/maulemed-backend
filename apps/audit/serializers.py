from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source="user", read_only=True)

    class Meta:
        model = AuditLog
        exclude = ["id", "deleted_at"]
