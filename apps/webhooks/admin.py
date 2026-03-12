"""Admin config for webhooks."""
from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(ModelAdmin):
    list_display = ("provider", "event_type", "external_event_id", "processed", "linked_user", "created_at")
    list_filter = ("provider", "event_type", "processed")
    search_fields = ("external_event_id", "linked_user__email")
    readonly_fields = ("created_at", "raw_payload")
    date_hierarchy = "created_at"
