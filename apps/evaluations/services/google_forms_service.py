"""
apps/evaluations/services/google_forms_service.py

Servicio para crear y gestionar formularios en Google Forms a partir de
las plantillas internas EvaluationForm.

RIESGO DOCUMENTADO — Formulario huérfano:
Si Google crea el formulario exitosamente pero el guardado en la base de
datos falla a continuación, quedará un formulario activo en Google Forms
sin registro interno. En ese caso se intenta eliminarlo via Drive API;
si esa llamada también falla, se registra el form_id en el log de error
para que un administrador lo elimine manualmente desde Google Drive.
"""
import logging
from typing import Any

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from apps.evaluations.models import (
    EvaluationForm,
    EvaluationFormQuestion,
)

logger = logging.getLogger(__name__)


class GoogleFormsService:
    SCOPES = [
        "https://www.googleapis.com/auth/forms.body",
        "https://www.googleapis.com/auth/forms.responses.readonly",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def __init__(self):
        self._validate_config()

        self.credentials = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=self.SCOPES,
        )

        self.forms_service = build(
            "forms",
            "v1",
            credentials=self.credentials,
            cache_discovery=False,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Validación de configuración
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_config() -> None:
        """
        Verifica que las variables de entorno necesarias estén configuradas.
        Levanta un error claro indicando el nombre de la variable faltante.
        """
        required = {
            "GOOGLE_CLIENT_ID":     getattr(settings, "GOOGLE_CLIENT_ID", ""),
            "GOOGLE_CLIENT_SECRET": getattr(settings, "GOOGLE_CLIENT_SECRET", ""),
            "GOOGLE_REFRESH_TOKEN": getattr(settings, "GOOGLE_REFRESH_TOKEN", ""),
        }
        for name, value in required.items():
            if not value:
                raise EnvironmentError(
                    f"La variable de entorno '{name}' es obligatoria para "
                    f"la integración con Google Forms y no está configurada."
                )

    # ──────────────────────────────────────────────────────────────────────────
    # Método principal
    # ──────────────────────────────────────────────────────────────────────────

    def create_form(
        self,
        evaluation_form: EvaluationForm,
    ) -> dict[str, Any]:
        """
        Crea el formulario en Google Forms y actualiza los IDs locales.

        Returns
        -------
        dict con:
            google_form_id       — ID asignado por Google
            google_form_url      — URL pública para responder
            google_form_edit_url — URL de edición
        """
        # 1. Crear el formulario vacío
        created_form = (
            self.forms_service.forms()
            .create(
                body={
                    "info": {
                        "title": evaluation_form.title,
                        "documentTitle": evaluation_form.title,
                    }
                }
            )
            .execute()
        )

        google_form_id = created_form["formId"]

        # 2. Añadir descripción y preguntas con batchUpdate
        requests = self._build_form_requests(evaluation_form)

        try:
            batch_response = (
                self.forms_service.forms()
                .batchUpdate(
                    formId=google_form_id,
                    body={
                        "includeFormInResponse": True,
                        "requests": requests,
                    },
                )
                .execute()
            )
        except Exception as exc:
            # El formulario se creó en Google pero el batchUpdate falló.
            # Intentamos eliminarlo para no dejar un formulario huérfano.
            logger.error(
                "batchUpdate falló para form_id=%s. "
                "Intentando eliminar el formulario huérfano. Error: %s",
                google_form_id,
                exc,
            )
            self._try_delete_orphan_form(google_form_id)
            raise

        # 3. Guardar IDs de preguntas en la BD local
        self._save_google_question_ids(
            evaluation_form=evaluation_form,
            batch_response=batch_response,
        )

        # 4. Preferir responderUri devuelto por Google; usar fallback si no viene
        responder_uri = (
            batch_response.get("form", {}).get("responderUri")
            or f"https://docs.google.com/forms/d/{google_form_id}/viewform"
        )

        return {
            "google_form_id":       google_form_id,
            "google_form_url":      responder_uri,
            "google_form_edit_url": (
                f"https://docs.google.com/forms/d/{google_form_id}/edit"
            ),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Construcción del batchUpdate
    # ──────────────────────────────────────────────────────────────────────────

    def _build_form_requests(
        self,
        evaluation_form: EvaluationForm,
    ) -> list[dict[str, Any]]:
        requests = []

        if evaluation_form.description:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {
                            "description": evaluation_form.description,
                        },
                        "updateMask": "description",
                    }
                }
            )

        questions = evaluation_form.questions.order_by("order")

        for index, question in enumerate(questions):
            requests.append(
                {
                    "createItem": {
                        "item": self._build_question_item(question),
                        "location": {
                            "index": index,
                        },
                    }
                }
            )

        return requests

    def _build_question_item(
        self,
        question: EvaluationFormQuestion,
    ) -> dict[str, Any]:
        google_question: dict[str, Any] = {
            "required": question.is_required,
        }

        qtype = question.question_type

        if qtype == EvaluationFormQuestion.TYPE_TEXT:
            google_question["textQuestion"] = {"paragraph": True}

        elif qtype == EvaluationFormQuestion.TYPE_RATING:
            rating_max = question.rating_max or 5
            google_question["scaleQuestion"] = {
                "low":       1,
                "high":      rating_max,
                "lowLabel":  "1",
                "highLabel": str(rating_max),
            }

        elif qtype == EvaluationFormQuestion.TYPE_SINGLE:
            google_question["choiceQuestion"] = {
                "type":    "RADIO",
                "options": [
                    {"value": str(opt)} for opt in (question.options or [])
                ],
                "shuffle": False,
            }

        elif qtype == EvaluationFormQuestion.TYPE_MULTIPLE:
            google_question["choiceQuestion"] = {
                "type":    "CHECKBOX",
                "options": [
                    {"value": str(opt)} for opt in (question.options or [])
                ],
                "shuffle": False,
            }

        elif qtype == EvaluationFormQuestion.TYPE_BOOLEAN:
            google_question["choiceQuestion"] = {
                "type":    "RADIO",
                "options": [{"value": "Sí"}, {"value": "No"}],
                "shuffle": False,
            }

        elif qtype == EvaluationFormQuestion.TYPE_DATE:
            google_question["dateQuestion"] = {
                "includeTime": False,
                "includeYear": True,
            }

        else:
            raise ValueError(
                f"Tipo de pregunta no soportado: {qtype}"
            )

        item: dict[str, Any] = {
            "title": question.question_text,
            "questionItem": {
                "question": google_question,
            },
        }

        if question.helper_text:
            item["description"] = question.helper_text

        return item

    # ──────────────────────────────────────────────────────────────────────────
    # Persistencia de IDs de preguntas
    # ──────────────────────────────────────────────────────────────────────────

    def _save_google_question_ids(
        self,
        evaluation_form: EvaluationForm,
        batch_response: dict,
    ) -> None:
        """
        Lee los IDs de ítems y preguntas desde batch_response["form"]["items"]
        y los persiste en cada EvaluationFormQuestion.
        """
        questions = list(
            evaluation_form.questions.order_by("order")
        )

        google_items = (
            batch_response
            .get("form", {})
            .get("items", [])
        )

        # Filtrar solo ítems que contienen questionItem
        question_items = [
            item for item in google_items if item.get("questionItem")
        ]

        for question, google_item in zip(questions, question_items):
            google_question = (
                google_item
                .get("questionItem", {})
                .get("question", {})
            )

            question.google_item_id     = google_item.get("itemId")
            question.google_question_id = google_question.get("questionId")

            question.save(
                update_fields=[
                    "google_item_id",
                    "google_question_id",
                    "updated_at",
                ]
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Re-sincronización del formulario con Google Forms
    # ──────────────────────────────────────────────────────────────────────────

    def resync_form(self, evaluation_form: EvaluationForm) -> dict[str, Any]:
        """
        Re-sincroniza un formulario ya publicado en Google Forms.

        Estrategia:
        1. Obtener todos los ítems actuales del Google Form.
        2. Eliminarlos todos con deleteItem.
        3. Recrear las preguntas desde cero con createItem.
        4. Actualizar google_item_id y google_question_id en cada pregunta local.
        5. Actualizar título y descripción si cambiaron.

        Las respuestas ya importadas en MauleMed no se tocan.
        Las preguntas nuevas aparecerán con null en respuestas previas
        (no existe UserEvaluationAnswer para esa combinación).
        """
        google_form_id = evaluation_form.google_form_id
        if not google_form_id:
            raise ValueError("El formulario no tiene google_form_id.")

        # 1. Obtener ítems actuales
        current_form = (
            self.forms_service.forms()
            .get(formId=google_form_id)
            .execute()
        )
        current_items = current_form.get("items", [])

        requests: list[dict] = []

        # 2. Eliminar todos los ítems existentes (en orden inverso para no afectar índices)
        for item in reversed(current_items):
            requests.append({
                "deleteItem": {
                    "location": {"index": current_items.index(item)}
                }
            })

        # 3. Actualizar info (título y descripción)
        requests.append({
            "updateFormInfo": {
                "info": {
                    "title":       evaluation_form.title,
                    "description": evaluation_form.description or "",
                },
                "updateMask": "title,description",
            }
        })

        # 4. Crear nuevas preguntas
        questions = evaluation_form.questions.order_by("order")
        for index, question in enumerate(questions):
            requests.append({
                "createItem": {
                    "item": self._build_question_item(question),
                    "location": {"index": index},
                }
            })

        batch_response = (
            self.forms_service.forms()
            .batchUpdate(
                formId=google_form_id,
                body={
                    "includeFormInResponse": True,
                    "requests": requests,
                },
            )
            .execute()
        )

        # 5. Actualizar IDs locales de preguntas
        self._save_google_question_ids(
            evaluation_form=evaluation_form,
            batch_response=batch_response,
        )

        responder_uri = (
            batch_response.get("form", {}).get("responderUri")
            or f"https://docs.google.com/forms/d/{google_form_id}/viewform"
        )

        return {
            "google_form_id":       google_form_id,
            "google_form_url":      responder_uri,
            "google_form_edit_url": f"https://docs.google.com/forms/d/{google_form_id}/edit",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Importación de respuestas desde Google Forms
    # ──────────────────────────────────────────────────────────────────────────

    def fetch_responses(self, google_form_id: str) -> list[dict]:
        """
        Obtiene todas las respuestas del formulario de Google Forms.

        Returns
        -------
        list de dicts con estructura de Google Forms Response:
          {
            "responseId": "...",
            "createTime": "...",
            "lastSubmittedTime": "...",
            "answers": {
              "<questionId>": {
                "questionId": "...",
                "textAnswers": {"answers": [{"value": "..."}]},
                "scaleAnswer": {"value": N},
                ...
              }
            }
          }
        """
        result = (
            self.forms_service.forms()
            .responses()
            .list(formId=google_form_id)
            .execute()
        )
        return result.get("responses", [])

    def _try_delete_orphan_form(self, google_form_id: str) -> None:
        """
        Intenta eliminar un formulario de Google Drive cuando la sincronización
        falló después de crearlo. Si falla, registra el ID para limpieza manual.
        """
        try:
            drive_service = build(
                "drive",
                "v3",
                credentials=self.credentials,
                cache_discovery=False,
            )
            drive_service.files().delete(fileId=google_form_id).execute()
            logger.info(
                "Formulario huérfano eliminado de Google Drive: form_id=%s",
                google_form_id,
            )
        except Exception as delete_exc:
            logger.error(
                "No se pudo eliminar el formulario huérfano de Google Drive. "
                "form_id=%s — eliminarlo manualmente desde Google Drive. Error: %s",
                google_form_id,
                delete_exc,
            )
