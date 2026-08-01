from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
    RoleViewSet,
    UserProfileViewSet,
    google_login,
    UserRoleAssignmentViewSet,
    UserManagementViewSet,
    change_my_password,
    update_my_profile,
    role_permissions_matrix,
    update_role_permission,
    me,
)


router = DefaultRouter()
router.register("roles", RoleViewSet, basename="roles")
router.register("user-profiles", UserProfileViewSet, basename="user-profiles")
router.register("user-role-assignments", UserRoleAssignmentViewSet, basename="user-role-assignments")
router.register("users", UserManagementViewSet, basename="users")


urlpatterns = [
    path("auth/login/",              CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/",            CustomTokenRefreshView.as_view(),    name="token_refresh"),
    path("auth/me/",                 me,                                  name="auth_me"),
    path("auth/change-password/",    change_my_password,       name="auth_change_password"),
    path("auth/update-profile/",     update_my_profile,        name="auth_update_profile"),
    path("auth/role-permissions/",   role_permissions_matrix,  name="auth_role_permissions"),
    path("auth/role-permissions/update/", update_role_permission, name="auth_role_permission_update"),
    path("auth/google/",            google_login,               name="google_login"),
    path("", include(router.urls)),
]
