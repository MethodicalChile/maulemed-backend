from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from apps.common.models import BaseModel
from apps.organizations.models import Branch


# Ajusta este import según dónde tengas BaseModel
# from apps.core.models import BaseModel


class EvaluationForm(BaseModel):
    """
    Plantilla interna de un formulario de evaluación.

    Puede sincronizarse con Google Forms para generar un formulario público
    accesible mediante enlace o código QR.
    """

    TARGET_ALL = "ALL"
    TARGET_BRANCH = "BRANCH"
    TARGET_ROLE = "ROLE"

    TARGET_CHOICES = [
        (TARGET_ALL, "Todos los usuarios"),
        (TARGET_BRANCH, "Sucursal específica"),
        (TARGET_ROLE, "Rol específico"),
    ]

    GOOGLE_STATUS_NOT_SYNCED = "NOT_SYNCED"
    GOOGLE_STATUS_SYNCING = "SYNCING"
    GOOGLE_STATUS_SYNCED = "SYNCED"
    GOOGLE_STATUS_ERROR = "ERROR"

    GOOGLE_SYNC_STATUS_CHOICES = [
        (GOOGLE_STATUS_NOT_SYNCED, "No sincronizado"),
        (GOOGLE_STATUS_SYNCING, "Sincronizando"),
        (GOOGLE_STATUS_SYNCED, "Sincronizado"),
        (GOOGLE_STATUS_ERROR, "Error"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    target_type = models.CharField(
        max_length=20,
        choices=TARGET_CHOICES,
        default=TARGET_ALL,
    )

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_evaluation_forms",
        blank=True,
        null=True,
    )

    # ==========================================================
    # Integración con Google Forms
    # ==========================================================

    google_form_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        help_text="Identificador del formulario generado por Google Forms.",
    )

    google_form_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Enlace público para responder el formulario.",
    )

    google_form_edit_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Enlace de edición del formulario en Google Forms.",
    )

    google_sync_status = models.CharField(
        max_length=20,
        choices=GOOGLE_SYNC_STATUS_CHOICES,
        default=GOOGLE_STATUS_NOT_SYNCED,
    )

    google_sync_error = models.TextField(
        blank=True,
        null=True,
        help_text="Detalle del último error de sincronización.",
    )

    google_synced_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    google_last_response_sync_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Fecha de la última consulta de respuestas en Google Forms.",
    )

    class Meta:
        db_table = "evaluation_forms"
        verbose_name = "Evaluation Form"
        verbose_name_plural = "Evaluation Forms"
        indexes = [
            models.Index(
                fields=["is_active"],
                name="idx_eval_form_active",
            ),
            models.Index(
                fields=["created_at"],
                name="idx_eval_form_created",
            ),
            models.Index(
                fields=["google_sync_status"],
                name="idx_eval_google_status",
            ),
        ]

    @property
    def is_published_in_google(self):
        return bool(
            self.google_form_id
            and self.google_form_url
            and self.google_sync_status == self.GOOGLE_STATUS_SYNCED
        )

    def __str__(self):
        return self.title


class EvaluationFormQuestion(BaseModel):
    """Pregunta perteneciente a un EvaluationForm."""

    TYPE_TEXT = "TEXT"
    TYPE_RATING = "RATING"
    TYPE_MULTIPLE = "MULTIPLE"
    TYPE_SINGLE = "SINGLE"
    TYPE_BOOLEAN = "BOOLEAN"
    TYPE_DATE = "DATE"

    QUESTION_TYPE_CHOICES = [
        (TYPE_TEXT, "Texto libre"),
        (TYPE_RATING, "Puntuación (1–N)"),
        (TYPE_MULTIPLE, "Selección múltiple"),
        (TYPE_SINGLE, "Selección única"),
        (TYPE_BOOLEAN, "Sí / No"),
        (TYPE_DATE, "Fecha"),
    ]

    evaluation_form = models.ForeignKey(
        EvaluationForm,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    order = models.PositiveIntegerField(default=1)

    question_text = models.TextField()

    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPE_CHOICES,
        default=TYPE_TEXT,
    )

    rating_max = models.PositiveIntegerField(
        default=5,
        blank=True,
        null=True,
    )

    options = models.JSONField(
        blank=True,
        null=True,
    )

    is_required = models.BooleanField(default=True)

    helper_text = models.CharField(
        max_length=300,
        blank=True,
        null=True,
    )

    # ==========================================================
    # Relación con la pregunta creada en Google Forms
    # ==========================================================

    google_item_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="ID del ítem asignado por Google Forms.",
    )

    google_question_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="ID usado por Google para identificar las respuestas.",
    )

    class Meta:
        db_table = "evaluation_form_questions"
        verbose_name = "Evaluation Form Question"
        verbose_name_plural = "Evaluation Form Questions"

        ordering = [
            "evaluation_form",
            "order",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "evaluation_form",
                    "order",
                ],
                name="uq_eval_question_order",
            ),
        ]

        indexes = [
            models.Index(
                fields=["evaluation_form", "order"],
                name="idx_eval_question_form_order",
            ),
            models.Index(
                fields=["google_question_id"],
                name="idx_eval_google_question",
            ),
        ]

    def clean(self):
        super().clean()

        if self.question_type in (
            self.TYPE_MULTIPLE,
            self.TYPE_SINGLE,
        ):
            if not self.options or not isinstance(self.options, list):
                raise ValidationError(
                    {
                        "options": (
                            "Las preguntas de selección requieren "
                            "una lista de opciones."
                        )
                    }
                )

            normalized_options = [
                str(option).strip()
                for option in self.options
                if str(option).strip()
            ]

            if len(normalized_options) < 2:
                raise ValidationError(
                    {
                        "options": (
                            "Las preguntas de selección requieren "
                            "al menos dos opciones."
                        )
                    }
                )

            if len(normalized_options) != len(set(normalized_options)):
                raise ValidationError(
                    {
                        "options": (
                            "Las opciones no pueden estar repetidas."
                        )
                    }
                )

        if self.question_type == self.TYPE_RATING:
            if not self.rating_max:
                raise ValidationError(
                    {
                        "rating_max": (
                            "Debe indicar el valor máximo de la puntuación."
                        )
                    }
                )

            if self.rating_max < 2 or self.rating_max > 10:
                raise ValidationError(
                    {
                        "rating_max": (
                            "El valor máximo debe estar entre 2 y 10."
                        )
                    }
                )

    def __str__(self):
        return (
            f"[{self.evaluation_form}] "
            f"#{self.order} "
            f"{self.question_text[:60]}"
        )

