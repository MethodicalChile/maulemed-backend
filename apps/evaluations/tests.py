"""
Tests de la integración Google Forms para EvaluationFormViewSet.

Todas las llamadas reales a Google se mockean — no se realizan requests externos.
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.evaluations.models import EvaluationForm, EvaluationFormQuestion

User = get_user_model()

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

MOCK_GOOGLE_RESULT = {
    "google_form_id":       "FAKE_FORM_ID",
    "google_form_url":      "https://docs.google.com/forms/d/FAKE_FORM_ID/viewform",
    "google_form_edit_url": "https://docs.google.com/forms/d/FAKE_FORM_ID/edit",
}


def _make_user(username="admin_test", is_admin=True):
    """Crea un usuario y le devuelve con token JWT."""
    user = User.objects.create_user(
        username=username,
        password="testpass123",
        first_name="Admin",
        last_name="Test",
    )
    if is_admin:
        # Simula el permiso de admin/gerente creando un rol directo
        # mediante is_superuser para simplicidad en tests
        user.is_superuser = True
        user.is_staff = True
        user.save()
    return user


def _auth_client(test_case, user):
    token = RefreshToken.for_user(user).access_token
    test_case.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


def _make_form(user, with_question=True, title="Formulario test"):
    form = EvaluationForm.objects.create(
        title=title,
        description="Desc",
        created_by=user,
    )
    if with_question:
        EvaluationFormQuestion.objects.create(
            evaluation_form=form,
            order=1,
            question_text="¿Cómo te sientes?",
            question_type=EvaluationFormQuestion.TYPE_TEXT,
            is_required=True,
        )
    return form


# ──────────────────────────────────────────────────────────────────────────────
# Tests de publish-google-form
# ──────────────────────────────────────────────────────────────────────────────

class PublishGoogleFormTests(APITestCase):

    def setUp(self):
        self.user = _make_user()
        _auth_client(self, self.user)

    def _url(self, form_uuid):
        return reverse("evaluation-forms-publish-google-form", kwargs={"uuid": str(form_uuid)})

    # ── 1. Sin preguntas → 400 ────────────────────────────────────────────────
    def test_publish_without_questions_returns_400(self):
        form = _make_form(self.user, with_question=False)
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pregunta", resp.data["message"].lower())

    # ── 2. Ya publicado → 409 ─────────────────────────────────────────────────
    def test_publish_already_synced_returns_409(self):
        form = _make_form(self.user)
        form.google_form_id  = "ALREADY_EXISTS"
        form.google_form_url = "https://example.com/form"
        form.google_sync_status = EvaluationForm.GOOGLE_STATUS_SYNCED
        form.save()

        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    # ── 3. Tipo de pregunta inválido → 400 ────────────────────────────────────
    def test_publish_unsupported_question_type_returns_400(self):
        form = EvaluationForm.objects.create(title="Test", created_by=self.user)
        EvaluationFormQuestion.objects.create(
            evaluation_form=form,
            order=1,
            question_text="Pregunta",
            question_type="INVALID_TYPE",
            is_required=True,
        )
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── 4. Publicación correcta guarda campos ─────────────────────────────────
    @patch("apps.evaluations.views.GoogleFormsService")
    def test_publish_success_saves_fields(self, MockService):
        MockService.return_value.create_form.return_value = MOCK_GOOGLE_RESULT

        form = _make_form(self.user)
        resp = self.client.post(self._url(form.uuid))

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        form.refresh_from_db()
        self.assertEqual(form.google_form_id, "FAKE_FORM_ID")
        self.assertEqual(form.google_sync_status, EvaluationForm.GOOGLE_STATUS_SYNCED)
        self.assertIsNotNone(form.google_synced_at)
        self.assertIsNone(form.google_sync_error)

        data = resp.data["data"]
        self.assertEqual(data["google_form_id"], "FAKE_FORM_ID")
        self.assertEqual(data["google_sync_status"], "SYNCED")

    # ── 5. Excepción de Google → estado ERROR ─────────────────────────────────
    @patch("apps.evaluations.views.GoogleFormsService")
    def test_publish_google_exception_sets_error_status(self, MockService):
        MockService.return_value.create_form.side_effect = Exception("Google down")

        form = _make_form(self.user)
        resp = self.client.post(self._url(form.uuid))

        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        form.refresh_from_db()
        self.assertEqual(form.google_sync_status, EvaluationForm.GOOGLE_STATUS_ERROR)
        self.assertIn("Google down", form.google_sync_error)

    # ── 6. Sin autenticación → 401 ────────────────────────────────────────────
    def test_publish_unauthenticated_returns_401(self):
        self.client.credentials()   # quitar token
        form = _make_form(self.user)
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── 7. Usuario sin permisos → 403 ─────────────────────────────────────────
    def test_publish_non_admin_returns_403(self):
        normal_user = _make_user(username="regular", is_admin=False)
        _auth_client(self, normal_user)
        form = _make_form(self.user)
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ──────────────────────────────────────────────────────────────────────────────
# Tests del endpoint QR
# ──────────────────────────────────────────────────────────────────────────────

class QREndpointTests(APITestCase):

    def setUp(self):
        self.user = _make_user()
        _auth_client(self, self.user)

    def _url(self, form_uuid, download=False):
        url = reverse("evaluation-forms-qr", kwargs={"uuid": str(form_uuid)})
        if download:
            url += "?download=true"
        return url

    # ── 1. Sin URL → 400 ──────────────────────────────────────────────────────
    def test_qr_without_url_returns_400(self):
        form = _make_form(self.user)
        # google_form_url vacío por defecto
        resp = self.client.get(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── 2. Con URL → PNG ──────────────────────────────────────────────────────
    def test_qr_returns_png(self):
        form = _make_form(self.user)
        form.google_form_url    = "https://docs.google.com/forms/d/TEST/viewform"
        form.google_form_id     = "TEST"
        form.google_sync_status = EvaluationForm.GOOGLE_STATUS_SYNCED
        form.save()

        resp = self.client.get(self._url(form.uuid))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertIn("inline", resp["Content-Disposition"])
        # Verificar firma PNG (\x89PNG)
        self.assertTrue(resp.content[:4] == b"\x89PNG")

    # ── 3. ?download=true → attachment ────────────────────────────────────────
    def test_qr_download_uses_attachment(self):
        form = _make_form(self.user)
        form.google_form_url    = "https://docs.google.com/forms/d/TEST/viewform"
        form.google_form_id     = "TEST"
        form.google_sync_status = EvaluationForm.GOOGLE_STATUS_SYNCED
        form.save()

        resp = self.client.get(self._url(form.uuid, download=True))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn(f"formulario-{form.uuid}.png", resp["Content-Disposition"])


# ──────────────────────────────────────────────────────────────────────────────
# Tests de validación de preguntas
# ──────────────────────────────────────────────────────────────────────────────

class ValidationTests(APITestCase):

    def setUp(self):
        self.user = _make_user()
        _auth_client(self, self.user)

    def _url(self, form_uuid):
        return reverse("evaluation-forms-publish-google-form", kwargs={"uuid": str(form_uuid)})

    def _form_with_question(self, **kwargs):
        form = EvaluationForm.objects.create(title="T", created_by=self.user)
        defaults = dict(
            evaluation_form=form,
            order=1,
            question_text="Pregunta",
            question_type=EvaluationFormQuestion.TYPE_TEXT,
            is_required=True,
        )
        defaults.update(kwargs)
        EvaluationFormQuestion.objects.create(**defaults)
        return form

    @patch("apps.evaluations.views.GoogleFormsService")
    def test_empty_question_text_returns_400(self, _):
        form = self._form_with_question(question_text="   ")
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.evaluations.views.GoogleFormsService")
    def test_single_without_options_returns_400(self, _):
        form = self._form_with_question(
            question_type=EvaluationFormQuestion.TYPE_SINGLE,
            options=["Solo una opción"],
        )
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.evaluations.views.GoogleFormsService")
    def test_rating_out_of_range_returns_400(self, _):
        form = self._form_with_question(
            question_type=EvaluationFormQuestion.TYPE_RATING,
            rating_max=15,
        )
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.evaluations.views.GoogleFormsService")
    def test_duplicate_options_returns_400(self, _):
        form = self._form_with_question(
            question_type=EvaluationFormQuestion.TYPE_MULTIPLE,
            options=["Opción A", "Opción A"],
        )
        resp = self.client.post(self._url(form.uuid))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
