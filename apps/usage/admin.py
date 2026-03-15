"""Admin config for usage tracking — with summary stats and export."""
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import DailyUsage, UsageEvent


@admin.register(DailyUsage)
class DailyUsageAdmin(ModelAdmin):
    list_display = ("user", "date", "text_prompts_used", "full_prompts_used", "total_used_badge", "created_at")
    list_filter = ("date",)
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date"
    list_per_page = 50
    actions = ["reset_usage"]

    @admin.display(description="Total")
    def total_used_badge(self, obj):
        total = obj.total_prompts_used
        if total >= 100:
            color = "#dc2626"  # red — heavy user
        elif total >= 50:
            color = "#f59e0b"  # amber
        else:
            color = "#10b981"  # green
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{}</span>',
            color, total,
        )

    @admin.action(description="🔄 Reset usage to 0 for selected days")
    def reset_usage(self, request, queryset):
        count = queryset.update(
            free_prompts_used=0, reward_prompts_used=0, total_prompts_used=0,
            text_prompts_used=0, full_prompts_used=0,
        )
        self.message_user(request, f"Reset usage for {count} record(s).")


@admin.register(UsageEvent)
class UsageEventAdmin(ModelAdmin):
    list_display = ("user", "event_badge", "prompt_count", "short_meta", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "metadata")
    date_hierarchy = "created_at"
    list_per_page = 50

    @admin.display(description="Event")
    def event_badge(self, obj):
        colors = {
            "consume_prompt": ("#2563eb", "📝"),
            "queue_started": ("#059669", "▶️"),
            "queue_finished": ("#10b981", "✅"),
            "prompt_failed": ("#dc2626", "❌"),
            "download_completed": ("#8b5cf6", "⬇️"),
            "run_aborted": ("#f59e0b", "⚠️"),
            "reward_granted": ("#eab308", "🎁"),
        }
        color, icon = colors.get(obj.event_type, ("#6b7280", "•"))
        label = obj.event_type.replace("_", " ").title()
        return format_html(
            '<span style="color:{};font-size:12px;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="Details")
    def short_meta(self, obj):
        if not obj.metadata:
            return "—"
        # Show first 2 key-value pairs
        items = list(obj.metadata.items())[:2]
        parts = [f"{k}={v}" for k, v in items]
        return ", ".join(parts) if parts else "—"
