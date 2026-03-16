"""Admin config for usage tracking — with friendly labels and readable stats."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import DailyUsage, UsageEvent


@admin.register(DailyUsage)
class DailyUsageAdmin(ModelAdmin):
    list_display = (
        "user_email", "date", "text_count", "full_count",
        "total_badge", "created_at",
    )
    list_filter = ("date",)
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date"
    list_per_page = 50
    actions = ["reset_usage"]

    @admin.display(description="👤 User", ordering="user__email")
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description="📝 Text Prompts")
    def text_count(self, obj):
        count = obj.text_prompts_used
        return format_html(
            '<span style="font-weight:600;font-size:13px;">{}</span>',
            count,
        )

    @admin.display(description="🖼️ Full Prompts")
    def full_count(self, obj):
        count = obj.full_prompts_used
        return format_html(
            '<span style="font-weight:600;font-size:13px;">{}</span>',
            count,
        )

    @admin.display(description="📊 Total Used")
    def total_badge(self, obj):
        total = obj.total_prompts_used
        if total >= 100:
            color, label = "#dc2626", "🔴 Heavy"
        elif total >= 50:
            color, label = "#f59e0b", "🟡 Medium"
        elif total >= 10:
            color, label = "#3b82f6", "🔵 Active"
        else:
            color, label = "#10b981", "🟢 Light"
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:6px;'
            'font-size:12px;font-weight:600;">{} ({})</span>',
            color, total, label,
        )

    @admin.action(description="🔄 Reset all usage counters to 0")
    def reset_usage(self, request, queryset):
        count = queryset.update(
            free_prompts_used=0, reward_prompts_used=0, total_prompts_used=0,
            text_prompts_used=0, full_prompts_used=0,
        )
        self.message_user(request, f"✅ Reset usage for {count} record(s).")


@admin.register(UsageEvent)
class UsageEventAdmin(ModelAdmin):
    list_display = (
        "user_email", "event_badge", "prompt_count_display",
        "source_badge", "prompt_type_badge", "time_ago",
    )
    list_filter = ("event_type", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "metadata")
    date_hierarchy = "created_at"
    list_per_page = 50

    @admin.display(description="👤 User", ordering="user__email")
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description="🏷️ Event")
    def event_badge(self, obj):
        colors = {
            "consume_prompt": ("#2563eb", "📝", "Prompt Used"),
            "queue_started": ("#059669", "▶️", "Queue Started"),
            "queue_finished": ("#10b981", "✅", "Queue Finished"),
            "prompt_failed": ("#dc2626", "❌", "Prompt Failed"),
            "download_completed": ("#8b5cf6", "⬇️", "Download Done"),
            "run_aborted": ("#f59e0b", "⚠️", "Run Stopped"),
            "reward_granted": ("#eab308", "🎁", "Reward Given"),
        }
        color, icon, label = colors.get(obj.event_type, ("#6b7280", "•", obj.event_type))
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:6px;'
            'font-size:11px;font-weight:600;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="🔢 Count")
    def prompt_count_display(self, obj):
        if obj.prompt_count == 0:
            return "—"
        return format_html(
            '<span style="font-weight:700;font-size:14px;">{}</span>',
            obj.prompt_count,
        )

    @admin.display(description="📱 Source")
    def source_badge(self, obj):
        """Shows where the event came from (extension, web, API)."""
        if not obj.metadata:
            return "—"
        source = obj.metadata.get("source", "—")
        colors = {
            "extension": ("#2563eb", "🧩 Extension"),
            "web": ("#10b981", "🌐 Website"),
            "api": ("#8b5cf6", "⚙️ API"),
        }
        color, label = colors.get(source, ("#6b7280", source.title()))
        return format_html(
            '<span style="color:{};font-size:12px;font-weight:500;">{}</span>',
            color, label,
        )

    @admin.display(description="📄 Type")
    def prompt_type_badge(self, obj):
        """Shows the prompt type in a friendly way."""
        if not obj.metadata:
            return "—"
        ptype = obj.metadata.get("prompt_type", "—")
        labels = {
            "text": ("📝", "Text Only", "#3b82f6"),
            "full": ("🖼️", "With Images", "#8b5cf6"),
            "frames": ("🎬", "With Frames", "#ec4899"),
        }
        icon, label, color = labels.get(ptype, ("•", ptype.title(), "#6b7280"))
        return format_html(
            '<span style="color:{};font-size:12px;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="🕐 When")
    def time_ago(self, obj):
        from django.utils.timesince import timesince
        return f"{timesince(obj.created_at)} ago"