# # ──────────────────────────────────────────────────────────────────────────────
# # EvaluationForm  — plantilla del formulario de evaluación
# # ──────────────────────────────────────────────────────────────────────────────

# class EvaluationForm(BaseModel):
#     """
#     Define la plantilla de un formulario de evaluación.
#     Cada formulario tiene un conjunto de preguntas (EvaluationFormQuestion)
#     y puede aplicarse a múltiples usuarios generando UserEvaluation.
#     """

#     TARGET_ALL    = "ALL"
#     TARGET_BRANCH = "BRANCH"
#     TARGET_ROLE   = "ROLE"

#     TARGET_CHOICES = [
#         (TARGET_ALL,    "Todos los usuarios"),
#         (TARGET_BRANCH, "Sucursal específica"),
#         (TARGET_ROLE,   "Rol específico"),
#     ]

#     title       = models.CharField(max_length=200)
#     description = models.TextField(blank=True, null=True)

#     target_type = models.CharField(
#         max_length=20,
#         choices=TARGET_CHOICES,
#         default=TARGET_ALL,
#     )

#     # Cuántos días tiene el usuario para completarla desde que se le asigna
#     # days_to_complete removido — no aplica para el flujo de WhatsApp

#     is_active = models.BooleanField(default=True)

#     created_by = models.ForeignKey(
#         settings.AUTH_USER_MODEL,
#         on_delete=models.SET_NULL,
#         related_name="created_evaluation_forms",
#         blank=True, null=True,
#     )

#     class Meta:
#         db_table = "evaluation_forms"
#         verbose_name = "Evaluation Form"
#         verbose_name_plural = "Evaluation Forms"
#         indexes = [
#             models.Index(fields=["is_active"], name="idx_eval_form_active"),
#             models.Index(fields=["created_at"], name="idx_eval_form_created"),
#         ]

#     def __str__(self):
#         return self.title


# # ──────────────────────────────────────────────────────────────────────────────
# # EvaluationFormQuestion  — preguntas de un formulario
# # ──────────────────────────────────────────────────────────────────────────────

# class EvaluationFormQuestion(BaseModel):
#     """Pregunta perteneciente a un EvaluationForm."""

#     TYPE_TEXT        = "TEXT"
#     TYPE_RATING      = "RATING"       # escala numérica 1–N
#     TYPE_MULTIPLE    = "MULTIPLE"     # selección múltiple (JSON de opciones)
#     TYPE_SINGLE      = "SINGLE"       # selección única (JSON de opciones)
#     TYPE_BOOLEAN     = "BOOLEAN"      # sí / no
#     TYPE_DATE        = "DATE"

#     QUESTION_TYPE_CHOICES = [
#         (TYPE_TEXT,     "Texto libre"),
#         (TYPE_RATING,   "Puntuación (1–N)"),
#         (TYPE_MULTIPLE, "Selección múltiple"),
#         (TYPE_SINGLE,   "Selección única"),
#         (TYPE_BOOLEAN,  "Sí / No"),
#         (TYPE_DATE,     "Fecha"),
#     ]

#     evaluation_form = models.ForeignKey(
#         EvaluationForm,
#         on_delete=models.CASCADE,
#         related_name="questions",
#     )

#     order         = models.PositiveIntegerField(default=1)
#     question_text = models.TextField()
#     question_type = models.CharField(
#         max_length=20,
#         choices=QUESTION_TYPE_CHOICES,
#         default=TYPE_TEXT,
#     )

