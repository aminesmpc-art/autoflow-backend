"""
Comprehensive tests for the AutoFlow backend.

Covers: auth flow, email verification, entitlements, usage consumption,
reward credits, and webhook processing.
"""
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.plans.models import PlanType, Profile
from apps.plans.services import (
    FREE_DAILY_LIMIT,
    consume_prompt,
    get_entitlement_snapshot,
    get_free_remaining,
    get_reward_credit_balance,
    grant_reward_credits,
)
from apps.rewards.models import RewardCreditLedger
from apps.usage.models import DailyUsage
from apps.users.models import CustomUser, EmailVerificationToken
from apps.users.services import create_verification_token, register_user, verify_email


# ================================================================
# AUTH & VERIFICATION TESTS
# ================================================================


class RegistrationTests(TestCase):
    """Test user registration flow."""

    @patch("apps.users.services.send_mail")
    def test_register_creates_inactive_user(self, mock_mail):
        user = register_user("test@example.com", "securepass123")
        self.assertFalse(user.is_active)
        self.assertEqual(user.email, "test@example.com")

    @patch("apps.users.services.send_mail")
    def test_register_creates_profile(self, mock_mail):
        user = register_user("test@example.com", "securepass123")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.plan_type, PlanType.FREE)

    @patch("apps.users.services.send_mail")
    def test_register_creates_verification_token(self, mock_mail):
        user = register_user("test@example.com", "securepass123")
        tokens = EmailVerificationToken.objects.filter(user=user)
        self.assertEqual(tokens.count(), 1)

    @patch("apps.users.services.send_mail")
    def test_register_sends_verification_email(self, mock_mail):
        register_user("test@example.com", "securepass123")
        mock_mail.assert_called_once()
        call_kwargs = mock_mail.call_args
        self.assertIn("test@example.com", call_kwargs[1]["recipient_list"])


class EmailVerificationTests(TestCase):
    """Test email verification token logic."""

    def setUp(self):
        self.user = CustomUser.objects.create_user("test@example.com", "pass123")
        self.user.is_active = False
        self.user.save()
        Profile.objects.create(user=self.user)

    def test_verify_email_activates_user(self):
        token = create_verification_token(self.user)
        success, _ = verify_email(token.token)
        self.assertTrue(success)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_expired_token_fails(self):
        token = create_verification_token(self.user)
        token.expires_at = timezone.now() - timedelta(hours=1)
        token.save()
        success, message = verify_email(token.token)
        self.assertFalse(success)
        self.assertIn("expired", message.lower())

    def test_used_token_cannot_be_reused(self):
        token = create_verification_token(self.user)
        verify_email(token.token)  # First use
        success, message = verify_email(token.token)  # Second use
        self.assertFalse(success)
        self.assertIn("already been used", message.lower())

    def test_invalid_token_fails(self):
        success, message = verify_email("nonexistent-token")
        self.assertFalse(success)
        self.assertIn("invalid", message.lower())

    def test_resend_verification_creates_new_token(self):
        create_verification_token(self.user)
        token2 = create_verification_token(self.user)
        tokens = EmailVerificationToken.objects.filter(user=self.user)
        self.assertEqual(tokens.count(), 2)
        self.assertNotEqual(tokens.first().token, tokens.last().token)


