"""Admin dashboard — live stats shown at the top of the admin homepage."""
from django.utils import timezone


def dashboard_callback(request, context):
    """Show key business metrics as easy-to-read cards."""
    from apps.users.models import CustomUser
    from apps.plans.models import Profile
    from apps.usage.models import DailyUsage, UsageEvent
    from apps.webhooks.models import WebhookEvent
    from django.db.models import Sum

    today = timezone.localdate()

    # Users
    total_users = CustomUser.objects.count()
    active_users = CustomUser.objects.filter(is_active=True).count()
    today_signups = CustomUser.objects.filter(created_at__date=today).count()

    # Plans
    pro_users = Profile.objects.filter(is_pro_active=True).count()
    free_users = total_users - pro_users

    # Usage today
    today_usage = DailyUsage.objects.filter(date=today).aggregate(
        total=Sum("total_prompts_used"),
        text=Sum("text_prompts_used"),
        full=Sum("full_prompts_used"),
    )
    active_today = DailyUsage.objects.filter(date=today).count()
    total_events = UsageEvent.objects.filter(created_at__date=today).count()

    # Webhooks
    pending_webhooks = WebhookEvent.objects.filter(processed=False).count()

    context.update({
        "kpi": [
            {
                "title": "👥 Total Users",
                "metric": total_users,
                "footer": f"📈 {today_signups} new today" if today_signups else "No signups today",
            },
            {
                "title": "✅ Active Users",
                "metric": active_users,
                "footer": f"⏸️ {total_users - active_users} haven't verified email yet",
            },
            {
                "title": "⚡ Pro Subscribers",
                "metric": pro_users,
                "footer": f"🆓 {free_users} still on free plan",
            },
            {
                "title": "📝 Prompts Used Today",
                "metric": today_usage["total"] or 0,
                "footer": f"📝 {today_usage['text'] or 0} text-only  •  🖼️ {today_usage['full'] or 0} with images",
            },
            {
                "title": "🟢 Active Today",
                "metric": active_today,
                "footer": f"📊 {total_events} total events logged today",
            },
            {
                "title": "📨 Pending Webhooks",
                "metric": pending_webhooks,
                "footer": "⚠️ Needs attention!" if pending_webhooks else "✅ All webhooks processed",
            },
        ],
    })

    return context


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
