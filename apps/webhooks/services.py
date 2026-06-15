"""Whop webhook processing service."""
import logging

from django.utils import timezone

from apps.plans.services import sync_profile_plan
from apps.users.models import CustomUser
from apps.webhooks.models import WebhookEvent

logger = logging.getLogger(__name__)


# ── Event type constants ──

ACTIVATION_EVENTS = (
    "membership.went_valid",
    "membership_went_valid",
    "membership.activated",
    "membership_activated",
    "membership.valid",
)
DEACTIVATION_EVENTS = (
    "membership.went_invalid",
    "membership_went_invalid",
    "membership.cancelled",
    "membership_cancelled",
    "membership.deactivated",
    "membership_deactivated",
    "membership.expired",
    "membership_expired",
)


def _extract_whop_payload(payload: dict) -> dict:
    """Extract email, membership_id, and whop_user_id from a Whop webhook payload.

    Handles both flat and nested payload structures.
    Returns a dict with keys: email, membership_id, whop_user_id.
    """
    data = payload.get("data", {})

    # Email: try multiple locations
    email = (
        data.get("email")
        or data.get("user_email")
        or data.get("user", {}).get("email")
        or data.get("customer", {}).get("email")
    )

    # Membership ID: try direct 'id' (for membership events) and nested 'membership.id' (for payment events)
    membership_id = ""
    if data.get("id", "").startswith("mem_"):
        membership_id = data["id"]
    elif isinstance(data.get("membership"), dict):
        membership_id = data["membership"].get("id", "")
    elif data.get("membership_id"):
        membership_id = data["membership_id"]

    # Whop user ID
    whop_user_id = (
        data.get("user_id", "")
        or data.get("user", {}).get("id", "")
    )

    return {
        "email": email.lower().strip() if email else None,
        "membership_id": membership_id,
        "whop_user_id": whop_user_id,
    }


def process_whop_webhook(event: WebhookEvent):
    """Process a Whop webhook event.

    Handles:
    - membership.activated / went_valid → activate pro
    - membership.deactivated / went_invalid / cancelled → deactivate pro
    - payment.succeeded → log payment (no plan change)

    If the user email is not found in our system, the webhook is stored
    but NOT marked as processed, so it can be retried when the user registers.
    """
    payload = event.raw_payload
    event_type = event.event_type

    try:
        extracted = _extract_whop_payload(payload)
        user_email = extracted["email"]
        membership_id = extracted["membership_id"]
        whop_user_id = extracted["whop_user_id"]

        if not user_email:
            logger.warning(
                "Whop webhook missing user email: %s (type: %s, keys: %s)",
                event.id, event_type, list(payload.get("data", {}).keys()),
            )
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
            return

        try:
            user = CustomUser.objects.get(email=user_email)
            event.linked_user = user
        except CustomUser.DoesNotExist:
            # User hasn't registered yet — keep webhook UNPROCESSED
            # so it can be picked up when they register
            logger.info(
                "Whop webhook: user %s not found yet (type: %s). "
                "Will auto-link when they register.",
                user_email, event_type,
            )
            # DON'T mark as processed — leave it for auto-linking on registration
            return

        if event_type in ACTIVATION_EVENTS:
            sync_profile_plan(
                user,
                plan_type="pro",
                is_pro_active=True,
                whop_membership_id=membership_id,
                whop_user_id=whop_user_id,
            )
            logger.info("Pro activated for %s via Whop (membership: %s)", user_email, membership_id)

        elif event_type in DEACTIVATION_EVENTS:
            sync_profile_plan(
                user,
                plan_type="free",
                is_pro_active=False,
            )
            logger.info("Pro deactivated for %s via Whop (event: %s)", user_email, event_type)

        elif event_type == "payment.succeeded":
            # Also store membership_id from payment events
            if membership_id:
                from apps.plans.models import Profile
                Profile.objects.filter(user=user, whop_membership_id__in=["", None]).update(
                    whop_membership_id=membership_id,
                )
            logger.info("Payment succeeded for %s (amount: %s)", user_email, payload.get("data", {}).get("total", "?"))

        else:
            logger.info("Unhandled Whop event type: %s", event_type)

        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["processed", "processed_at", "linked_user"])

    except Exception as exc:
        logger.exception("Error processing Whop webhook %s: %s", event.id, exc)


def link_pending_webhooks_for_user(user: CustomUser):
    """Check for unprocessed Whop webhooks matching this user's email.

    Called during registration/verification to auto-activate Pro
    for users who paid on Whop before creating an AutoFlow account.
    """
    # Find unprocessed webhooks that match this user's email
    unprocessed = WebhookEvent.objects.filter(
        provider="whop",
        processed=False,
        linked_user__isnull=True,
    )

    linked_count = 0
    for event in unprocessed:
        extracted = _extract_whop_payload(event.raw_payload)
        if extracted["email"] and extracted["email"] == user.email.lower().strip():
            event.linked_user = user
            linked_count += 1

            # Process the event now
            if event.event_type in ACTIVATION_EVENTS:
                sync_profile_plan(
                    user,
                    plan_type="pro",
                    is_pro_active=True,
                    whop_membership_id=extracted["membership_id"],
                    whop_user_id=extracted["whop_user_id"],
                )
                logger.info(
                    "Auto-linked: Pro activated for %s from pending webhook (membership: %s)",
                    user.email, extracted["membership_id"],
                )

            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at", "linked_user"])

    if linked_count:
        logger.info("Auto-linked %d pending webhook(s) for %s", linked_count, user.email)

    return linked_count
