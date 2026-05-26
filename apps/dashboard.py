"""Admin dashboard — rich visual stats with charts, funnels, and analytics.

Data philosophy: All prompt counts are derived from confirmed UsageEvent records
(consume_prompt events), NOT from DailyUsage pre-consumed totals. This ensures
the admin sees what ACTUALLY happened, not inflated "launch intent" numbers.
"""
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def _event_prompt_counts(date_filter):
    """Count confirmed prompts from events, split by type.

    Returns (total, text, full) based on actual consume_prompt events.
    Each consume_prompt event = a prompt that actually ran through Flow.
    """
    from apps.usage.models import UsageEvent
    from django.db.models import Sum, Q, Count

    qs = UsageEvent.objects.filter(
        event_type="consume_prompt",
        **date_filter,
    )
    total = qs.aggregate(s=Sum("prompt_count"))["s"] or 0

    # Count by prompt_type in metadata
    full = qs.filter(metadata__prompt_type="full").aggregate(
        s=Sum("prompt_count")
    )["s"] or 0
    text = total - full  # everything else is text

    return total, text, full


def dashboard_callback(request, context):
    """Provide chart data, KPI metrics, funnels, and analytics for the dashboard."""
    from apps.plans.models import Profile
    from apps.usage.models import DailyUsage, UsageEvent, MonthlyUsage
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

    # ── REAL usage today (from confirmed events) ──
    today_total, today_text, today_full = _event_prompt_counts(
        {"created_at__date": today}
    )

    # Downloads from events (real downloads, not pre-consumed)
    today_downloads = UsageEvent.objects.filter(
        created_at__date=today,
        event_type="download_completed",
    ).aggregate(s=Sum("prompt_count"))["s"] or 0

    # Queue run counts (from DailyUsage — these are accurate since each run = 1 event)
    today_run_agg = DailyUsage.objects.filter(date=today).aggregate(
        lite_runs=Sum("lite_runs_today"),
        flow_runs=Sum("flow_runs_today"),
    )
    today_lite_runs = today_run_agg["lite_runs"] or 0
    today_flow_runs = today_run_agg["flow_runs"] or 0

    # Full runs from monthly (accurate)
    today_full_runs = MonthlyUsage.objects.filter(
        year=today.year, month=today.month,
    ).aggregate(t=Sum("full_runs_used"))["t"] or 0

    active_today = DailyUsage.objects.filter(date=today).count()
    total_events = UsageEvent.objects.filter(created_at__date=today).count()

    # Queue runs recorded today (from events)
    today_queue_run_count = UsageEvent.objects.filter(
        created_at__date=today,
        event_type__in=["queue_run_lite", "queue_run_flow", "queue_run_full"],
    ).count()

    # ── Yesterday comparison (REAL event-based) ──
    yesterday = today - timedelta(days=1)
    yesterday_total, _, _ = _event_prompt_counts({"created_at__date": yesterday})
    yesterday_downloads = UsageEvent.objects.filter(
        created_at__date=yesterday,
        event_type="download_completed",
    ).aggregate(s=Sum("prompt_count"))["s"] or 0
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

    # ── Power Users (event-based — real usage) ──
    from apps.plans.services import FREE_TEXT_DAILY_LIMIT
    power_users_qs = (
        UsageEvent.objects.filter(
            created_at__date=today,
            event_type="consume_prompt",
        )
        .values("user__email", "user__profile__is_pro_active")
        .annotate(
            total=Sum("prompt_count"),
            text_count=Sum("prompt_count", filter=Q(metadata__prompt_type="text") | ~Q(metadata__has_key="prompt_type")),
            full_count=Sum("prompt_count", filter=Q(metadata__prompt_type="full")),
        )
        .order_by("-total")[:5]
    )
    power_users = []
    for pu in power_users_qs:
        total_p = pu["total"] or 0
        usage_pct = min(100, round(total_p / FREE_TEXT_DAILY_LIMIT * 100))
        power_users.append({
            "email": pu["user__email"],
            "total": total_p,
            "text": pu["text_count"] or 0,
            "full": pu["full_count"] or 0,
            "pct": usage_pct,
            "is_pro": pu["user__profile__is_pro_active"] or False,
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
        "queue_run_lite": "#facc15",
        "queue_run_flow": "#34d399",
        "queue_run_full": "#6366f1",
    }
    event_labels = {
        "consume_prompt": "Prompts",
        "queue_started": "Queue Start",
        "queue_finished": "Queue Done",
        "prompt_failed": "Failed",
        "download_completed": "Downloads",
        "run_aborted": "Aborted",
        "reward_granted": "Rewards",
        "queue_run_lite": "Lite Run",
        "queue_run_flow": "Flow Run",
        "queue_run_full": "Full Run",
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
        "queue_run_lite": "⚡",
        "queue_run_flow": "🔄",
        "queue_run_full": "🚀",
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

    # ── 7-day usage chart data (event-based = REAL) ──
    chart_labels = []
    chart_text = []
    chart_full = []
    chart_total = []
    chart_downloads = []
    chart_lite_runs = []
    chart_flow_runs = []
    chart_full_runs = []
    chart_active_users = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        chart_labels.append(d.strftime("%b %d"))

        # Real prompt counts from events
        d_total, d_text, d_full = _event_prompt_counts({"created_at__date": d})
        chart_text.append(d_text)
        chart_full.append(d_full)
        chart_total.append(d_total)

        # Downloads from events
        d_downloads = UsageEvent.objects.filter(
            created_at__date=d, event_type="download_completed"
        ).aggregate(s=Sum("prompt_count"))["s"] or 0
        chart_downloads.append(d_downloads)

        # Queue runs from DailyUsage (accurate — 1 run = 1 increment)
        run_agg = DailyUsage.objects.filter(date=d).aggregate(
            lr=Sum("lite_runs_today"),
            fr=Sum("flow_runs_today"),
        )
        chart_lite_runs.append(run_agg["lr"] or 0)
        chart_flow_runs.append(run_agg["fr"] or 0)

        # Full runs from MonthlyUsage for that day's events
        d_full_runs = UsageEvent.objects.filter(
            created_at__date=d,
            event_type="queue_run_full",
        ).count()
        chart_full_runs.append(d_full_runs)

        # Active users (users who had any event that day)
        chart_active_users.append(
            UsageEvent.objects.filter(
                created_at__date=d,
                event_type="consume_prompt",
            ).values("user").distinct().count()
        )

    # ── Queue runs chart data ──
    queue_chart = json.dumps({
        "labels": chart_labels,
        "datasets": [
            {
                "label": "Lite",
                "data": chart_lite_runs,
                "backgroundColor": "#facc15",
                "borderRadius": 4,
            },
            {
                "label": "Flow",
                "data": chart_flow_runs,
                "backgroundColor": "#34d399",
                "borderRadius": 4,
            },
            {
                "label": "Full",
                "data": chart_full_runs,
                "backgroundColor": "#818cf8",
                "borderRadius": 4,
            },
        ],
    })

    # ── Active users chart data ──
    active_chart = json.dumps({
        "labels": chart_labels,
        "datasets": [
            {
                "label": "Active Users",
                "data": chart_active_users,
                "borderColor": "#f59e0b",
                "backgroundColor": "rgba(245, 158, 11, 0.1)",
                "fill": True,
                "tension": 0.4,
                "type": "line",
                "pointRadius": 5,
                "pointBackgroundColor": "#f59e0b",
            },
        ],
    })

    # ── Upgrade candidates (event-based — real usage intensity) ──
    from apps.plans.services import FREE_TEXT_DAILY_LIMIT
    threshold = int(FREE_TEXT_DAILY_LIMIT * 0.5)  # users who hit 50%+ of limit

    # Get users with high real usage in last 3 days
    upgrade_candidates_qs = (
        UsageEvent.objects.filter(
            created_at__date__gte=today - timedelta(days=3),
            event_type="consume_prompt",
        )
        .exclude(user__profile__is_pro_active=True)
        .values("user__email")
        .annotate(
            total_prompts=Sum("prompt_count"),
            days_active=Count("created_at__date", distinct=True),
            total_runs=Count(
                "id",
                filter=Q(event_type__in=["queue_run_lite", "queue_run_flow", "queue_run_full"]),
            ),
        )
        .filter(total_prompts__gte=threshold)
        .order_by("-total_prompts")[:8]
    )
    # We also need queue run counts from the same user set
    upgrade_candidates = []
    for uc in upgrade_candidates_qs:
        # Get queue runs separately since they're different event types
        user_runs = UsageEvent.objects.filter(
            created_at__date__gte=today - timedelta(days=3),
            event_type__in=["queue_run_lite", "queue_run_flow", "queue_run_full"],
            user__email=uc["user__email"],
        ).count()

        usage_pct = min(100, round(uc["total_prompts"] / (FREE_TEXT_DAILY_LIMIT * uc["days_active"]) * 100))
        upgrade_candidates.append({
            "email": uc["user__email"],
            "days_active": uc["days_active"],
            "total_prompts": uc["total_prompts"],
            "total_runs": user_runs,
            "usage_pct": usage_pct,
            "heat": "🔥🔥🔥" if usage_pct >= 90 else ("🔥🔥" if usage_pct >= 70 else "🔥"),
        })

    # ── Hourly activity heatmap (today) ──
    hourly_events = []
    for hour in range(24):
        count = UsageEvent.objects.filter(
            created_at__date=today,
            created_at__hour=hour,
        ).count()
        hourly_events.append(count)
    hourly_chart = json.dumps({
        "labels": [f"{h:02d}" for h in range(24)],
        "datasets": [{
            "label": "Events",
            "data": hourly_events,
            "backgroundColor": [
                f"rgba(16,185,129,{max(0.1, min(1.0, c / max(max(hourly_events), 1)))})"
                for c in hourly_events
            ],
            "borderRadius": 3,
        }],
    })

    # ── Avg prompts per queue run (real: confirmed prompts / queue runs) ──
    total_queue_runs = today_queue_run_count
    avg_prompts_per_run = round(today_total / total_queue_runs, 1) if total_queue_runs > 0 else 0

    # ── 7-day signup chart data ──
    signup_labels = []
    signup_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        signup_labels.append(d.strftime("%b %d"))
        signup_data.append(
            CustomUser.objects.filter(created_at__date=d).count()
        )

    # ── Top 5 users today (event-based = REAL) ──
    top_users_qs = (
        UsageEvent.objects.filter(
            created_at__date=today,
            event_type="consume_prompt",
        )
        .values("user__email")
        .annotate(
            total=Sum("prompt_count"),
            text=Sum("prompt_count", filter=Q(metadata__prompt_type="text") | ~Q(metadata__has_key="prompt_type")),
            full=Sum("prompt_count", filter=Q(metadata__prompt_type="full")),
        )
        .order_by("-total")[:5]
    )
    top_users = []
    for tu in top_users_qs:
        # Get downloads for this user today
        dl = UsageEvent.objects.filter(
            created_at__date=today,
            event_type="download_completed",
            user__email=tu["user__email"],
        ).aggregate(s=Sum("prompt_count"))["s"] or 0

        top_users.append({
            "email": tu["user__email"],
            "text": tu["text"] or 0,
            "full": tu["full"] or 0,
            "downloads": dl,
            "total": tu["total"] or 0,
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

    # ── All-time stats (event-based for accuracy) ──
    all_time_prompts = UsageEvent.objects.filter(
        event_type="consume_prompt"
    ).aggregate(s=Sum("prompt_count"))["s"] or 0
    all_time_downloads = UsageEvent.objects.filter(
        event_type="download_completed"
    ).aggregate(s=Sum("prompt_count"))["s"] or 0

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
                "title": "Queue Runs Today",
                "metric": today_lite_runs + today_flow_runs + today_full_runs,
                "footer": f"⚡{today_lite_runs} Lite · 🔄{today_flow_runs} Flow · 🚀{today_full_runs} Full",
                "highlight": f"~{avg_prompts_per_run} prompts/run" if avg_prompts_per_run > 0 else None,
                "icon": "play_circle",
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
        # Queue runs by mode (for mode cards)
        "queue_runs": {
            "lite": today_lite_runs,
            "flow": today_flow_runs,
            "full": today_full_runs,
            "total": today_lite_runs + today_flow_runs + today_full_runs,
        },
        # New analytics
        "queue_chart": queue_chart,
        "active_chart": active_chart,
        "hourly_chart": hourly_chart,
        "upgrade_candidates": upgrade_candidates,
        "avg_prompts_per_run": avg_prompts_per_run,
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
    from apps.usage.models import UsageEvent
    from django.utils import timezone
    from django.db.models import Sum
    result = UsageEvent.objects.filter(
        created_at__date=timezone.localdate(),
        event_type="download_completed",
    ).aggregate(d=Sum("prompt_count"))
    count = result["d"] or 0
    return count if count > 0 else None


def badge_callback_pending_claims(request):
    """Sidebar badge: pending review reward claims."""
    from apps.rewards.models import ReviewRewardClaim
    count = ReviewRewardClaim.objects.filter(status="pending").count()
    return count if count > 0 else None
