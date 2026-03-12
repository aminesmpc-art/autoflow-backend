"""Whop webhook processing service."""
import logging

from django.utils import timezone

from apps.plans.services import sync_profile_plan
from apps.users.models import CustomUser
from apps.webhooks.models import WebhookEvent

logger = logging.getLogger(__name__)


def process_whop_webhook(event: WebhookEvent):
    """Process a Whop webhook event.

    Currently handles:
    - membership.went_valid → activate pro
    - membership.went_invalid → deactivate pro
    - membership.cancelled → deactivate pro

    This is a starter implementation; extend as Whop integration matures.
    """
    payload = event.raw_payload
    event_type = event.event_type

    try:
        # Extract user email from Whop payload (structure depends on Whop API)
        user_email = payload.get("data", {}).get("email")
        membership_id = payload.get("data", {}).get("id", "")

        if not user_email:
            logger.warning("Whop webhook missing user email: %s", event.id)
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
            return

        try:
            user = CustomUser.objects.get(email=user_email)
            event.linked_user = user
        except CustomUser.DoesNotExist:
            logger.warning("Whop webhook: user not found %s", user_email)
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
            return

        if event_type in ("membership.went_valid",):
            sync_profile_plan(
                user,
                plan_type="pro",
                is_pro_active=True,
                whop_membership_id=membership_id,
            )
            logger.info("Pro activated for %s via Whop", user_email)

        elif event_type in ("membership.went_invalid", "membership.cancelled"):
            sync_profile_plan(
                user,
                plan_type="free",
                is_pro_active=False,
            )
            logger.info("Pro deactivated for %s via Whop", user_email)

        else:
            logger.info("Unhandled Whop event type: %s", event_type)

        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["processed", "processed_at", "linked_user"])

    except Exception as exc:
        logger.exception("Error processing Whop webhook %s: %s", event.id, exc)
