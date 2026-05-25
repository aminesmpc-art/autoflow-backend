"""
Entitlement & usage service — the core business logic layer.

All consumption, entitlement checks, and reward credit operations live here.
Views call these functions; no business logic in serializers or views.
"""
import logging
from datetime import date as date_type
from datetime import datetime, time

from django.conf import settings
from django.db import transaction, IntegrityError
from django.db.models import Sum
from django.utils import timezone

from apps.plans.models import PlanType, Profile
from apps.rewards.models import CreditStatus, RewardCreditLedger
from apps.usage.models import DailyUsage, MonthlyUsage, UsageEvent

logger = logging.getLogger(__name__)

# ── Plan limits ──
FREE_TEXT_DAILY_LIMIT = getattr(settings, "FREE_TEXT_DAILY_LIMIT", 100)
FREE_FULL_DAILY_LIMIT = getattr(settings, "FREE_FULL_DAILY_LIMIT", 20)
FREE_DOWNLOAD_DAILY_LIMIT = getattr(settings, "FREE_DOWNLOAD_DAILY_LIMIT", 20)
# Queue run limits (per mode)
FREE_LITE_DAILY_LIMIT = getattr(settings, "FREE_LITE_DAILY_LIMIT", 3)
FREE_FLOW_DAILY_LIMIT = getattr(settings, "FREE_FLOW_DAILY_LIMIT", 5)
FREE_FULL_DAILY_LIMIT_RUNS = getattr(settings, "FREE_FULL_DAILY_LIMIT_RUNS", 1)
# Keep legacy constant for backward compat
FREE_DAILY_LIMIT = FREE_TEXT_DAILY_LIMIT


# ── Daily usage helpers ──


def get_or_create_daily_usage(user, target_date: date_type = None) -> DailyUsage:
    """Get or create the DailyUsage row for user+date."""
    target_date = target_date or timezone.now().date()
    try:
        usage, _ = DailyUsage.objects.get_or_create(
            user=user,
            date=target_date,
            defaults={
                "free_prompts_used": 0,
                "reward_prompts_used": 0,
                "total_prompts_used": 0,
                "text_prompts_used": 0,
                "full_prompts_used": 0,
                "extend_prompts_used": 0,
                "downloads_used": 0,
                "lite_runs_today": 0,
                "flow_runs_today": 0,
                "full_runs_today": 0,
            },
        )
        return usage
    except IntegrityError:
        return DailyUsage.objects.get(user=user, date=target_date)


def get_or_create_monthly_usage(user, year: int = None, month: int = None) -> MonthlyUsage:
    """Get or create the MonthlyUsage row for user+year+month."""
    now = timezone.now()
    year = year or now.year
    month = month or now.month
    try:
        usage, _ = MonthlyUsage.objects.get_or_create(
            user=user, year=year, month=month,
            defaults={"full_runs_used": 0},
        )
        return usage
    except IntegrityError:
        return MonthlyUsage.objects.get(user=user, year=year, month=month)


def get_free_remaining(user, target_date: date_type = None) -> int:
    """How many free text prompts the user has left today."""
    usage = get_or_create_daily_usage(user, target_date)
    return max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used)


# ── Reward credit helpers ──


def get_reward_credit_balance(user) -> int:
    """Sum of all completed reward credit entries for the user."""
    result = (
        RewardCreditLedger.objects.filter(
            user=user, status=CreditStatus.COMPLETED
        ).aggregate(balance=Sum("amount"))
    )
    return result["balance"] or 0


def grant_reward_credits(
    user,
    amount: int,
    source: str,
    reference_id: str = None,
    metadata: dict = None,
) -> RewardCreditLedger:
    """Grant reward credits to a user (idempotent if reference_id provided)."""
    if amount <= 0:
        raise ValueError("Grant amount must be positive")

    if reference_id:
        existing = RewardCreditLedger.objects.filter(reference_id=reference_id).first()
        if existing:
            logger.info(
                "Idempotent reward grant: reference_id=%s already exists", reference_id
            )
            return existing

    entry = RewardCreditLedger.objects.create(
        user=user,
        amount=amount,
        source=source,
        status=CreditStatus.COMPLETED,
        reference_id=reference_id,
        metadata=metadata or {},
    )

    UsageEvent.objects.create(
        user=user,
        event_type=UsageEvent.EventType.REWARD_GRANTED,
        prompt_count=amount,
        metadata={"source": source, "reference_id": reference_id},
    )

    return entry


