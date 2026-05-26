"""Admin config for usage tracking — advanced analytics with smart logic."""
from django.contrib import admin
from django.db.models import Sum, Count, Q, F
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import DailyUsage, MonthlyUsage, UsageEvent


# ── Custom Filters ──


class UsageLevelFilter(admin.SimpleListFilter):
    """Filter users by how much of their daily limit they used."""
    title = "Usage Level"
    parameter_name = "usage_level"

    def lookups(self, request, model_admin):
        return [
            ("maxed", "🔴 Maxed Out (100%)"),
            ("heavy", "🟠 Heavy (70-99%)"),
            ("active", "🟢 Active (30-69%)"),
            ("light", "🔵 Light (1-29%)"),
            ("ghost", "👻 Ghost (0 prompts)"),
        ]

    def queryset(self, request, queryset):
        from apps.plans.services import FREE_TEXT_DAILY_LIMIT
        limit = FREE_TEXT_DAILY_LIMIT
        if self.value() == "maxed":
            return queryset.filter(free_prompts_used__gte=limit)
        elif self.value() == "heavy":
            return queryset.filter(free_prompts_used__gte=int(limit * 0.7), free_prompts_used__lt=limit)
        elif self.value() == "active":
            return queryset.filter(free_prompts_used__gte=int(limit * 0.3), free_prompts_used__lt=int(limit * 0.7))
        elif self.value() == "light":
            return queryset.filter(free_prompts_used__gte=1, free_prompts_used__lt=int(limit * 0.3))
        elif self.value() == "ghost":
            return queryset.filter(total_prompts_used=0)
        return queryset


