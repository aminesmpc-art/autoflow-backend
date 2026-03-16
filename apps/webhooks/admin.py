"""Admin config for webhooks — with clear status indicators and actions."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(ModelAdmin):
    list_display = (
        "event_badge", "provider_display", "user_display",
        "processed_badge", "event_id_short", "time_ago",
    )
    list_filter = ("provider", "event_type", "processed")
    search_fields = ("external_event_id", "linked_user__email")
    readonly_fields = ("created_at", "raw_payload")
    date_hierarchy = "created_at"
    list_per_page = 50
    actions = ["mark_processed", "reprocess"]

    @admin.display(description="🏷️ Event Type")
    def event_badge(self, obj):
        if "activated" in obj.event_type or "valid" in obj.event_type:
            color, icon = "#10b981", "⚡"
        elif "cancelled" in obj.event_type or "deactivated" in obj.event_type or "invalid" in obj.event_type:
            color, icon = "#dc2626", "🔒"
        elif "payment" in obj.event_type:
            color, icon = "#8b5cf6", "💳"
        else:
            color, icon = "#6b7280", "•"
        label = obj.event_type.replace("_", " ").replace(".", " → ").title()
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:6px;'
            'font-size:11px;font-weight:600;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="🔌 Provider")
    def provider_display(self, obj):
        icons = {"whop": "💳 Whop", "stripe": "💰 Stripe"}
        return icons.get(obj.provider, obj.provider.title())

    @admin.display(description="👤 User")
    def user_display(self, obj):
        if obj.linked_user:
            return obj.linked_user.email
        return format_html(
            '<span style="color:#6b7280;font-style:italic;">No user linked</span>'
        )

    @admin.display(description="✅ Processed?", boolean=True)
    def processed_badge(self, obj):
        return obj.processed

    @admin.display(description="🔑 Event ID")
    def event_id_short(self, obj):
        if obj.external_event_id:
            short = obj.external_event_id[:16] + "…" if len(obj.external_event_id) > 16 else obj.external_event_id
            return format_html(
                '<code style="font-size:11px;background:#1e293b;padding:2px 6px;border-radius:4px;">{}</code>',
                short,
            )
        return "—"

    @admin.display(description="🕐 When")
    def time_ago(self, obj):
        from django.utils.timesince import timesince
        return f"{timesince(obj.created_at)} ago"

    @admin.action(description="✅ Mark selected as processed")
    def mark_processed(self, request, queryset):
        from django.utils import timezone
        count = queryset.update(processed=True, processed_at=timezone.now())
        self.message_user(request, f"✅ {count} event(s) marked as processed.")

    @admin.action(description="🔄 Reprocess selected events")
    def reprocess(self, request, queryset):
        from apps.webhooks.services import process_whop_webhook
        count = 0
        for event in queryset:
            event.processed = False
            event.save(update_fields=["processed"])
            process_whop_webhook(event)
            count += 1
        self.message_user(request, f"🔄 Reprocessed {count} event(s).")