# ── Entitlement snapshot ──


def get_entitlement_snapshot(user) -> dict:
    """Full snapshot of a user's current entitlement state."""
    profile = Profile.objects.select_related("user").get(user=user)
    now = timezone.now()
    today = now.date()
    usage = get_or_create_daily_usage(user, today)
    monthly = get_or_create_monthly_usage(user, now.year, now.month)
    reward_balance = get_reward_credit_balance(user)

    text_remaining = max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used)
    full_remaining = max(0, FREE_FULL_DAILY_LIMIT - usage.full_prompts_used)

    # Reset time: midnight UTC of the next day
    tomorrow = today.toordinal() + 1
    import datetime as dt_mod
    reset_dt = datetime.combine(
        date_type.fromordinal(tomorrow), time.min, tzinfo=dt_mod.timezone.utc
    )

    can_run = False
    if profile.is_pro:
        can_run = True
    elif text_remaining > 0 or full_remaining > 0:
        can_run = True
    elif reward_balance > 0:
        can_run = True

    # Queue run limits
    lite_remaining = 999  # Lite is unlimited for all users
    flow_remaining = max(0, FREE_FLOW_DAILY_LIMIT - usage.flow_runs_today)
    full_daily_remaining = max(0, FREE_FULL_DAILY_LIMIT_RUNS - usage.full_runs_today)

    return {
        "plan_type": profile.plan_type,
        "is_pro_active": profile.is_pro,
        # Text-to-video limits (no images)
        "text_daily_limit": FREE_TEXT_DAILY_LIMIT,
        "text_used_today": usage.text_prompts_used,
        "text_remaining_today": text_remaining,
        # Full-feature limits (with images/frames)
        "full_daily_limit": FREE_FULL_DAILY_LIMIT,
        "full_used_today": usage.full_prompts_used,
        "full_remaining_today": full_remaining,
        # Legacy fields
        "free_daily_limit": FREE_TEXT_DAILY_LIMIT,
        "free_used_today": usage.free_prompts_used,
        "free_remaining_today": max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used),
        # Rewards
        "reward_credit_balance": reward_balance,
        "can_run_prompt": can_run,
        "reset_at": reset_dt.isoformat(),
        # Download limits
        "download_daily_limit": FREE_DOWNLOAD_DAILY_LIMIT,
        "downloads_used_today": usage.downloads_used,
        "downloads_remaining_today": max(0, FREE_DOWNLOAD_DAILY_LIMIT - usage.downloads_used),
        # Queue run limits (per mode)
        "lite_runs_today": usage.lite_runs_today,
        "lite_daily_limit": 0,  # 0 = unlimited
        "lite_remaining_today": 999,  # Lite is always unlimited
        "flow_runs_today": usage.flow_runs_today,
        "flow_daily_limit": FREE_FLOW_DAILY_LIMIT,
        "flow_remaining_today": flow_remaining if not profile.is_pro else 999,
        "full_runs_today": usage.full_runs_today,
        "full_daily_limit": FREE_FULL_DAILY_LIMIT_RUNS,
        "full_remaining_today_runs": full_daily_remaining if not profile.is_pro else 999,
        # Legacy monthly fields (keep for backward compat)
        "full_runs_this_month": monthly.full_runs_used,
        "full_monthly_limit": FREE_FULL_DAILY_LIMIT_RUNS,
        "full_remaining_this_month": full_daily_remaining if not profile.is_pro else 999,
    }


# ── Prompt consumption ──


