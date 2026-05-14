"""Admin config for usage tracking — with polished badges and readable stats."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import DailyUsage, UsageEvent


@admin.register(DailyUsage)
class DailyUsageAdmin(ModelAdmin):
    list_display = (
        "user_display", "plan_badge", "date_display", "text_count", "full_count",
        "download_count", "total_badge", "created_display",
    )
    list_filter = ("date",)
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date"
    list_per_page = 50
    list_display_links = ("user_display",)
    actions = ["reset_usage", "export_csv"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user__profile")

    @admin.action(description="📥 Export selected as CSV")
    def export_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="autoflow_usage.csv"'
        writer = csv.writer(response)
        writer.writerow(["User", "Date", "Text", "Full", "Downloads", "Total", "Rewards"])
        for row in queryset.select_related("user").order_by("-date"):
            writer.writerow([
                row.user.email, row.date, row.text_prompts_used,
                row.full_prompts_used, row.downloads_used,
                row.total_prompts_used, row.reward_prompts_used,
            ])
        self.message_user(request, f"📥 Exported {queryset.count()} row(s) to CSV.")
        return response

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return format_html(
            '<span style="color:#60a5fa;font-weight:600;font-size:13px;">{}</span>',
            obj.user.email,
        )

    @admin.display(description="Plan", ordering="user__profile__plan_type")
    def plan_badge(self, obj):
        try:
            profile = obj.user.profile
            if profile.is_pro_active:
                return format_html(
                    '<span style="background:linear-gradient(135deg, rgba(99,102,241,0.2), rgba(167,139,250,0.2));'
                    'color:#a5b4fc;border:1px solid rgba(99,102,241,0.3);padding:2px 8px;border-radius:12px;'
                    'font-size:10px;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;">PRO</span>'
                )
            return format_html(
                '<span style="background:rgba(100,116,139,0.15);color:#94a3b8;border:1px solid rgba(100,116,139,0.2);'
                'padding:2px 8px;border-radius:12px;font-size:10px;font-weight:700;'
                'letter-spacing:0.5px;text-transform:uppercase;">FREE</span>'
            )
        except Exception:
            return format_html('<span style="color:#6b7280;">—</span>')

    @admin.display(description="Date", ordering="date")
    def date_display(self, obj):
        return format_html(
            '<span style="color:#d1d5db;font-size:12px;font-weight:500;">{}</span>',
            obj.date.strftime("%b %d, %Y"),
        )

    @admin.display(description="Text Prompts")
    def text_count(self, obj):
        count = obj.text_prompts_used
        if count == 0:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')
        return format_html(
            '<div style="display:inline-flex;align-items:center;gap:4px;">'
            '<span style="color:#94a3b8;font-size:12px;">📝</span>'
            '<span style="font-weight:700;font-size:14px;color:#f8fafc;'
            'font-variant-numeric:tabular-nums;">{}</span></div>',
            count,
        )

    @admin.display(description="Full Prompts")
    def full_count(self, obj):
        count = obj.full_prompts_used
        if count == 0:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')
        return format_html(
            '<div style="display:inline-flex;align-items:center;gap:4px;">'
            '<span style="color:#a78bfa;font-size:12px;">✨</span>'
            '<span style="font-weight:700;font-size:14px;color:#f8fafc;'
            'font-variant-numeric:tabular-nums;">{}</span></div>',
            count,
        )

    @admin.display(description="Total Used")
    def total_badge(self, obj):
        total = obj.total_prompts_used
        if total >= 100:
            bg, label = "linear-gradient(135deg, #7f1d1d, #b91c1c)", "Heavy"
            border = "rgba(239, 68, 68, 0.4)"
        elif total >= 50:
            bg, label = "linear-gradient(135deg, #78350f, #d97706)", "Medium"
            border = "rgba(245, 158, 11, 0.4)"
        elif total >= 10:
            bg, label = "linear-gradient(135deg, #064e3b, #059669)", "Active"
            border = "rgba(16, 185, 129, 0.4)"
        elif total > 0:
            bg, label = "linear-gradient(135deg, #1e3a8a, #2563eb)", "Light"
            border = "rgba(59, 130, 246, 0.4)"
        else:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')
            
        return format_html(
            '<div style="display:inline-flex;align-items:center;background:{};'
            'border:1px solid {};padding:2px 8px;border-radius:8px;'
            'box-shadow:0 2px 4px rgba(0,0,0,0.2);">'
            '<span style="font-weight:800;font-size:12px;color:#fff;margin-right:6px;">{}</span>'
            '<span style="font-size:10px;font-weight:600;color:rgba(255,255,255,0.8);'
            'text-transform:uppercase;letter-spacing:0.5px;">{}</span>'
            '</div>',
            bg, border, total, label,
        )

    @admin.display(description="Downloads")
    def download_count(self, obj):
        count = obj.downloads_used
        if count == 0:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')
        return format_html(
            '<div style="display:inline-flex;align-items:center;gap:4px;">'
            '<span style="color:#38bdf8;font-size:12px;">⬇</span>'
            '<span style="font-weight:700;font-size:14px;color:#bae6fd;'
            'font-variant-numeric:tabular-nums;">{}</span></div>',
            count,
        )

    @admin.display(description="Created", ordering="created_at")
    def created_display(self, obj):
        return format_html(
            '<span style="color:#6b7280;font-size:12px;">{}</span>',
            obj.created_at.strftime("%b %d, %H:%M"),
        )

    @admin.action(description="🔄 Reset all usage counters to 0")
    def reset_usage(self, request, queryset):
        count = queryset.update(
            free_prompts_used=0, reward_prompts_used=0, total_prompts_used=0,
            text_prompts_used=0, full_prompts_used=0, downloads_used=0,
        )
        self.message_user(request, f"✅ Reset usage for {count} record(s).")


@admin.register(UsageEvent)
class UsageEventAdmin(ModelAdmin):
    list_display = (
        "user_display", "event_badge", "prompt_count_display",
        "source_badge", "prompt_type_badge", "time_display",
    )
    list_filter = ("event_type", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "metadata")
    date_hierarchy = "created_at"
    list_per_page = 50

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return format_html(
            '<span style="color:#34d399;font-weight:500;">{}</span>',
            obj.user.email,
        )

    @admin.display(description="Event")
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
            '<span style="background:{};color:#fff;padding:4px 10px;border-radius:6px;'
            'font-size:11px;font-weight:600;letter-spacing:0.02em;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="Count")
    def prompt_count_display(self, obj):
        if obj.prompt_count == 0:
            return format_html('<span style="color:#4b5563;">—</span>')
        return format_html(
            '<span style="font-weight:700;font-size:14px;color:#e5e7eb;'
            'font-variant-numeric:tabular-nums;">{}</span>',
            obj.prompt_count,
        )

    @admin.display(description="Source")
    def source_badge(self, obj):
        """Shows where the event came from (extension, web, API)."""
        if not obj.metadata:
            return format_html('<span style="color:#4b5563;">—</span>')
        source = obj.metadata.get("source", "—")
        colors = {
            "extension": ("#1e3a5f", "#60a5fa", "🧩 Extension"),
            "web": ("#064e3b", "#6ee7b7", "🌐 Website"),
            "api": ("#3b1f7a", "#c4b5fd", "⚙️ API"),
        }
        bg, fg, label = colors.get(source, ("#1f2937", "#9ca3af", source.title()))
        return format_html(
            '<span style="background:{};color:{};padding:3px 8px;border-radius:5px;'
            'font-size:11px;font-weight:500;">{}</span>',
            bg, fg, label,
        )

    @admin.display(description="Type")
    def prompt_type_badge(self, obj):
        """Shows the prompt type in a friendly way."""
        if not obj.metadata:
            return format_html('<span style="color:#4b5563;">—</span>')
        ptype = obj.metadata.get("prompt_type", "—")
        labels = {
            "text": ("📝", "Text Only", "#3b82f6"),
            "full": ("🖼️", "With Images", "#8b5cf6"),
            "frames": ("🎬", "With Frames", "#ec4899"),
        }
        icon, label, color = labels.get(ptype, ("•", ptype.title(), "#6b7280"))
        return format_html(
            '<span style="color:{};font-size:12px;font-weight:500;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="When", ordering="created_at")
    def time_display(self, obj):
        from django.utils.timesince import timesince
        return format_html(
            '<span style="color:#6b7280;font-size:12px;">{} ago</span>',
            timesince(obj.created_at),
        )
