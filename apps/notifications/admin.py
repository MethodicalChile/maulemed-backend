from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "user",
        "title",
        "notification_type",
        "is_read",
        "related_model",
        "related_uuid",
        "created_at",
    )
    search_fields = (
        "uuid",
        "user__username",
        "user__first_name",
        "user__last_name",
        "title",
        "message",
    )
    list_filter = (
        "notification_type",
        "is_read",
        "created_at",
    )