def can_consume_prompt(user, prompt_type: str = "text") -> tuple[bool, str]:
    """Check if user is allowed to consume a prompt.

    prompt_type: "text" (text-to-video only) or "full" (with images/frames)
    
    Every prompt counts toward text_prompts_used (100/day).
    Full prompts ALSO count toward full_prompts_used (20/day).
    Returns (allowed, reason).
    """
    profile = Profile.objects.get(user=user)

    if profile.is_pro:
        return True, "pro"

    today = timezone.now().date()
    usage = get_or_create_daily_usage(user, today)

    # Every prompt counts toward the free (total) limit
    free_remaining = FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used
    if free_remaining <= 0:
        reward_balance = get_reward_credit_balance(user)
        if reward_balance > 0:
            return True, "reward"
        return False, "limit_reached"

    # Full prompts also count toward the stricter full-features limit
    if prompt_type == "full":
        full_remaining = FREE_FULL_DAILY_LIMIT - usage.full_prompts_used
        if full_remaining <= 0:
            return False, "full_limit_reached"

    return True, "free"


def consume_prompt(user, source: str = "extension", prompt_type: str = "text") -> dict:
    """Atomically consume one prompt.

    prompt_type: "text" (text-to-video), "full" (with images/frames), or "extend"
    Returns consumption result dict.
    """
    today = timezone.now().date()
    
    # 1. Ensure the DailyUsage record exists safely outside the transaction lock
    get_or_create_daily_usage(user, today)

    # 2. Open transaction and lock rows
    with transaction.atomic():
        profile = Profile.objects.select_for_update().get(user=user)
        usage = DailyUsage.objects.select_for_update().get(user=user, date=today)

        source_used = "pro"

        if profile.is_pro:
            source_used = "pro"
        else:
            # Every prompt counts toward the free limit
            free_remaining = FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used

            if free_remaining > 0:
                if prompt_type == "full":
                    full_remaining = FREE_FULL_DAILY_LIMIT - usage.full_prompts_used
                    if full_remaining <= 0:
                        return {
                            "allowed": False,
                            "source_used": None,
                            "text_remaining_today": max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used),
                            "full_remaining_today": 0,
                            "reward_credit_balance": get_reward_credit_balance(user),
                            "message": "Daily full-feature prompt limit reached.",
                        }
                usage.free_prompts_used += 1
                source_used = "free"
            else:
                reward_balance = get_reward_credit_balance(user)
                if reward_balance > 0:
                    RewardCreditLedger.objects.create(
                        user=user,
                        amount=-1,
                        source="prompt_consumption",
                        status=CreditStatus.COMPLETED,
                        metadata={"consumed_via": source, "prompt_type": prompt_type},
                    )
                    usage.reward_prompts_used += 1
                    source_used = "reward"
                else:
                    return {
                        "allowed": False,
                        "source_used": None,
                        "text_remaining_today": max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used),
                        "full_remaining_today": max(0, FREE_FULL_DAILY_LIMIT - usage.full_prompts_used),
                        "reward_credit_balance": 0,
                        "message": f"Daily {prompt_type} prompt limit reached.",
                    }

        if prompt_type == "full":
            usage.full_prompts_used += 1
        elif prompt_type == "extend":
            usage.extend_prompts_used += 1
        else:
            usage.text_prompts_used += 1

        usage.total_prompts_used += 1
        usage.save()

        UsageEvent.objects.create(
            user=user,
            event_type=UsageEvent.EventType.CONSUME_PROMPT,
            prompt_count=1,
            metadata={"source": source, "source_used": source_used, "prompt_type": prompt_type},
        )

        return {
            "allowed": True,
            "source_used": source_used,
            "prompt_type": prompt_type,
            "text_remaining_today": max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used) if not profile.is_pro else 999,
            "full_remaining_today": max(0, FREE_FULL_DAILY_LIMIT - usage.full_prompts_used) if not profile.is_pro else 999,
            "reward_credit_balance": get_reward_credit_balance(user),
            "message": "Prompt consumed successfully.",
        }


# ── Profile helpers ──


def mark_last_seen(user):
    """Update profile last_seen_at."""
    Profile.objects.filter(user=user).update(last_seen_at=timezone.now())


def sync_profile_plan(user, plan_type: str, is_pro_active: bool, **extra):
    """Update a user's plan info (e.g. after Whop webhook)."""
    Profile.objects.filter(user=user).update(
        plan_type=plan_type,
        is_pro_active=is_pro_active,
        updated_at=timezone.now(),
        **extra,
    )


# ── Download consumption ──