#     # Para RATING: valor máximo (default 5)
#     rating_max    = models.PositiveIntegerField(default=5, blank=True, null=True)

#     # Para MULTIPLE / SINGLE: JSON array de opciones, ej. ["Nunca","A veces","Siempre"]
#     options       = models.JSONField(blank=True, null=True)

#     is_required   = models.BooleanField(default=True)
#     helper_text   = models.CharField(max_length=300, blank=True, null=True)

#     class Meta:
#         db_table = "evaluation_form_questions"
#         verbose_name = "Evaluation Form Question"
#         verbose_name_plural = "Evaluation Form Questions"
#         ordering = ["evaluation_form", "order"]
#         constraints = [
#             models.UniqueConstraint(
#                 fields=["evaluation_form", "order"],
#                 name="uq_eval_question_order",
#             )
#         ]

#     def clean(self):
#         if self.question_type in (self.TYPE_MULTIPLE, self.TYPE_SINGLE):
#             if not self.options or not isinstance(self.options, list):
#                 raise ValidationError("Las preguntas de selección requieren una lista de opciones.")

#     def __str__(self):
#         return f"[{self.evaluation_form}] #{self.order} {self.question_text[:60]}"


# ──────────────────────────────────────────────────────────────────────────────
# UserEvaluation  — resultado de una evaluación aplicada a un usuario
# ──────────────────────────────────────────────────────────────────────────────

class UserEvaluation(BaseModel):
    """
    Instancia de un EvaluationForm aplicada a un usuario específico.
    Es el 'gancho' entre el formulario y el usuario evaluado.
    Los resultados externos llegan aquí referenciando el evaluation_form por UUID.
    """

    STATUS_PENDING    = "PENDING"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED  = "COMPLETED"
    STATUS_EXPIRED    = "EXPIRED"

    STATUS_CHOICES = [
        (STATUS_PENDING,     "Pendiente"),
        (STATUS_IN_PROGRESS, "En progreso"),
        (STATUS_COMPLETED,   "Completada"),
        (STATUS_EXPIRED,     "Vencida"),
    ]

    evaluation_form = models.ForeignKey(
        EvaluationForm,
        on_delete=models.PROTECT,
        related_name="user_evaluations",
    )
    evaluated_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="evaluations",
        blank=True,
        null=True,
        help_text="Null para respuestas anónimas importadas desde Google Forms.",
    )
    # Quién asignó la evaluación
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_evaluations",
        blank=True, null=True,
    )

    status        = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    # Puede estar acotada a una sucursal específica
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="user_evaluations",
        blank=True, null=True,
    )

    due_date      = models.DateField(blank=True, null=True)
    completed_at  = models.DateTimeField(blank=True, null=True)

    # Puntaje total calculado (sum de RATING / max posible * 100)
    score         = models.DecimalField(
        max_digits=6, decimal_places=2,
        blank=True, null=True,
    )

    # Observaciones del evaluador
    notes         = models.TextField(blank=True, null=True)

    # Origen de la respuesta: 'WEB' | 'EXTERNAL_FORM' | 'IMPORT'
    source        = models.CharField(max_length=50, default="WEB")

    class Meta:
        db_table = "user_evaluations"
        verbose_name = "User Evaluation"
        verbose_name_plural = "User Evaluations"
        indexes = [
            models.Index(fields=["evaluation_form"], name="idx_ueval_form"),
            models.Index(fields=["evaluated_user"],  name="idx_ueval_user"),
            models.Index(fields=["status"],          name="idx_ueval_status"),
            models.Index(fields=["due_date"],        name="idx_ueval_due_date"),
        ]

    def __str__(self):
        return f"{self.evaluation_form} → {self.evaluated_user} [{self.status}]"


# ──────────────────────────────────────────────────────────────────────────────
# UserEvaluationAnswer  — respuestas individuales de una evaluación
# ──────────────────────────────────────────────────────────────────────────────

class UserEvaluationAnswer(BaseModel):
    """Respuesta a una pregunta dentro de una UserEvaluation."""

    user_evaluation = models.ForeignKey(
        UserEvaluation,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        EvaluationFormQuestion,
        on_delete=models.PROTECT,
        related_name="answers",
    )

    # Texto libre / fecha / booleano como string
    answer_text   = models.TextField(blank=True, null=True)
    # Para RATING
    answer_rating = models.PositiveIntegerField(blank=True, null=True)
    # Para MULTIPLE / SINGLE: JSON array de opciones seleccionadas
    answer_options = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "user_evaluation_answers"
        verbose_name = "User Evaluation Answer"
        verbose_name_plural = "User Evaluation Answers"
        constraints = [
            models.UniqueConstraint(
                fields=["user_evaluation", "question"],
                name="uq_ueval_answer",
            )
        ]

    def __str__(self):
        return f"{self.user_evaluation} – Q{self.question.order}"
