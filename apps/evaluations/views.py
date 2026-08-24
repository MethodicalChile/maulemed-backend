import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.viewsets import BaseModelViewSet
from apps.common.permissions import (
    CanManageEvaluations,
    CanManageEvaluationQuestions,
    user_has_permission_key,
)
from apps.common.responses import api_response, api_error

from .models import (
    EvaluationForm,
    EvaluationFormQuestion,
    UserEvaluation,
    UserEvaluationAnswer,
)
from .serializers import (
    EvaluationFormSerializer,
    EvaluationFormSmallSerializer,
    EvaluationFormQuestionSerializer,
    UserEvaluationSerializer,
    UserEvaluationSmallSerializer,
    SubmitEvaluationSerializer,
)
from .services.google_forms_service import GoogleFormsService
from .services.qr_service import QRService

logger = logging.getLogger(__name__)
User = get_user_model()


# ──────────────────────────────────────────────────────────────────────────────
# EvaluationFormViewSet
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# EvaluationFormViewSet
# ──────────────────────────────────────────────────────────────────────────────

class EvaluationFormViewSet(BaseModelViewSet):
    """
    CRUD de plantillas de formulario de evaluación.

    Permisos granulares:
    - list / retrieve / questions / qr / responses_summary
        -> can_view_evaluations
    - create
        -> can_create_evaluations
    - update / partial_update / toggle_active /
      publish_google_form / resync_google_form / sync_responses
        -> can_edit_evaluations
    - destroy
        -> can_delete_evaluations
    """

    queryset = (
        EvaluationForm.objects
        .prefetch_related("questions")
        .order_by("-created_at")
    )
    serializer_class  = EvaluationFormSerializer
    search_fields     = ["title", "description"]
    filterset_fields  = ["is_active", "target_type", "google_sync_status"]
    ordering_fields   = ["title", "created_at", "is_active", "google_synced_at"]

    def get_permissions(self):
        return [
            CanManageEvaluations()
        ]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ── toggle-active ─────────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="toggle-active")
    def toggle_active(self, request, uuid=None):
        """Activa o desactiva el formulario."""
        form = self.get_object()
        form.is_active = not form.is_active
        form.save(update_fields=["is_active", "updated_at"])
        return api_response(
            data=EvaluationFormSmallSerializer(form).data,
            message=f"Formulario {'activado' if form.is_active else 'desactivado'} correctamente.",
        )

    # ── questions ─────────────────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="questions")
    def questions(self, request, uuid=None):
        """Lista las preguntas del formulario en orden."""
        form      = self.get_object()
        questions = form.questions.order_by("order")
        data      = EvaluationFormQuestionSerializer(questions, many=True).data
        return api_response(data=data)

    # ── publish-google-form ───────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="publish-google-form")
    def publish_google_form(self, request, uuid=None):
        """
        Publica el formulario en Google Forms.
        Devuelve 409 si ya tiene un Google Form asociado.
        """
        evaluation_form = self.get_object()

        # Validar que tenga preguntas
        if not evaluation_form.questions.exists():
            return api_error(
                message=(
                    "El formulario debe contener al menos una pregunta "
                    "antes de publicarse en Google Forms."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Evitar duplicados
        if evaluation_form.google_form_id:
            return api_error(
                data={
                    "google_form_id":      evaluation_form.google_form_id,
                    "google_form_url":     evaluation_form.google_form_url,
                    "google_form_edit_url": evaluation_form.google_form_edit_url,
                    "google_sync_status":  evaluation_form.google_sync_status,
                },
                message="El formulario ya se encuentra publicado en Google Forms.",
                status_code=status.HTTP_409_CONFLICT,
            )

        # Validar preguntas antes de llamar a Google
        validation_error = self._validate_google_questions(evaluation_form)
        if validation_error:
            return api_error(
                message=validation_error,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Marcar SYNCING
        evaluation_form.google_sync_status = EvaluationForm.GOOGLE_STATUS_SYNCING
        evaluation_form.google_sync_error  = None
        evaluation_form.save(update_fields=["google_sync_status", "google_sync_error", "updated_at"])

        try:
            result = GoogleFormsService().create_form(evaluation_form)

            with transaction.atomic():
                evaluation_form.google_form_id       = result["google_form_id"]
                evaluation_form.google_form_url      = result["google_form_url"]
                evaluation_form.google_form_edit_url = result["google_form_edit_url"]
                evaluation_form.google_sync_status   = EvaluationForm.GOOGLE_STATUS_SYNCED
                evaluation_form.google_sync_error    = None
                evaluation_form.google_synced_at     = timezone.now()
                evaluation_form.save(update_fields=[
                    "google_form_id",
                    "google_form_url",
                    "google_form_edit_url",
                    "google_sync_status",
                    "google_sync_error",
                    "google_synced_at",
                    "updated_at",
                ])

            return api_response(
                data={
                    "uuid":                str(evaluation_form.uuid),
                    "title":               evaluation_form.title,
                    "google_form_id":      evaluation_form.google_form_id,
                    "google_form_url":     evaluation_form.google_form_url,
                    "google_form_edit_url": evaluation_form.google_form_edit_url,
                    "google_sync_status":  evaluation_form.google_sync_status,
                    "google_synced_at":    evaluation_form.google_synced_at,
                },
                message="Formulario publicado correctamente en Google Forms.",
                status_code=status.HTTP_201_CREATED,
            )

        except Exception as exc:
            logger.exception(
                "Error publicando formulario %s en Google Forms.",
                evaluation_form.uuid,
            )
            evaluation_form.google_sync_status = EvaluationForm.GOOGLE_STATUS_ERROR
            evaluation_form.google_sync_error  = str(exc)
            evaluation_form.save(update_fields=[
                "google_sync_status",
                "google_sync_error",
                "updated_at",
            ])
            return api_error(
                data={
                    "detail":             str(exc),
                    "google_sync_status": evaluation_form.google_sync_status,
                },
                message="No fue posible publicar el formulario en Google Forms.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── qr ────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="qr")
    def qr(self, request, uuid=None):
        """
        Genera y devuelve el QR del formulario como PNG.

        ?download=true  →  Content-Disposition: attachment (descarga)
        (por defecto)   →  Content-Disposition: inline   (visualización)
        """
        evaluation_form = self.get_object()

        if not evaluation_form.google_form_url:
            return api_error(
                message="El formulario aún no tiene URL de Google Forms.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        png_bytes = QRService.generate_png(evaluation_form.google_form_url)

        download = request.GET.get("download", "").lower() in ("1", "true", "yes")
        filename = f"formulario-{evaluation_form.uuid}.png"

        if download:
            disposition = f'attachment; filename="{filename}"'
        else:
            disposition = f'inline; filename="{filename}"'

        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = disposition
        return response

    # ── resync-google-form ────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="resync-google-form")
    def resync_google_form(self, request, uuid=None):
        """
        Re-sincroniza el Google Form con las preguntas actuales del formulario.

        - Requiere que el formulario ya esté publicado (google_form_id presente).
        - Elimina todos los ítems del Google Form y los recrea.
        - Las respuestas ya importadas en MauleMed se conservan.
        - Preguntas nuevas aparecen con null en respuestas anteriores.
        - Actualiza google_sync_status y google_synced_at.
        """
        evaluation_form = self.get_object()

        if not evaluation_form.google_form_id:
            return api_error(
                message="El formulario no está publicado en Google Forms. Usa 'Publicar' primero.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        validation_error = self._validate_google_questions(evaluation_form)
        if validation_error:
            return api_error(
                message=validation_error,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Marcar SYNCING
        evaluation_form.google_sync_status = EvaluationForm.GOOGLE_STATUS_SYNCING
        evaluation_form.google_sync_error  = None
        evaluation_form.save(update_fields=["google_sync_status", "google_sync_error", "updated_at"])

        try:
            result = GoogleFormsService().resync_form(evaluation_form)

            with transaction.atomic():
                evaluation_form.google_form_url      = result["google_form_url"]
                evaluation_form.google_form_edit_url = result["google_form_edit_url"]
                evaluation_form.google_sync_status   = EvaluationForm.GOOGLE_STATUS_SYNCED
                evaluation_form.google_sync_error    = None
                evaluation_form.google_synced_at     = timezone.now()
                evaluation_form.save(update_fields=[
                    "google_form_url",
                    "google_form_edit_url",
                    "google_sync_status",
                    "google_sync_error",
                    "google_synced_at",
                    "updated_at",
                ])

            return api_response(
                data={
                    "uuid":                str(evaluation_form.uuid),
                    "title":               evaluation_form.title,
                    "google_form_id":      evaluation_form.google_form_id,
                    "google_form_url":     evaluation_form.google_form_url,
                    "google_form_edit_url": evaluation_form.google_form_edit_url,
                    "google_sync_status":  evaluation_form.google_sync_status,
                    "google_synced_at":    evaluation_form.google_synced_at,
                },
                message="Formulario re-sincronizado correctamente con Google Forms.",
            )

        except Exception as exc:
            logger.exception(
                "Error re-sincronizando formulario %s con Google Forms.",
                evaluation_form.uuid,
            )
            evaluation_form.google_sync_status = EvaluationForm.GOOGLE_STATUS_ERROR
            evaluation_form.google_sync_error  = str(exc)
            evaluation_form.save(update_fields=[
                "google_sync_status",
                "google_sync_error",
                "updated_at",
            ])
            return api_error(
                data={"detail": str(exc), "google_sync_status": evaluation_form.google_sync_status},
                message="No fue posible re-sincronizar el formulario con Google Forms.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── responses-summary ─────────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="responses-summary")
    def responses_summary(self, request, uuid=None):
        """
        Devuelve un resumen de respuestas agrupadas por pregunta.

        Estructura de respuesta:
        {
          "total_responses": N,
          "google_last_response_sync_at": "...",
          "questions": [
            {
              "order": 1,
              "question_text": "...",
              "question_type": "TEXT",
              "total_answers": N,
              "answers": ["resp1", "resp2", ...]          // TEXT / DATE / BOOLEAN / SINGLE
              // o para RATING:
              "average": 3.5,
              "distribution": {"1": 2, "2": 5, ...}
              // o para MULTIPLE:
              "option_counts": {"Opción A": 3, "Opción B": 7}
            },
            ...
          ]
        }
        """
        evaluation_form = self.get_object()

        questions = list(evaluation_form.questions.order_by("order"))

        # Contar evaluaciones completadas para este formulario
        total_responses = UserEvaluation.objects.filter(
            evaluation_form=evaluation_form,
            status=UserEvaluation.STATUS_COMPLETED,
        ).count()

        question_summaries = []

        for question in questions:
            answers_qs = UserEvaluationAnswer.objects.filter(
                question=question,
                user_evaluation__evaluation_form=evaluation_form,
                user_evaluation__status=UserEvaluation.STATUS_COMPLETED,
            )

            total_answers = answers_qs.count()
            qtype = question.question_type
            summary = {
                "uuid":          str(question.uuid),
                "order":         question.order,
                "question_text": question.question_text,
                "question_type": qtype,
                "total_answers": total_answers,
            }

            if qtype == EvaluationFormQuestion.TYPE_RATING:
                values = [
                    a.answer_rating
                    for a in answers_qs
                    if a.answer_rating is not None
                ]
                avg = round(sum(values) / len(values), 2) if values else None
                dist = {}
                for v in values:
                    dist[str(v)] = dist.get(str(v), 0) + 1
                summary["average"]      = avg
                summary["distribution"] = dist

            elif qtype == EvaluationFormQuestion.TYPE_MULTIPLE:
                counts = {}
                for a in answers_qs:
                    for opt in (a.answer_options or []):
                        counts[opt] = counts.get(opt, 0) + 1
                summary["option_counts"] = counts

            else:
                # TEXT, DATE, SINGLE, BOOLEAN
                texts = [
                    a.answer_options[0] if a.answer_options else a.answer_text
                    for a in answers_qs
                    if a.answer_text or a.answer_options
                ]
                # Para SINGLE/BOOLEAN también contar por opción
                if qtype in (
                    EvaluationFormQuestion.TYPE_SINGLE,
                    EvaluationFormQuestion.TYPE_BOOLEAN,
                ):
                    counts = {}
                    for t in texts:
                        if t:
                            counts[t] = counts.get(t, 0) + 1
                    summary["option_counts"] = counts
                summary["answers"] = [t for t in texts if t]

            question_summaries.append(summary)

        return api_response(
            data={
                "total_responses":               total_responses,
                "google_last_response_sync_at":  evaluation_form.google_last_response_sync_at,
                "questions":                     question_summaries,
            },
            message="Resumen de respuestas obtenido correctamente.",
        )

    # ── sync-responses ────────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="sync-responses")
    def sync_responses(self, request, uuid=None):
        """
        Importa todas las respuestas de Google Forms como UserEvaluation.

        - Solo funciona si el formulario está publicado (google_form_id presente).
        - Respuestas ya importadas (mismo google_response_id) se omiten.
        - Las respuestas se crean con source='EXTERNAL_FORM' y status=COMPLETED.
        - El usuario evaluado queda en None (respuestas anónimas de Google Forms).
        - Actualiza google_last_response_sync_at.
        - Devuelve cuántas respuestas se importaron y cuántas ya existían.
        """
        evaluation_form = self.get_object()

        if not evaluation_form.google_form_id:
            return api_error(
                message="El formulario no está publicado en Google Forms.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service   = GoogleFormsService()
            responses = service.fetch_responses(evaluation_form.google_form_id)
        except Exception as exc:
            logger.exception(
                "Error obteniendo respuestas de Google Forms para form %s",
                evaluation_form.uuid,
            )
            return api_error(
                message=f"No se pudo conectar con Google Forms: {exc}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Mapa google_question_id → EvaluationFormQuestion
        question_map = {
            q.google_question_id: q
            for q in evaluation_form.questions.all()
            if q.google_question_id
        }

        # IDs de respuestas ya importadas para este formulario
        existing_ids = set(
            UserEvaluation.objects
            .filter(
                evaluation_form=evaluation_form,
                source="EXTERNAL_FORM",
            )
            .exclude(notes__isnull=True)
            .values_list("notes", flat=True)
        )

        imported = 0
        skipped  = 0

        for gresponse in responses:
            response_id = gresponse.get("responseId", "")

            # Usar notes como campo para almacenar el google_response_id
            marker = f"google_response_id:{response_id}"

            if marker in existing_ids:
                skipped += 1
                continue

            raw_answers = gresponse.get("answers", {})

            # Calcular score RATING
            rating_sum = 0
            rating_max_total = 0

            answer_rows = []
            for q_id, answer_data in raw_answers.items():
                question = question_map.get(q_id)
                if not question:
                    continue

                text_val    = None
                rating_val  = None
                options_val = None

                qtype = question.question_type

                if qtype == EvaluationFormQuestion.TYPE_RATING:
                    scale = answer_data.get("scaleAnswer", {})
                    rating_val = scale.get("value")
                    if rating_val is not None:
                        rating_sum       += int(rating_val)
                        rating_max_total += (question.rating_max or 5)

                elif qtype == EvaluationFormQuestion.TYPE_DATE:
                    date_ans = answer_data.get("dateAnswer", {})
                    y = date_ans.get("year", "")
                    m = str(date_ans.get("month", "")).zfill(2)
                    d = str(date_ans.get("day",   "")).zfill(2)
                    if y:
                        text_val = f"{y}-{m}-{d}"

                elif qtype in (
                    EvaluationFormQuestion.TYPE_SINGLE,
                    EvaluationFormQuestion.TYPE_BOOLEAN,
                ):
                    texts = answer_data.get("textAnswers", {}).get("answers", [])
                    text_val = texts[0].get("value") if texts else None

                elif qtype == EvaluationFormQuestion.TYPE_MULTIPLE:
                    texts = answer_data.get("textAnswers", {}).get("answers", [])
                    options_val = [a.get("value") for a in texts if a.get("value")]

                else:  # TYPE_TEXT y cualquier otro
                    texts = answer_data.get("textAnswers", {}).get("answers", [])
                    text_val = texts[0].get("value") if texts else None

                answer_rows.append({
                    "question":      question,
                    "answer_text":   text_val,
                    "answer_rating": rating_val,
                    "answer_options": options_val,
                })

            score = None
            if rating_max_total > 0:
                score = round((rating_sum / rating_max_total) * 100, 2)

            submitted_at_str = (
                gresponse.get("lastSubmittedTime")
                or gresponse.get("createTime")
            )

            with transaction.atomic():
                eval_instance = UserEvaluation.objects.create(
                    evaluation_form=evaluation_form,
                    evaluated_user=None,      # respuestas anónimas de Google Forms
                    status=UserEvaluation.STATUS_COMPLETED,
                    source="EXTERNAL_FORM",
                    score=score,
                    completed_at=timezone.now(),
                    notes=marker,             # almacena el google_response_id para deduplicar
                )

                for row in answer_rows:
                    UserEvaluationAnswer.objects.create(
                        user_evaluation=eval_instance,
                        question=row["question"],
                        answer_text=row["answer_text"],
                        answer_rating=row["answer_rating"],
                        answer_options=row["answer_options"],
                    )

            imported += 1

        # Actualizar timestamp de última sincronización
        evaluation_form.google_last_response_sync_at = timezone.now()
        evaluation_form.save(update_fields=["google_last_response_sync_at", "updated_at"])

        return api_response(
            data={
                "imported": imported,
                "skipped":  skipped,
                "total":    len(responses),
                "google_last_response_sync_at": evaluation_form.google_last_response_sync_at,
            },
            message=(
                f"Sincronización completada: {imported} respuestas importadas, "
                f"{skipped} ya existían."
            ),
        )

    # ── helper de validación ──────────────────────────────────────────────────

    def _validate_google_questions(self, evaluation_form: EvaluationForm):
        """
        Valida todas las preguntas antes de enviarlas a Google Forms.
        Devuelve el primer mensaje de error encontrado, o None si todo está bien.
        """
        supported_types = {
            EvaluationFormQuestion.TYPE_TEXT,
            EvaluationFormQuestion.TYPE_RATING,
            EvaluationFormQuestion.TYPE_MULTIPLE,
            EvaluationFormQuestion.TYPE_SINGLE,
            EvaluationFormQuestion.TYPE_BOOLEAN,
            EvaluationFormQuestion.TYPE_DATE,
        }

        for question in evaluation_form.questions.order_by("order"):
            if not (question.question_text or "").strip():
                return f"La pregunta #{question.order} no tiene un texto válido."

            if question.question_type not in supported_types:
                return (
                    f"El tipo de la pregunta #{question.order} "
                    f"no está soportado: {question.question_type}."
                )

            if question.question_type in (
                EvaluationFormQuestion.TYPE_SINGLE,
                EvaluationFormQuestion.TYPE_MULTIPLE,
            ):
                if not isinstance(question.options, list):
                    return f"La pregunta #{question.order} debe tener una lista de opciones."

                clean = [str(o).strip() for o in question.options if str(o).strip()]
                if len(clean) < 2:
                    return f"La pregunta #{question.order} debe tener al menos dos opciones válidas."
                if len(clean) != len(set(clean)):
                    return f"La pregunta #{question.order} contiene opciones repetidas."

            if question.question_type == EvaluationFormQuestion.TYPE_RATING:
                if question.rating_max is None:
                    return f"La pregunta #{question.order} debe indicar el valor máximo de la escala."
                if question.rating_max < 2 or question.rating_max > 10:
                    return f"La escala de la pregunta #{question.order} debe estar entre 2 y 10."

        return None

# ──────────────────────────────────────────────────────────────────────────────
# EvaluationFormQuestionViewSet
# ──────────────────────────────────────────────────────────────────────────────

class EvaluationFormQuestionViewSet(BaseModelViewSet):
    """
    CRUD de preguntas de formularios.

    Permisos:
    - GET          -> can_view_evaluations
    - POST         -> can_create_evaluations
    - PUT / PATCH  -> can_edit_evaluations
    - DELETE       -> can_delete_evaluations
    """

    queryset = (
        EvaluationFormQuestion.objects
        .select_related(
            "evaluation_form"
        )
        .order_by(
            "evaluation_form",
            "order",
        )
    )

    serializer_class = (
        EvaluationFormQuestionSerializer
    )

    filterset_fields = [
        "evaluation_form__uuid",
        "question_type",
        "is_required",
    ]

    ordering_fields = [
        "order",
        "created_at",
    ]

    def get_permissions(self):
        return [
            CanManageEvaluationQuestions()
        ]


# ──────────────────────────────────────────────────────────────────────────────
# UserEvaluationViewSet
# ──────────────────────────────────────────────────────────────────────────────

class UserEvaluationViewSet(BaseModelViewSet):
    """
    Gestión de evaluaciones asignadas a usuarios.

    Permisos administrativos:

    - list / retrieve
        -> can_view_evaluations

    - create
        -> can_create_evaluations

    - update / partial_update
        -> can_edit_evaluations

    - destroy
        -> can_delete_evaluations

    Acciones personales:

    - my_evaluations
        -> cualquier usuario autenticado puede
           consultar sus propias evaluaciones.

    - submit
        -> cualquier usuario autenticado puede
           responder únicamente sus propias
           evaluaciones.

    El queryset garantiza que un usuario que no tenga
    can_view_evaluations solo pueda acceder a registros
    donde evaluated_user sea él mismo.
    """

    serializer_class = UserEvaluationSerializer

    filterset_fields = [
        "status",
        "evaluation_form__uuid",
        "evaluated_user",
        "source",
        "branch__uuid",
    ]

    search_fields = [
        "evaluated_user__username",
        "evaluated_user__first_name",
        "evaluation_form__title",
    ]

    ordering_fields = [
        "created_at",
        "due_date",
        "score",
        "status",
    ]

    ordering = [
        "-created_at"
    ]

    # =========================================================
    # QUERYSET
    # =========================================================

    def get_queryset(self):
        user = self.request.user

        qs = (
            UserEvaluation.objects
            .select_related(
                "evaluation_form",
                "evaluated_user",
                "assigned_by",
                "branch",
            )
            .prefetch_related(
                "answers__question"
            )
        )

        can_view_all = (
            user_has_permission_key(
                user,
                "can_view_evaluations",
            )
        )

        if not can_view_all:
            """
            Un usuario sin permiso administrativo
            solamente puede acceder a sus propias
            evaluaciones.

            Esto también protege retrieve y submit,
            porque self.get_object() trabaja sobre
            este queryset.
            """
            qs = qs.filter(
                evaluated_user=user
            )

        return qs.order_by(
            "-created_at"
        )

    # =========================================================
    # PERMISOS
    # =========================================================

    def get_permissions(self):
        """
        my_evaluations y submit son acciones personales.

        No requieren can_view_evaluations ni
        can_edit_evaluations porque responder una
        evaluación propia no equivale a administrar
        el módulo.
        """

        if self.action in (
            "my_evaluations",
            "submit",
        ):
            return [
                IsAuthenticated()
            ]

        return [
            CanManageEvaluations()
        ]

    # =========================================================
    # CREATE
    # =========================================================

    def perform_create(
        self,
        serializer,
    ):
        serializer.save(
            assigned_by=self.request.user
        )

    # =========================================================
    # MIS EVALUACIONES
    # =========================================================

    @action(
        detail=False,
        methods=["get"],
        url_path="my",
    )
    def my_evaluations(
        self,
        request,
    ):
        """
        Devuelve únicamente las evaluaciones
        asignadas al usuario autenticado.
        """

        qs = (
            UserEvaluation.objects
            .filter(
                evaluated_user=request.user
            )
            .select_related(
                "evaluation_form"
            )
            .order_by(
                "-created_at"
            )
        )

        data = (
            UserEvaluationSmallSerializer(
                qs,
                many=True,
            ).data
        )

        return api_response(
            data=data
        )

    # =========================================================
    # RESPONDER EVALUACIÓN PROPIA
    # =========================================================

    @action(
        detail=True,
        methods=["post"],
        url_path="submit",
    )
    def submit(
        self,
        request,
        uuid=None,
    ):
        """
        Envía las respuestas de una evaluación
        perteneciente al usuario autenticado.

        Calcula automáticamente el score para
        preguntas de tipo RATING.
        """

        evaluation = self.get_object()

        if (
            evaluation.status
            == UserEvaluation.STATUS_COMPLETED
        ):
            return api_error(
                message=(
                    "Esta evaluación "
                    "ya fue completada."
                ),
                status_code=400,
            )

        serializer = (
            SubmitEvaluationSerializer(
                data=request.data
            )
        )

        if not serializer.is_valid():
            return api_error(
                data=serializer.errors,
                message="Datos inválidos.",
            )

        answers_data = (
            serializer.validated_data[
                "answers"
            ]
        )

        notes = (
            serializer.validated_data.get(
                "notes"
            )
        )

        questions = {
            str(q.uuid): q
            for q
            in evaluation
            .evaluation_form
            .questions
            .all()
        }

        rating_sum = 0
        rating_max = 0

        for answer in answers_data:
            question_uuid = str(
                answer[
                    "question"
                ]
            )

            if (
                question_uuid
                not in questions
            ):
                return api_error(
                    message=(
                        f"La pregunta "
                        f"{question_uuid} "
                        f"no pertenece a este "
                        f"formulario."
                    ),
                    status_code=400,
                )

            question = questions[
                question_uuid
            ]

            if (
                question.question_type
                == "RATING"
                and answer.get(
                    "answer_rating"
                )
                is not None
            ):
                rating_sum += (
                    answer[
                        "answer_rating"
                    ]
                )

                rating_max += (
                    question.rating_max
                    or 5
                )

            UserEvaluationAnswer.objects.update_or_create(
                user_evaluation=evaluation,
                question=question,
                defaults={
                    "answer_text": (
                        answer.get(
                            "answer_text"
                        )
                    ),
                    "answer_rating": (
                        answer.get(
                            "answer_rating"
                        )
                    ),
                    "answer_options": (
                        answer.get(
                            "answer_options"
                        )
                    ),
                },
            )

        score = None

        if rating_max > 0:
            score = round(
                (
                    rating_sum
                    / rating_max
                )
                * 100,
                2,
            )

        evaluation.status = (
            UserEvaluation.STATUS_COMPLETED
        )

        evaluation.completed_at = (
            timezone.now()
        )

        evaluation.score = score

        if notes:
            evaluation.notes = notes

        evaluation.save(
            update_fields=[
                "status",
                "completed_at",
                "score",
                "notes",
            ]
        )

        logger.info(
            (
                "Evaluación completada "
                "uuid=%s usuario=%s "
                "score=%s"
            ),
            evaluation.uuid,
            evaluation.evaluated_user,
            score,
        )

        return api_response(
            data=UserEvaluationSerializer(
                evaluation
            ).data,
            message=(
                "Evaluación completada "
                "correctamente."
            ),
        )