def can_download(user, count: int = 1) -> tuple[bool, int]:
    """Check if user can download `count` files. Returns (allowed, remaining)."""
    profile = Profile.objects.get(user=user)
    if profile.is_pro:
        return True, 999

    today = timezone.now().date()
    usage = get_or_create_daily_usage(user, today)
    remaining = max(0, FREE_DOWNLOAD_DAILY_LIMIT - usage.downloads_used)
    return count <= remaining, remaining


def consume_download(user, count: int = 1) -> dict:
    """Atomically consume download credits. Returns result dict."""
    today = timezone.now().date()

    # 1. Ensure the DailyUsage record exists safely outside the transaction lock
    get_or_create_daily_usage(user, today)

    with transaction.atomic():
        profile = Profile.objects.get(user=user)
        usage = DailyUsage.objects.select_for_update().get(user=user, date=today)

        if not profile.is_pro:
            remaining = FREE_DOWNLOAD_DAILY_LIMIT - usage.downloads_used
            if count > remaining:
                return {
                    "allowed": False,
                    "downloads_used_today": usage.downloads_used,
                    "downloads_remaining_today": max(0, remaining),
                    "download_daily_limit": FREE_DOWNLOAD_DAILY_LIMIT,
                    "message": f"Daily download limit reached ({FREE_DOWNLOAD_DAILY_LIMIT}/day). Upgrade to Pro for unlimited.",
                }

        usage.downloads_used += count
        usage.save()

        UsageEvent.objects.create(
            user=user,
            event_type=UsageEvent.EventType.DOWNLOAD_COMPLETED,
            prompt_count=count,
            metadata={"source": "extension", "count": count},
        )

        new_remaining = max(0, FREE_DOWNLOAD_DAILY_LIMIT - usage.downloads_used) if not profile.is_pro else 999
        return {
            "allowed": True,
            "downloads_used_today": usage.downloads_used,
            "downloads_remaining_today": new_remaining,
            "download_daily_limit": FREE_DOWNLOAD_DAILY_LIMIT if not profile.is_pro else 999,
            "message": f"{count} download(s) recorded.",
        }


# ── Queue run consumption ──


_MODE_EVENT_MAP = {
    "lite": UsageEvent.EventType.QUEUE_RUN_LITE,
    "flow": UsageEvent.EventType.QUEUE_RUN_FLOW,
    "full": UsageEvent.EventType.QUEUE_RUN_FULL,
}


def can_start_queue(user, mode: str) -> dict:
    """Check if user can start a queue in the given mode.

    Returns { allowed, used, limit, remaining, period, message }.
    """
    profile = Profile.objects.get(user=user)

    if profile.is_pro:
        return {
            "allowed": True,
            "used": 0,
            "limit": 999,
            "remaining": 999,
            "period": "unlimited",
            "message": "Pro — unlimited.",
        }

    now = timezone.now()
    today = now.date()
    usage = get_or_create_daily_usage(user, today)

    if mode == "lite":
        used = usage.lite_runs_today
        limit = FREE_LITE_DAILY_LIMIT
        remaining = max(0, limit - used)
        period = "day"
    elif mode == "flow":
        used = usage.flow_runs_today
        limit = FREE_FLOW_DAILY_LIMIT
        remaining = max(0, limit - used)
        period = "day"
    elif mode == "full":
        monthly = get_or_create_monthly_usage(user, now.year, now.month)
        used = monthly.full_runs_used
        limit = FREE_FULL_MONTHLY_LIMIT
        remaining = max(0, limit - used)
        period = "month"
    else:
        return {
            "allowed": False,
            "used": 0,
            "limit": 0,
            "remaining": 0,
            "period": "day",
            "message": f"Unknown mode: {mode}",
        }

    if remaining <= 0:
        return {
            "allowed": False,
            "used": used,
            "limit": limit,
            "remaining": 0,
            "period": period,
            "message": f"{mode.capitalize()} mode limit reached ({limit}/{period}). Upgrade to Pro for unlimited.",
        }

    return {
        "allowed": True,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "period": period,
        "message": f"{remaining} {mode} run(s) remaining this {period}.",
    }