class QueueModeFilter(admin.SimpleListFilter):
    """Filter by which queue modes were used."""
    title = "Queue Mode"
    parameter_name = "queue_mode"

    def lookups(self, request, model_admin):
        return [
            ("lite_only", "⚡ Lite Only"),
            ("flow_only", "🔄 Flow Only"),
            ("full_only", "🚀 Full Only"),
            ("mixed", "🎯 Mixed Modes"),
            ("no_queue", "❌ No Queue Runs"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "lite_only":
            return queryset.filter(lite_runs_today__gt=0, flow_runs_today=0, full_runs_today=0)
        elif self.value() == "flow_only":
            return queryset.filter(flow_runs_today__gt=0, lite_runs_today=0, full_runs_today=0)
        elif self.value() == "full_only":
            return queryset.filter(full_runs_today__gt=0, lite_runs_today=0, flow_runs_today=0)
        elif self.value() == "mixed":
            return queryset.filter(
                Q(lite_runs_today__gt=0) | Q(flow_runs_today__gt=0) | Q(full_runs_today__gt=0)
            ).exclude(
                Q(lite_runs_today__gt=0, flow_runs_today=0, full_runs_today=0) |
                Q(flow_runs_today__gt=0, lite_runs_today=0, full_runs_today=0) |
                Q(full_runs_today__gt=0, lite_runs_today=0, flow_runs_today=0)
            )
        elif self.value() == "no_queue":
            return queryset.filter(lite_runs_today=0, flow_runs_today=0, full_runs_today=0)
        return queryset


class PlanFilter(admin.SimpleListFilter):
    """Filter by user plan type."""
    title = "Plan"
    parameter_name = "plan_type"

    def lookups(self, request, model_admin):
        return [
            ("pro", "⚡ Pro Users"),
            ("free", "🆓 Free Users"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "pro":
            return queryset.filter(user__profile__is_pro_active=True)
        elif self.value() == "free":
            return queryset.exclude(user__profile__is_pro_active=True)
        return queryset


@admin.register(DailyUsage)
class DailyUsageAdmin(ModelAdmin):
    list_display = (
        "user_display", "plan_badge", "date_display",
        "prompt_usage_bar", "queue_breakdown",
        "download_badge", "completion_rate",
        "total_badge", "created_display",
    )
    list_filter = (PlanFilter, UsageLevelFilter, QueueModeFilter, "date")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date"
    list_per_page = 50
    list_display_links = ("user_display",)
    actions = ["reset_usage", "export_csv"]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("user__profile")
            .annotate(
                _total_runs=F("lite_runs_today") + F("flow_runs_today") + F("full_runs_today"),
            )
        )

    @admin.action(description="📥 Export selected as CSV")
    def export_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="autoflow_usage.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "User", "Plan", "Date", "Text", "Full", "Extend", "Downloads",
            "Lite Runs", "Flow Runs", "Full Runs", "Total Prompts", "Free Used", "Rewards",
        ])
        for row in queryset.select_related("user__profile").order_by("-date"):
            try:
                plan = "PRO" if row.user.profile.is_pro_active else "FREE"
            except Exception:
                plan = "—"
            writer.writerow([
                row.user.email, plan, row.date,
                row.text_prompts_used, row.full_prompts_used, row.extend_prompts_used,
                row.downloads_used,
                row.lite_runs_today, row.flow_runs_today, row.full_runs_today,
                row.total_prompts_used, row.free_prompts_used, row.reward_prompts_used,
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

    @admin.display(description="Prompts Usage")
    def prompt_usage_bar(self, obj):
        """Visual progress bar showing text + full + extend prompts with limit awareness."""
        from apps.plans.services import FREE_TEXT_DAILY_LIMIT, FREE_FULL_DAILY_LIMIT
        text = obj.text_prompts_used
        full = obj.full_prompts_used
        extend = obj.extend_prompts_used
        total = text + full + extend

        if total == 0:
            return format_html('<span style="color:#475569;font-size:12px;">No prompts</span>')

        try:
            is_pro = obj.user.profile.is_pro_active
        except Exception:
            is_pro = False

        # Calculate usage % against limit (for free users)
        limit = FREE_TEXT_DAILY_LIMIT
        pct = min(100, round(obj.free_prompts_used / limit * 100)) if not is_pro and limit > 0 else 0

        # Color coding based on limit usage
        if is_pro:
            bar_color = "linear-gradient(90deg, #6366f1, #818cf8)"
            glow = "rgba(99,102,241,0.4)"
        elif pct >= 90:
            bar_color = "linear-gradient(90deg, #dc2626, #f87171)"
            glow = "rgba(220,38,38,0.4)"
        elif pct >= 70:
            bar_color = "linear-gradient(90deg, #d97706, #fbbf24)"
            glow = "rgba(217,119,6,0.4)"
        else:
            bar_color = "linear-gradient(90deg, #10b981, #34d399)"
            glow = "rgba(16,185,129,0.4)"

        # Build the breakdown chips
        chips = []
        if text > 0:
            chips.append(f'<span style="color:#60a5fa;font-size:11px;">📝{text}</span>')
        if full > 0:
            chips.append(f'<span style="color:#a78bfa;font-size:11px;">✨{full}</span>')
        if extend > 0:
            chips.append(f'<span style="color:#f472b6;font-size:11px;">🔗{extend}</span>')

        chip_html = '<span style="margin-left:4px;">' + ' '.join(chips) + '</span>' if chips else ''

        if is_pro:
            # Pro users: just show count, no bar
            return format_html(
                '<div style="display:flex;align-items:center;gap:6px;">'
                '<span style="font-weight:700;font-size:14px;color:#a5b4fc;">{}</span>'
                '{}'
                '</div>',
                total, format_html(chip_html),
            )

        # Free users: show progress bar with limit
        return format_html(
            '<div style="min-width:160px;">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">'
            '<span style="font-weight:700;font-size:13px;color:#f8fafc;">{}/{}</span>'
            '{}'
            '</div>'
            '<div style="height:6px;border-radius:999px;background:rgba(0,0,0,0.3);overflow:hidden;">'
            '<div style="height:100%;width:{}%;border-radius:999px;background:{};box-shadow:0 0 8px {};'
            'transition:width 0.5s ease;"></div>'
            '</div>'
            '</div>',
            total, limit, format_html(chip_html),
            pct, bar_color, glow,
        )

    @admin.display(description="Queue Runs")
    def queue_breakdown(self, obj):
        """Shows queue runs by mode with avg prompts per run."""
        lite = obj.lite_runs_today
        flow = obj.flow_runs_today
        full_r = obj.full_runs_today
        total_runs = lite + flow + full_r

        if total_runs == 0:
            return format_html('<span style="color:#475569;font-size:12px;">No runs</span>')

        # Calculate avg prompts per run
        total_prompts = obj.total_prompts_used
        avg = round(total_prompts / total_runs, 1) if total_runs > 0 else 0

        # Build mode chips
        parts = []
        if lite > 0:
            parts.append(
                f'<span style="background:rgba(234,179,8,0.15);color:#facc15;padding:2px 6px;'
                f'border-radius:4px;font-size:10px;font-weight:700;">⚡{lite}</span>'
            )
        if flow > 0:
            parts.append(
                f'<span style="background:rgba(16,185,129,0.15);color:#34d399;padding:2px 6px;'
                f'border-radius:4px;font-size:10px;font-weight:700;">🔄{flow}</span>'
            )
        if full_r > 0:
            parts.append(
                f'<span style="background:rgba(99,102,241,0.15);color:#818cf8;padding:2px 6px;'
                f'border-radius:4px;font-size:10px;font-weight:700;">🚀{full_r}</span>'
            )

        mode_html = ' '.join(parts)
        return format_html(
            '<div>'
            '<div style="display:flex;gap:4px;align-items:center;margin-bottom:3px;">{}</div>'
            '<div style="font-size:10px;color:#6b7280;">~{} prompts/run</div>'
            '</div>',
            format_html(mode_html), avg,
        )

    @admin.display(description="Downloads")
    def download_badge(self, obj):
        """Downloads with limit indicator for free users."""
        from apps.plans.services import FREE_DOWNLOAD_DAILY_LIMIT
        count = obj.downloads_used
        if count == 0:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')

        try:
            is_pro = obj.user.profile.is_pro_active
        except Exception:
            is_pro = False

        limit = FREE_DOWNLOAD_DAILY_LIMIT
        if not is_pro and count >= limit:
            # Hit the limit
            return format_html(
                '<div style="display:inline-flex;align-items:center;gap:4px;">'
                '<span style="color:#f87171;font-weight:700;font-size:14px;">⬇{}/{}</span>'
                '<span style="background:rgba(239,68,68,0.15);color:#f87171;padding:1px 5px;'
                'border-radius:3px;font-size:9px;font-weight:700;">MAX</span>'
                '</div>',
                count, limit,
            )

        color = "#a5b4fc" if is_pro else "#38bdf8"
        return format_html(
            '<div style="display:inline-flex;align-items:center;gap:4px;">'
            '<span style="color:{};font-size:12px;">⬇</span>'
            '<span style="font-weight:700;font-size:14px;color:{};">{}</span>'
            '</div>',
            color, color, count,
        )

    @admin.display(description="Completion %")
    def completion_rate(self, obj):
        """
        Logic: Downloads / Total Prompts = how many prompts resulted in a download.
        This tells us the actual conversion rate of prompts → usable videos.
        """
        total = obj.total_prompts_used
        downloads = obj.downloads_used
        if total == 0:
            return format_html('<span style="color:#475569;font-size:12px;">—</span>')

        rate = round(downloads / total * 100)

        # Color based on rate
        if rate >= 80:
            color, bg = "#34d399", "rgba(16,185,129,0.12)"
            label = "Excellent"
        elif rate >= 50:
            color, bg = "#fbbf24", "rgba(234,179,8,0.12)"
            label = "Good"
        elif rate >= 20:
            color, bg = "#f97316", "rgba(249,115,22,0.12)"
            label = "Low"
        elif rate > 0:
            color, bg = "#f87171", "rgba(239,68,68,0.12)"
            label = "Poor"
        else:
            color, bg = "#475569", "transparent"
            label = "None"

        return format_html(
            '<div style="text-align:center;">'
            '<div style="background:{};color:{};padding:3px 8px;border-radius:6px;'
            'font-size:12px;font-weight:700;display:inline-block;">'
            '{}% <span style="font-size:9px;opacity:0.7;">{}</span>'
            '</div>'
            '<div style="font-size:9px;color:#6b7280;margin-top:2px;">{}/{} saved</div>'
            '</div>',
            bg, color, rate, label, downloads, total,
        )

    @admin.display(description="Total Used")
    def total_badge(self, obj):
        total = obj.total_prompts_used
        total_runs = obj.lite_runs_today + obj.flow_runs_today + obj.full_runs_today

        if total == 0 and total_runs == 0:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')

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
            # Ghost: has runs but no prompts (shouldn't happen after fix)
            bg, label = "linear-gradient(135deg, #3f3f46, #52525b)", "Ghost"
            border = "rgba(113, 113, 122, 0.4)"

        return format_html(
            '<div style="display:inline-flex;align-items:center;background:{};'
            'border:1px solid {};padding:3px 10px;border-radius:8px;'
            'box-shadow:0 2px 4px rgba(0,0,0,0.2);">'
            '<span style="font-weight:800;font-size:13px;color:#fff;margin-right:6px;">{}</span>'
            '<span style="font-size:10px;font-weight:600;color:rgba(255,255,255,0.8);'
            'text-transform:uppercase;letter-spacing:0.5px;">{}</span>'
            '</div>',
            bg, border, total, label,
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
            text_prompts_used=0, full_prompts_used=0, extend_prompts_used=0,
            downloads_used=0,
            lite_runs_today=0, flow_runs_today=0, full_runs_today=0,
        )
        self.message_user(request, f"✅ Reset usage for {count} record(s).")


@admin.register(UsageEvent)
class UsageEventAdmin(ModelAdmin):
    list_display = (
        "user_display", "event_badge", "prompt_count_display",
        "source_badge", "prompt_type_badge", "dedup_indicator", "time_display",
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
            "queue_run_lite": ("#eab308", "⚡", "Lite Run"),
            "queue_run_flow": ("#10b981", "🔄", "Flow Run"),
            "queue_run_full": ("#6366f1", "🚀", "Full Run"),
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
            "extend": ("🔗", "Extend", "#f59e0b"),
        }
        icon, label, color = labels.get(ptype, ("•", ptype.title(), "#6b7280"))
        return format_html(
            '<span style="color:{};font-size:12px;font-weight:500;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="Dedup")
    def dedup_indicator(self, obj):
        """Shows if this event was a dedup (pre-consumed by queue run, no counter increment)."""
        if not obj.metadata:
            return format_html('<span style="color:#4b5563;">—</span>')

        is_dedup = obj.metadata.get("dedup", False)
        source_used = obj.metadata.get("source_used", "")

        if is_dedup or source_used == "pre_consumed":
            return format_html(
                '<span style="background:rgba(234,179,8,0.15);color:#fbbf24;padding:2px 6px;'
                'border-radius:4px;font-size:10px;font-weight:700;">'
                '🔒 DEDUP</span>'
            )
        return format_html('<span style="color:#475569;font-size:11px;">—</span>')

    @admin.display(description="When", ordering="created_at")
    def time_display(self, obj):
        from django.utils.timesince import timesince
        return format_html(
            '<span style="color:#6b7280;font-size:12px;">{} ago</span>',
            timesince(obj.created_at),
        )


@admin.register(MonthlyUsage)
class MonthlyUsageAdmin(ModelAdmin):
    list_display = ("user_display", "period_display", "full_runs_badge", "created_display")
    list_filter = ("year", "month")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return format_html(
            '<span style="color:#60a5fa;font-weight:600;font-size:13px;">{}</span>',
            obj.user.email,
        )

    @admin.display(description="Period")
    def period_display(self, obj):
        import calendar
        month_name = calendar.month_abbr[obj.month]
        return format_html(
            '<span style="color:#d1d5db;font-weight:500;font-size:13px;">{} {}</span>',
            month_name, obj.year,
        )

    @admin.display(description="Full Runs")
    def full_runs_badge(self, obj):
        count = obj.full_runs_used
        if count == 0:
            return format_html('<span style="color:#475569;font-size:13px;">0</span>')
        bg = "#6366f1" if count < 2 else "#dc2626"
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:6px;'
            'font-size:12px;font-weight:700;">\U0001f680 {}</span>',
            bg, count,
        )

    @admin.display(description="Created", ordering="created_at")
    def created_display(self, obj):
        return format_html(
            '<span style="color:#6b7280;font-size:12px;">{}</span>',
            obj.created_at.strftime("%b %d, %H:%M"),
        )
