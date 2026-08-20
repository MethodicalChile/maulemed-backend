from rest_framework import serializers

from .models import Organization, LegalEntity, Branch, CostCenter


class OrganizationSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "uuid", "name", "rut"]


class LegalEntitySmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalEntity
        fields = ["id", "uuid", "name", "rut"]


class BranchSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["uuid", "name", "code", "city"]


class CostCenterSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostCenter
        fields = ["uuid", "code", "name"]


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        exclude = ["deleted_at"]


class LegalEntitySerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all())
    organization_detail = OrganizationSmallSerializer(source="organization", read_only=True)

    class Meta:
        model = LegalEntity
        exclude = ["deleted_at"]


class BranchSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all())
    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.all(), allow_null=True, required=False)
    organization_detail = OrganizationSmallSerializer(source="organization", read_only=True)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)

    class Meta:
        model = Branch
        exclude = ["deleted_at"]


class CostCenterSerializer(serializers.ModelSerializer):
    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.all())
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all(), allow_null=True, required=False)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)

    class Meta:
        model = CostCenter
        exclude = ["deleted_at"]