def consume_queue_run(user, mode: str, prompt_count: int = 1, prompt_type: str = "text") -> dict:
    """Atomically record a queue run AND pre-consume prompts for the given mode.

    This ensures prompt usage is tracked even if the extension never calls back
    per-prompt (e.g. tab closed, network issue, extension crash).

    Returns consumption result dict.
    """
    now = timezone.now()
    today = now.date()

    # Ensure rows exist outside the lock
    get_or_create_daily_usage(user, today)
    if mode == "full":
        get_or_create_monthly_usage(user, now.year, now.month)

    with transaction.atomic():
        profile = Profile.objects.get(user=user)
        usage = DailyUsage.objects.select_for_update().get(user=user, date=today)

        # For full mode, always fetch monthly (Pro and Free both need it for tracking)
        monthly = None
        if mode == "full":
            monthly = MonthlyUsage.objects.select_for_update().get(
                user=user, year=now.year, month=now.month
            )

        # Enforce limits for free users only
        if not profile.is_pro:
            # Lite mode is unlimited for all users — no limit check needed
            if False:  # was: mode == "lite" limit check
                pass
            elif mode == "flow" and usage.flow_runs_today >= FREE_FLOW_DAILY_LIMIT:
                return {
                    "allowed": False,
                    "used": usage.flow_runs_today,
                    "limit": FREE_FLOW_DAILY_LIMIT,
                    "remaining": 0,
                    "period": "day",
                    "message": f"Flow mode limit reached ({FREE_FLOW_DAILY_LIMIT}/day). Upgrade to Pro for unlimited.",
                }
            elif mode == "full" and usage.full_runs_today >= FREE_FULL_DAILY_LIMIT_RUNS:
                return {
                    "allowed": False,
                    "used": usage.full_runs_today,
                    "limit": FREE_FULL_DAILY_LIMIT_RUNS,
                    "remaining": 0,
                    "period": "day",
                    "message": f"Full mode limit reached ({FREE_FULL_DAILY_LIMIT_RUNS}/day). Upgrade to Pro for unlimited.",
                }
            elif mode not in ("lite", "flow", "full"):
                return {
                    "allowed": False,
                    "used": 0,
                    "limit": 0,
                    "remaining": 0,
                    "period": "day",
                    "message": f"Unknown mode: {mode}",
                }

        # Increment queue run counters (for both Pro and Free — Pro for monitoring)
        if mode == "lite":
            usage.lite_runs_today += 1
        elif mode == "flow":
            usage.flow_runs_today += 1
        elif mode == "full":
            usage.full_runs_today += 1
            if monthly:
                monthly.full_runs_used += 1
                monthly.save()

        # ── Pre-consume prompts atomically ──
        # This is the critical fix: track prompt usage at queue start time
        # so it's recorded even if the extension never calls back per-prompt.
        if prompt_type == "full":
            usage.full_prompts_used += prompt_count
        else:
            usage.text_prompts_used += prompt_count
        usage.free_prompts_used += prompt_count
        usage.total_prompts_used += prompt_count
        usage.save()

        # Log queue run event
        event_type = _MODE_EVENT_MAP.get(mode, UsageEvent.EventType.QUEUE_STARTED)
        UsageEvent.objects.create(
            user=user,
            event_type=event_type,
            prompt_count=prompt_count,
            metadata={"mode": mode, "prompt_count": prompt_count, "prompt_type": prompt_type},
        )

        # Compute remaining
        if mode == "lite":
            used = usage.lite_runs_today
            limit = FREE_LITE_DAILY_LIMIT
            period = "day"
        elif mode == "flow":
            used = usage.flow_runs_today
            limit = FREE_FLOW_DAILY_LIMIT
            period = "day"
        else:  # full
            used = usage.full_runs_today
            limit = FREE_FULL_DAILY_LIMIT_RUNS
            period = "day"

        remaining = max(0, limit - used) if not profile.is_pro else 999

        return {
            "allowed": True,
            "used": used if not profile.is_pro else 0,
            "limit": limit if not profile.is_pro else 999,
            "remaining": remaining,
            "period": period,
            "message": f"Queue run recorded. {remaining} {mode} run(s) remaining.",
        }


