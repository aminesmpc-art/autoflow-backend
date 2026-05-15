"""Whop webhook processing service."""
import logging

from django.utils import timezone

from apps.plans.services import sync_profile_plan
from apps.users.models import CustomUser
from apps.webhooks.models import WebhookEvent

logger = logging.getLogger(__name__)


def process_whop_webhook(event: WebhookEvent):
    """Process a Whop webhook event.

    Handles:
    - membership.went_valid → activate pro
    - membership.went_invalid → deactivate pro
    - membership.cancelled → deactivate pro
    - payment.succeeded → log payment (no plan change)
    """
    payload = event.raw_payload
    event_type = event.event_type

    try:
        data = payload.get("data", {})

        # Whop sends user email in different locations depending on event type
        user_email = (
            data.get("email")
            or data.get("user", {}).get("email")
            or data.get("customer", {}).get("email")
        )
        membership_id = (
            data.get("id", "")
            or data.get("membership", {}).get("id", "")
        )
        whop_user_id = (
            data.get("user_id", "")
            or data.get("user", {}).get("id", "")
        )

        if not user_email:
            logger.warning("Whop webhook missing user email: %s (type: %s)", event.id, event_type)
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
            return

        try:
            user = CustomUser.objects.get(email=user_email)
            event.linked_user = user
        except CustomUser.DoesNotExist:
            logger.warning("Whop webhook: user not found %s (type: %s)", user_email, event_type)
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
            return

        # ── Activation events ──
        activation_events = (
            "membership.went_valid",
            "membership_went_valid",
            "membership.activated",
            "membership_activated",
            "membership.valid",
        )
        # ── Deactivation events ──
        deactivation_events = (
            "membership.went_invalid",
            "membership_went_invalid",
            "membership.cancelled",
            "membership_cancelled",
            "membership.deactivated",
            "membership_deactivated",
            "membership.expired",
            "membership_expired",
        )

        if event_type in activation_events:
            sync_profile_plan(
                user,
                plan_type="pro",
                is_pro_active=True,
                whop_membership_id=membership_id,
                whop_user_id=whop_user_id,
            )
            logger.info("Pro activated for %s via Whop (membership: %s)", user_email, membership_id)

        elif event_type in deactivation_events:
            sync_profile_plan(
                user,
                plan_type="free",
                is_pro_active=False,
            )
            logger.info("Pro deactivated for %s via Whop (event: %s)", user_email, event_type)

        elif event_type == "payment.succeeded":
            logger.info("Payment succeeded for %s (amount: %s)", user_email, data.get("amount", "?"))

        else:
            logger.info("Unhandled Whop event type: %s", event_type)

        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["processed", "processed_at", "linked_user"])

    except Exception as exc:
        logger.exception("Error processing Whop webhook %s: %s", event.id, exc)

