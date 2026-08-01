from rest_framework import serializers

from .models import Organization, LegalEntity, Branch, CostCenter


class OrganizationSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["uuid", "name", "rut"]


class LegalEntitySmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalEntity
        fields = ["uuid", "name", "rut"]


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
        exclude = ["id", "deleted_at"]


class LegalEntitySerializer(serializers.ModelSerializer):
    organization_detail = OrganizationSmallSerializer(source="organization", read_only=True)

    class Meta:
        model = LegalEntity
        exclude = ["id", "deleted_at"]


class BranchSerializer(serializers.ModelSerializer):
    organization_detail = OrganizationSmallSerializer(source="organization", read_only=True)
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)

    class Meta:
        model = Branch
        exclude = ["id", "deleted_at"]


class CostCenterSerializer(serializers.ModelSerializer):
    legal_entity_detail = LegalEntitySmallSerializer(source="legal_entity", read_only=True)
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)

    class Meta:
        model = CostCenter
        exclude = ["id", "deleted_at"]
