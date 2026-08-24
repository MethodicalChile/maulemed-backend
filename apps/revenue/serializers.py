from rest_framework import serializers

from apps.organizations.serializers import (
    LegalEntitySmallSerializer,
    BranchSmallSerializer,
)

from .models import (
    Financier,
    FinancierAlias,
    RevenueEntry,
    RevenueImportBatch,
)


class FinancierSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Financier
        fields = ["uuid", "code", "name", "financier_type"]


class FinancierSerializer(serializers.ModelSerializer):
    financier_type_label = serializers.CharField(
        source="get_financier_type_display", read_only=True
    )
    alias_count = serializers.IntegerField(source="aliases.count", read_only=True)

    class Meta:
        model = Financier
        exclude = ["id", "deleted_at"]


class FinancierAliasSerializer(serializers.ModelSerializer):
    financier_detail = FinancierSmallSerializer(source="financier", read_only=True)

    class Meta:
        model = FinancierAlias
        exclude = ["id", "deleted_at"]


class RevenueEntrySerializer(serializers.ModelSerializer):
    legal_entity_detail = LegalEntitySmallSerializer(
        source="legal_entity", read_only=True
    )
    branch_detail = BranchSmallSerializer(source="branch", read_only=True)
    financier_detail = FinancierSmallSerializer(source="financier", read_only=True)

    class Meta:
        model = RevenueEntry
        exclude = ["id", "deleted_at"]


class RevenueImportBatchSerializer(serializers.ModelSerializer):
    imported_by_username = serializers.CharField(
        source="imported_by.username", read_only=True
    )
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = RevenueImportBatch
        exclude = ["id", "deleted_at"]
