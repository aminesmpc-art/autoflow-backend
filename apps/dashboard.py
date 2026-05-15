"""Admin dashboard — rich visual stats with charts, funnels, and analytics."""
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def dashboard_callback(request, context):
    """Provide chart data, KPI metrics, funnels, and analytics for the dashboard."""
    from apps.plans.models import Profile
    from apps.usage.models import DailyUsage, UsageEvent
    from apps.users.models import CustomUser
    from apps.webhooks.models import WebhookEvent
    from apps.extractions.models import SavedExtraction
    from apps.marketing.models import EmailSequenceSubscriber
    from django.db.models import Sum, Count, Avg, Q

    today = timezone.localdate()
    now = timezone.now()

    # ── Users ──
    total_users = CustomUser.objects.count()
    active_users = CustomUser.objects.filter(is_active=True).count()
    inactive_users = total_users - active_users
    today_signups = CustomUser.objects.filter(created_at__date=today).count()
    week_signups = CustomUser.objects.filter(
        created_at__date__gte=today - timedelta(days=7)
    ).count()

    # ── Plans ──
    pro_users = Profile.objects.filter(is_pro_active=True).count()
    free_users = total_users - pro_users
    pro_pct = round((pro_users / total_users * 100) if total_users else 0)
    free_pct = 100 - pro_pct

    # ── Usage today ──
    today_agg = DailyUsage.objects.filter(date=today).aggregate(
        total=Sum("total_prompts_used"),
        text=Sum("text_prompts_used"),
        full=Sum("full_prompts_used"),
        downloads=Sum("downloads_used"),
    )
    today_total = today_agg["total"] or 0
    today_text = today_agg["text"] or 0
    today_full = today_agg["full"] or 0
    today_downloads = today_agg["downloads"] or 0
    active_today = DailyUsage.objects.filter(date=today).count()
    total_events = UsageEvent.objects.filter(created_at__date=today).count()

    # ── Yesterday comparison (for trend arrows) ──
    yesterday = today - timedelta(days=1)
    yesterday_agg = DailyUsage.objects.filter(date=yesterday).aggregate(
        total=Sum("total_prompts_used"),
        downloads=Sum("downloads_used"),
    )
    yesterday_total = yesterday_agg["total"] or 0
    yesterday_downloads = yesterday_agg["downloads"] or 0
    yesterday_signups = CustomUser.objects.filter(created_at__date=yesterday).count()
    yesterday_active = DailyUsage.objects.filter(date=yesterday).count()

    def trend(current, previous):
        if previous == 0:
            return "↑ New" if current > 0 else "—"
        diff = current - previous
        pct = round(abs(diff) / previous * 100)
        if diff > 0:
            return f"↑ {pct}% vs yesterday"
        elif diff < 0:
            return f"↓ {pct}% vs yesterday"
        return "→ Same as yesterday"

    # ── Webhooks ──
    pending_webhooks = WebhookEvent.objects.filter(processed=False).count()

    # ── Extractions ──
    total_extractions = SavedExtraction.objects.count()
    today_extractions = SavedExtraction.objects.filter(created_at__date=today).count()

    # ── Marketing Sequence ──
    marketing_total = EmailSequenceSubscriber.objects.count()
    marketing_active = EmailSequenceSubscriber.objects.filter(sequence_completed=False).count()
    marketing_completed = EmailSequenceSubscriber.objects.filter(sequence_completed=True).count()
    marketing_acted = EmailSequenceSubscriber.objects.filter(action_taken=True).count()
    marketing_converted_to_pro = CustomUser.objects.filter(
        email__in=EmailSequenceSubscriber.objects.filter(action_taken=True).values("email"),
        profile__is_pro_active=True
    ).count()
    marketing_conversion_rate = round((marketing_converted_to_pro / marketing_acted * 100) if marketing_acted else 0)

    # ── Conversion Funnel ──
    verified_users = CustomUser.objects.filter(is_active=True).count()
    users_with_usage = DailyUsage.objects.values("user").distinct().count()
    signup_to_verified = round((verified_users / total_users * 100) if total_users else 0)
    verified_to_active = round((users_with_usage / verified_users * 100) if verified_users else 0)
    active_to_pro = round((pro_users / users_with_usage * 100) if users_with_usage else 0)

    # ── 7-Day Retention ──
    retention_data = []
    for i in range(7, 0, -1):
        cohort_date = today - timedelta(days=i)
        cohort_size = CustomUser.objects.filter(created_at__date=cohort_date).count()
        if cohort_size > 0:
            returned = DailyUsage.objects.filter(
                user__created_at__date=cohort_date,
                date__gt=cohort_date,
            ).values("user").distinct().count()
            retention_pct = round(returned / cohort_size * 100)
        else:
            retention_pct = 0
        retention_data.append({
            "date": cohort_date.strftime("%b %d"),
            "cohort_size": cohort_size,
            "returned": returned if cohort_size > 0 else 0,
            "pct": retention_pct,
        })

    # ── Power Users (>50% of daily limit used) ──
    from apps.plans.services import FREE_TEXT_DAILY_LIMIT
    half_limit = FREE_TEXT_DAILY_LIMIT // 2
    power_users_qs = (
        DailyUsage.objects.filter(date=today, total_prompts_used__gte=half_limit)
        .select_related("user")
        .order_by("-total_prompts_used")[:5]
    )
    power_users = []
    for du in power_users_qs:
        try:
            is_pro = du.user.profile.is_pro
        except Exception:
            is_pro = False
        usage_pct = min(100, round(du.total_prompts_used / FREE_TEXT_DAILY_LIMIT * 100))
        power_users.append({
            "email": du.user.email,
            "total": du.total_prompts_used,
            "downloads": du.downloads_used,
            "pct": usage_pct,
            "is_pro": is_pro,
        })

    # ── Revenue Estimate ──
    whop_paying_users = Profile.objects.filter(is_pro_active=True, whop_membership_id__isnull=False).count()
    pro_price_monthly = 10.00  # Whop subscription price
    mrr = round(whop_paying_users * pro_price_monthly, 2)
    arr = round(mrr * 12, 2)

    # ── Event Type Distribution ──
    event_dist_qs = (
        UsageEvent.objects.filter(created_at__date=today)
        .values("event_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    event_distribution = []
    event_colors = {
        "consume_prompt": "#3b82f6",
        "queue_started": "#059669",
        "queue_finished": "#10b981",
        "prompt_failed": "#dc2626",
        "download_completed": "#a78bfa",
        "run_aborted": "#f59e0b",
        "reward_granted": "#eab308",
    }
    event_labels = {
        "consume_prompt": "Prompts",
        "queue_started": "Queue Start",
        "queue_finished": "Queue Done",
        "prompt_failed": "Failed",
        "download_completed": "Downloads",
        "run_aborted": "Aborted",
        "reward_granted": "Rewards",
    }
    for ev in event_dist_qs:
        event_distribution.append({
            "type": event_labels.get(ev["event_type"], ev["event_type"]),
            "count": ev["count"],
            "color": event_colors.get(ev["event_type"], "#6b7280"),
        })

    # ── Recent Activity Feed (last 10 events) ──
    recent_events_qs = (
        UsageEvent.objects.select_related("user")
        .order_by("-created_at")[:10]
    )
    recent_activity = []
    event_icons = {
        "consume_prompt": "📝",
        "queue_started": "▶️",
        "queue_finished": "✅",
        "prompt_failed": "❌",
        "download_completed": "⬇️",
        "run_aborted": "⚠️",
        "reward_granted": "🎁",
    }
    for ev in recent_events_qs:
        from django.utils.timesince import timesince
        recent_activity.append({
            "email": ev.user.email,
            "icon": event_icons.get(ev.event_type, "•"),
            "label": event_labels.get(ev.event_type, ev.event_type),
            "color": event_colors.get(ev.event_type, "#6b7280"),
            "count": ev.prompt_count,
            "time_ago": timesince(ev.created_at),
        })

    # ── 7-day usage chart data ──
    chart_labels = []
    chart_text = []
    chart_full = []
    chart_total = []
    chart_downloads = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        chart_labels.append(d.strftime("%b %d"))
        agg = DailyUsage.objects.filter(date=d).aggregate(
            t=Sum("text_prompts_used"),
            f=Sum("full_prompts_used"),
            tot=Sum("total_prompts_used"),
            dl=Sum("downloads_used"),
        )
        chart_text.append(agg["t"] or 0)
        chart_full.append(agg["f"] or 0)
        chart_total.append(agg["tot"] or 0)
        chart_downloads.append(agg["dl"] or 0)

    # ── 7-day signup chart data ──
    signup_labels = []
    signup_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        signup_labels.append(d.strftime("%b %d"))
        signup_data.append(
            CustomUser.objects.filter(created_at__date=d).count()
        )

    # ── Top 5 users today ──
    top_users_qs = (
        DailyUsage.objects.filter(date=today)
        .select_related("user")
        .order_by("-total_prompts_used")[:5]
    )
    top_users = []
    for du in top_users_qs:
        top_users.append({
            "email": du.user.email,
            "text": du.text_prompts_used,
            "full": du.full_prompts_used,
            "downloads": du.downloads_used,
            "total": du.total_prompts_used,
        })

    # ── Recent signups ──
    recent_users = []
    for u in CustomUser.objects.order_by("-created_at")[:5]:
        try:
            plan = u.profile.get_plan_type_display()
        except Exception:
            plan = "—"
        recent_users.append({
            "email": u.email,
            "plan": plan,
            "active": u.is_active,
            "date": u.created_at.strftime("%b %d, %H:%M"),
        })

    # ── All-time stats ──
    all_time_prompts = DailyUsage.objects.aggregate(t=Sum("total_prompts_used"))["t"] or 0
    all_time_downloads = DailyUsage.objects.aggregate(d=Sum("downloads_used"))["d"] or 0

    context.update({
        # KPI cards
        "kpi": [
            {
                "title": "Total Users",
                "metric": total_users,
                "footer": trend(today_signups, yesterday_signups),
                "highlight": f"+{today_signups} today" if today_signups else None,
                "icon": "group",
            },
            {
                "title": "Pro Subscribers",
                "metric": pro_users,
                "footer": f"${mrr:.0f} MRR · ${arr:.0f} ARR",
                "highlight": f"{pro_pct}% conversion" if pro_pct > 0 else None,
                "icon": "workspace_premium",
                "accent": "gold",
            },
            {
                "title": "Prompts Today",
                "metric": today_total,
                "footer": trend(today_total, yesterday_total),
                "highlight": f"{today_text} text · {today_full} image",
                "icon": "edit_note",
            },
            {
                "title": "Downloads Today",
                "metric": today_downloads,
                "footer": trend(today_downloads, yesterday_downloads),
                "icon": "download",
                "accent": "purple",
            },
            {
                "title": "Active Today",
                "metric": active_today,
                "footer": trend(active_today, yesterday_active),
                "highlight": f"{total_events} events",
                "icon": "monitoring",
            },
            {
                "title": "Extractions",
                "metric": total_extractions,
                "footer": f"{today_extractions} today" if today_extractions else "Video prompt extractor",
                "icon": "movie",
            },
            {
                "title": "Pending Webhooks",
                "metric": pending_webhooks,
                "footer": "⚠️ Needs attention!" if pending_webhooks else "All processed ✓",
                "icon": "webhook",
                "accent": "red" if pending_webhooks else None,
            },
        ],
        # Chart data
        "usage_chart": json.dumps({
            "labels": chart_labels,
            "datasets": [
                {
                    "label": "Text Prompts",
                    "data": chart_text,
                    "backgroundColor": "#10b981",
                    "borderRadius": 4,
                },
                {
                    "label": "Image Prompts",
                    "data": chart_full,
                    "backgroundColor": "#6ee7b7",
                    "borderRadius": 4,
                },
                {
                    "label": "Downloads",
                    "data": chart_downloads,
                    "backgroundColor": "#a78bfa",
                    "borderRadius": 4,
                },
            ],
        }),
        "signup_chart": json.dumps({
            "labels": signup_labels,
            "datasets": [
                {
                    "label": "Signups",
                    "data": signup_data,
                    "borderColor": "#34d399",
                    "backgroundColor": "rgba(52, 211, 153, 0.1)",
                    "fill": True,
                    "tension": 0.4,
                    "type": "line",
                    "pointRadius": 4,
                    "pointBackgroundColor": "#34d399",
                },
            ],
        }),
        # Plan distribution
        "plan_distribution": {
            "pro_count": pro_users,
            "free_count": free_users,
            "pro_pct": pro_pct,
            "free_pct": free_pct,
        },
        # Conversion funnel
        "funnel": {
            "total_users": total_users,
            "verified": verified_users,
            "active": users_with_usage,
            "pro": pro_users,
            "signup_to_verified": signup_to_verified,
            "verified_to_active": verified_to_active,
            "active_to_pro": active_to_pro,
        },
        # Retention
        "retention": retention_data,
        # Revenue
        "revenue": {
            "mrr": mrr,
            "arr": arr,
            "price": pro_price_monthly,
        },
        # Power users
        "power_users": power_users,
        # Event distribution
        "event_distribution": event_distribution,
        # Recent activity
        "recent_activity": recent_activity,
        # All-time stats
        "all_time": {
            "prompts": all_time_prompts,
            "downloads": all_time_downloads,
        },
        # Tables
        "top_users": top_users,
        "recent_users": recent_users,
        # Marketing Analytics
        "marketing": {
            "total": marketing_total,
            "active": marketing_active,
            "completed": marketing_completed,
            "acted": marketing_acted,
            "converted_to_pro": marketing_converted_to_pro,
            "conversion_rate": marketing_conversion_rate,
        },
    })

    return context


def environment_callback(request):
    """Show environment label in the sidebar."""
    if settings.DEBUG:
        return ["LOCAL", "info"]
    return ["PRODUCTION", "warning"]


def badge_callback_users(request):
    """Sidebar badge: total user count."""
    from apps.users.models import CustomUser
    return CustomUser.objects.count()


def badge_callback_pro(request):
    """Sidebar badge: active Pro subscriber count."""
    from apps.plans.models import Profile
    return Profile.objects.filter(is_pro_active=True).count()


def badge_callback_today_usage(request):
    """Sidebar badge: users who were active today."""
    from apps.usage.models import DailyUsage
    from django.utils import timezone
    return DailyUsage.objects.filter(date=timezone.localdate()).count()


def badge_callback_pending_webhooks(request):
    """Sidebar badge: unprocessed webhooks (only shown if > 0)."""
    from apps.webhooks.models import WebhookEvent
    count = WebhookEvent.objects.filter(processed=False).count()
    return count if count > 0 else None


def badge_callback_extractions(request):
    """Sidebar badge: total extractions."""
    from apps.extractions.models import SavedExtraction
    return SavedExtraction.objects.count()


def badge_callback_downloads_today(request):
    """Sidebar badge: downloads today."""
    from apps.usage.models import DailyUsage
    from django.utils import timezone
    from django.db.models import Sum
    result = DailyUsage.objects.filter(
        date=timezone.localdate()
    ).aggregate(d=Sum("downloads_used"))
    count = result["d"] or 0
    return count if count > 0 else None


def badge_callback_pending_claims(request):
    """Sidebar badge: pending review reward claims."""
    from apps.rewards.models import ReviewRewardClaim
    count = ReviewRewardClaim.objects.filter(status="pending").count()
    return count if count > 0 else None

