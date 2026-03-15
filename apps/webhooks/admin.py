"""Admin config for webhooks — with payload preview and status badges."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(ModelAdmin):
    list_display = ("event_badge", "provider", "linked_user", "processed_badge", "external_short", "created_at")
    list_filter = ("provider", "event_type", "processed")
    search_fields = ("external_event_id", "linked_user__email")
    readonly_fields = ("created_at", "raw_payload")
    date_hierarchy = "created_at"
    list_per_page = 50
    actions = ["mark_processed", "reprocess"]

    @admin.display(description="Event Type")
    def event_badge(self, obj):
        # Color by activation vs deactivation
        if "activated" in obj.event_type or "valid" in obj.event_type:
            color = "#10b981"
            icon = "⚡"
        elif "cancelled" in obj.event_type or "deactivated" in obj.event_type or "invalid" in obj.event_type:
            color = "#dc2626"
            icon = "🔒"
        elif "payment" in obj.event_type:
            color = "#8b5cf6"
            icon = "💳"
        else:
            color = "#6b7280"
            icon = "•"
        label = obj.event_type.replace("_", " ").replace(".", " ").title()
        return format_html(
            '<span style="color:{};font-size:12px;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="Processed", boolean=True)
    def processed_badge(self, obj):
        return obj.processed

    @admin.display(description="Event ID")
    def external_short(self, obj):
        if obj.external_event_id:
            return obj.external_event_id[:20] + "…" if len(obj.external_event_id) > 20 else obj.external_event_id
        return "—"

    @admin.action(description="✅ Mark as processed")
    def mark_processed(self, request, queryset):
        from django.utils import timezone
        count = queryset.update(processed=True, processed_at=timezone.now())
        self.message_user(request, f"{count} event(s) marked as processed.")

    @admin.action(description="🔄 Reprocess selected events")
    def reprocess(self, request, queryset):
        from apps.webhooks.services import process_whop_webhook
        count = 0
        for event in queryset:
            event.processed = False
            event.save(update_fields=["processed"])
            process_whop_webhook(event)
            count += 1
        self.message_user(request, f"Reprocessed {count} event(s).")