class LoginTests(TestCase):
    """Test login behavior."""

    def setUp(self):
        self.client = APIClient()

    @patch("apps.users.services.send_mail")
    def test_unverified_user_cannot_login(self, mock_mail):
        register_user("test@example.com", "securepass123")
        response = self.client.post("/api/auth/login", {
            "email": "test@example.com",
            "password": "securepass123",
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn("verify", response.data["message"].lower())

    @patch("apps.users.services.send_mail")
    def test_verified_user_can_login(self, mock_mail):
        user = register_user("test@example.com", "securepass123")
        token = EmailVerificationToken.objects.filter(user=user).first()
        verify_email(token.token)
        response = self.client.post("/api/auth/login", {
            "email": "test@example.com",
            "password": "securepass123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)


# ================================================================
# ENTITLEMENT & USAGE TESTS
# ================================================================


class EntitlementTests(TestCase):
    """Test entitlement snapshot and consumption logic."""

    def setUp(self):
        self.user = CustomUser.objects.create_user("test@example.com", "pass123", is_active=True)
        self.profile = Profile.objects.create(user=self.user, plan_type=PlanType.FREE)

    def test_free_user_has_daily_limit(self):
        remaining = get_free_remaining(self.user)
        self.assertEqual(remaining, FREE_DAILY_LIMIT)

    def test_snapshot_returns_correct_data(self):
        snapshot = get_entitlement_snapshot(self.user)
        self.assertEqual(snapshot["plan_type"], "free")
        self.assertFalse(snapshot["is_pro_active"])
        self.assertEqual(snapshot["free_daily_limit"], FREE_DAILY_LIMIT)
        self.assertEqual(snapshot["free_remaining_today"], FREE_DAILY_LIMIT)
        self.assertTrue(snapshot["can_run_prompt"])

    def test_free_user_can_consume_prompt(self):
        result = consume_prompt(self.user)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["source_used"], "free")
        self.assertEqual(result["free_remaining_today"], FREE_DAILY_LIMIT - 1)

    def test_free_user_exhausting_daily_limit(self):
        for i in range(FREE_DAILY_LIMIT):
            result = consume_prompt(self.user)
            self.assertTrue(result["allowed"])

        # 31st prompt should fail
        result = consume_prompt(self.user)
        self.assertFalse(result["allowed"])

    def test_free_user_uses_reward_credits_after_limit(self):
        # Exhaust free limit
        for _ in range(FREE_DAILY_LIMIT):
            consume_prompt(self.user)

        # Grant reward credits
        grant_reward_credits(self.user, 5, "test_grant")

        # Should now use reward credits
        result = consume_prompt(self.user)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["source_used"], "reward")

    def test_pro_user_always_allowed(self):
        self.profile.plan_type = PlanType.PRO
        self.profile.is_pro_active = True
        self.profile.save()

        for _ in range(50):  # way beyond free limit
            result = consume_prompt(self.user)
            self.assertTrue(result["allowed"])
            self.assertEqual(result["source_used"], "pro")


class RewardCreditTests(TestCase):
    """Test reward credit granting and idempotency."""

    def setUp(self):
        self.user = CustomUser.objects.create_user("test@example.com", "pass123", is_active=True)
        Profile.objects.create(user=self.user)

    def test_grant_reward_credits(self):
        grant_reward_credits(self.user, 10, "test")
        balance = get_reward_credit_balance(self.user)
        self.assertEqual(balance, 10)

    def test_duplicate_grant_blocked_by_reference_id(self):
        entry1 = grant_reward_credits(self.user, 10, "test", reference_id="ref-001")
        entry2 = grant_reward_credits(self.user, 10, "test", reference_id="ref-001")
        self.assertEqual(entry1.id, entry2.id)  # Same entry returned
        balance = get_reward_credit_balance(self.user)
        self.assertEqual(balance, 10)  # Not doubled

    def test_negative_grant_rejected(self):
        with self.assertRaises(ValueError):
            grant_reward_credits(self.user, -5, "test")


# ================================================================
# API ENDPOINT TESTS
# ================================================================


class APIEndpointTests(TestCase):
    """Test API endpoints via the test client."""

    def setUp(self):
        self.client = APIClient()
        self.user = CustomUser.objects.create_user(
            "api@example.com", "testpass123", is_active=True
        )
        Profile.objects.create(user=self.user)

    def _login(self):
        response = self.client.post("/api/auth/login", {
            "email": "api@example.com",
            "password": "testpass123",
        })
        token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ok")

    def test_entitlements_requires_auth(self):
        response = self.client.get("/api/entitlements")
        self.assertEqual(response.status_code, 401)

    def test_entitlements_returns_snapshot(self):
        self._login()
        response = self.client.get("/api/entitlements")
        self.assertEqual(response.status_code, 200)
        self.assertIn("plan_type", response.data)
        self.assertIn("can_run_prompt", response.data)
        self.assertIn("free_remaining_today", response.data)

    def test_consume_endpoint(self):
        self._login()
        response = self.client.post("/api/usage/consume")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["allowed"])

    def test_usage_events_endpoint(self):
        self._login()
        response = self.client.post("/api/usage/events", {
            "event_type": "queue_started",
            "prompt_count": 3,
        })
        self.assertEqual(response.status_code, 201)

    def test_register_endpoint(self):
        with patch("apps.users.services.send_mail"):
            response = self.client.post("/api/auth/register", {
                "email": "new@example.com",
                "password": "securepass123",
            })
        self.assertEqual(response.status_code, 201)

    def test_me_endpoint(self):
        self._login()
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["email"], "api@example.com")


class WebhookTests(TestCase):
    """Test webhook event storage and processing."""

    def test_whop_webhook_stores_event(self):
        client = APIClient()
        response = client.post("/api/webhooks/whop", {
            "type": "membership.went_valid",
            "id": "evt_123",
            "data": {"email": "nobody@example.com", "id": "mem_456"},
        }, format="json")
        self.assertEqual(response.status_code, 200)

        from apps.webhooks.models import WebhookEvent
        self.assertEqual(WebhookEvent.objects.count(), 1)
        event = WebhookEvent.objects.first()
        self.assertEqual(event.event_type, "membership.went_valid")
        self.assertTrue(event.processed)
