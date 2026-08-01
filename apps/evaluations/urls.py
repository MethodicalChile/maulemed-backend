from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    EvaluationFormViewSet,
    EvaluationFormQuestionViewSet,
    UserEvaluationViewSet,
)

router = DefaultRouter()
router.register("evaluation-forms",     EvaluationFormViewSet,         basename="evaluation-forms")
router.register("evaluation-questions", EvaluationFormQuestionViewSet, basename="evaluation-questions")
router.register("user-evaluations",     UserEvaluationViewSet,         basename="user-evaluations")

urlpatterns = [
    path("", include(router.urls)),
]
