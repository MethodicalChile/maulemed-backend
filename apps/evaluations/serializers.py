from rest_framework import serializers
from django.contrib.auth import get_user_model

from apps.accounts.serializers import UserSerializer
from apps.organizations.serializers import BranchSmallSerializer

from .models import EvaluationForm, EvaluationFormQuestion, UserEvaluation, UserEvaluationAnswer

User = get_user_model()


# ── Questions ─────────────────────────────────────────────────────────────────

class EvaluationFormQuestionSerializer(serializers.ModelSerializer):
    # Acepta el UUID del formulario en escritura (el frontend envía UUID, no ID numérico)
    evaluation_form = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=EvaluationForm.objects.all(),
    )

    class Meta:
        model            = EvaluationFormQuestion
        exclude          = ["id", "deleted_at"]
        read_only_fields = ["uuid", "google_item_id", "google_question_id"]


class EvaluationFormQuestionSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model  = EvaluationFormQuestion
        fields = [
            "uuid", "order", "question_text", "question_type",
            "rating_max", "options", "is_required",
        ]


# ── Forms ─────────────────────────────────────────────────────────────────────

class EvaluationFormSmallSerializer(serializers.ModelSerializer):
    question_count         = serializers.SerializerMethodField()
    is_published_in_google = serializers.BooleanField(read_only=True)

    class Meta:
        model = EvaluationForm
        fields = [
            "uuid",
            "title",
            "is_active",
            "target_type",
            "question_count",
            # Google Forms
            "google_form_id",
            "google_form_url",
            "google_form_edit_url",
            "google_sync_status",
            "google_sync_error",
            "google_synced_at",
            "is_published_in_google",
        ]
        read_only_fields = [
            "uuid",
            "question_count",
            "google_form_id",
            "google_form_url",
            "google_form_edit_url",
            "google_sync_status",
            "google_sync_error",
            "google_synced_at",
            "is_published_in_google",
        ]

    def get_question_count(self, obj):
        questions = obj.questions.all()
        # Aprovechar el prefetch cache si está disponible — evita N+1 en listados
        if hasattr(questions, "_result_cache") and questions._result_cache is not None:
            return len(questions._result_cache)
        return questions.count()


class EvaluationFormSerializer(serializers.ModelSerializer):
    questions              = EvaluationFormQuestionSerializer(many=True, read_only=True)
    is_published_in_google = serializers.BooleanField(read_only=True)

    class Meta:
        model = EvaluationForm
        fields = [
            "uuid",
            "title",
            "description",
            "target_type",
            "is_active",
            "created_by",
            "questions",
            # Google Forms
            "google_form_id",
            "google_form_url",
            "google_form_edit_url",
            "google_sync_status",
            "google_sync_error",
            "google_synced_at",
            "google_last_response_sync_at",
            "is_published_in_google",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uuid",
            "created_by",
            "google_form_id",
            "google_form_url",
            "google_form_edit_url",
            "google_sync_status",
            "google_sync_error",
            "google_synced_at",
            "google_last_response_sync_at",
            "is_published_in_google",
            "created_at",
            "updated_at",
        ]


# ── User Evaluations ──────────────────────────────────────────────────────────

class UserEvaluationAnswerSerializer(serializers.ModelSerializer):
    question_detail = EvaluationFormQuestionSmallSerializer(source="question", read_only=True)

    class Meta:
        model   = UserEvaluationAnswer
        exclude = ["id", "deleted_at"]


class UserEvaluationSmallSerializer(serializers.ModelSerializer):
    evaluation_form_detail = EvaluationFormSmallSerializer(source="evaluation_form", read_only=True)
    evaluated_user_detail  = UserSerializer(source="evaluated_user", read_only=True)

    class Meta:
        model  = UserEvaluation
        fields = [
            "uuid", "status", "score", "due_date",
            "completed_at", "source",
            "evaluation_form_detail", "evaluated_user_detail",
        ]


class UserEvaluationSerializer(serializers.ModelSerializer):
    evaluation_form_detail = EvaluationFormSmallSerializer(source="evaluation_form", read_only=True)
    evaluated_user_detail  = UserSerializer(source="evaluated_user", read_only=True)
    assigned_by_detail     = UserSerializer(source="assigned_by",    read_only=True)
    branch_detail          = BranchSmallSerializer(source="branch",  read_only=True)
    answers                = UserEvaluationAnswerSerializer(many=True, read_only=True)

    class Meta:
        model   = UserEvaluation
        exclude = ["id", "deleted_at"]


# ── Submit answers ────────────────────────────────────────────────────────────

class SubmitAnswerSerializer(serializers.Serializer):
    question       = serializers.UUIDField()
    answer_text    = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    answer_rating  = serializers.IntegerField(required=False, allow_null=True)
    answer_options = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True,
    )


class SubmitEvaluationSerializer(serializers.Serializer):
    answers = SubmitAnswerSerializer(many=True)
    notes   = serializers.CharField(required=False, allow_blank=True, allow_null=True)
