"""
Entitlement & usage service — the core business logic layer.

All consumption, entitlement checks, and reward credit operations live here.
Views call these functions; no business logic in serializers or views.
"""
import logging
from datetime import date as date_type
from datetime import datetime, time

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.plans.models import PlanType, Profile
from apps.rewards.models import CreditStatus, RewardCreditLedger
from apps.usage.models import DailyUsage, UsageEvent

logger = logging.getLogger(__name__)

FREE_DAILY_LIMIT = getattr(settings, "FREE_DAILY_PROMPT_LIMIT", 30)


# ── Daily usage helpers ──


def get_or_create_daily_usage(user, target_date: date_type = None) -> DailyUsage:
    """Get or create the DailyUsage row for user+date."""
    target_date = target_date or timezone.now().date()
    usage, _ = DailyUsage.objects.get_or_create(
        user=user,
        date=target_date,
        defaults={
            "free_prompts_used": 0,
            "reward_prompts_used": 0,
            "total_prompts_used": 0,
        },
    )
    return usage


def get_free_remaining(user, target_date: date_type = None) -> int:
    """How many free prompts the user has left today."""
    usage = get_or_create_daily_usage(user, target_date)
    return max(0, FREE_DAILY_LIMIT - usage.free_prompts_used)


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
    """Grant reward credits to a user (idempotent if reference_id provided).

    Returns the existing entry if reference_id already exists (idempotent).
    """
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

    # Log event
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
    today = timezone.now().date()
    usage = get_or_create_daily_usage(user, today)
    reward_balance = get_reward_credit_balance(user)
    free_remaining = max(0, FREE_DAILY_LIMIT - usage.free_prompts_used)

    # Reset time: midnight UTC of the next day
    tomorrow = today.toordinal() + 1
    import datetime as dt_mod
    reset_dt = datetime.combine(
        date_type.fromordinal(tomorrow), time.min, tzinfo=dt_mod.timezone.utc
    )

    can_run = False
    if profile.is_pro:
        can_run = True
    elif free_remaining > 0:
        can_run = True
    elif reward_balance > 0:
        can_run = True

    return {
        "plan_type": profile.plan_type,
        "is_pro_active": profile.is_pro_active,
        "free_daily_limit": FREE_DAILY_LIMIT,
        "free_used_today": usage.free_prompts_used,
        "free_remaining_today": free_remaining,
        "reward_credit_balance": reward_balance,
        "can_run_prompt": can_run,
        "reset_at": reset_dt.isoformat(),
    }


# ── Prompt consumption ──


def can_consume_prompt(user) -> tuple[bool, str]:
    """Check if user is allowed to consume a prompt.

    Returns (allowed, reason).
    """
    profile = Profile.objects.get(user=user)

    if profile.is_pro:
        return True, "pro"

    today = timezone.now().date()
    usage = get_or_create_daily_usage(user, today)
    free_remaining = FREE_DAILY_LIMIT - usage.free_prompts_used

    if free_remaining > 0:
        return True, "free"

    reward_balance = get_reward_credit_balance(user)
    if reward_balance > 0:
        return True, "reward"

    return False, "limit_reached"


@transaction.atomic
def consume_prompt(user, source: str = "extension") -> dict:
    """Atomically consume one prompt.

    Uses SELECT FOR UPDATE to prevent race conditions.
    Returns consumption result dict.
    """
    profile = Profile.objects.select_for_update().get(user=user)
    today = timezone.now().date()

    # Lock the daily usage row
    usage, created = DailyUsage.objects.select_for_update().get_or_create(
        user=user,
        date=today,
        defaults={
            "free_prompts_used": 0,
            "reward_prompts_used": 0,
            "total_prompts_used": 0,
        },
    )

    source_used = "pro"

    if profile.is_pro:
        # Pro: always allow, record for analytics
        source_used = "pro"
    else:
        free_remaining = FREE_DAILY_LIMIT - usage.free_prompts_used
        if free_remaining > 0:
            usage.free_prompts_used += 1
            source_used = "free"
        else:
            # Try reward credits
            reward_balance = get_reward_credit_balance(user)
            if reward_balance > 0:
                # Deduct 1 reward credit
                RewardCreditLedger.objects.create(
                    user=user,
                    amount=-1,
                    source="prompt_consumption",
                    status=CreditStatus.COMPLETED,
                    metadata={"consumed_via": source},
                )
                usage.reward_prompts_used += 1
                source_used = "reward"
            else:
                return {
                    "allowed": False,
                    "source_used": None,
                    "free_remaining_today": 0,
                    "reward_credit_balance": 0,
                    "message": "Daily free limit reached and no reward credits available.",
                }

    usage.total_prompts_used += 1
    usage.save()

    # Log the consumption event
    UsageEvent.objects.create(
        user=user,
        event_type=UsageEvent.EventType.CONSUME_PROMPT,
        prompt_count=1,
        metadata={"source": source, "source_used": source_used},
    )

    free_remaining_now = max(0, FREE_DAILY_LIMIT - usage.free_prompts_used)
    reward_balance_now = get_reward_credit_balance(user)

    return {
        "allowed": True,
        "source_used": source_used,
        "free_remaining_today": free_remaining_now,
        "reward_credit_balance": reward_balance_now,
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
