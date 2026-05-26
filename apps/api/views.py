"""API views — thin controllers that delegate to service layer."""
import logging

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.plans.services import (
    consume_download,
    consume_prompt,
    consume_queue_run,
    get_entitlement_snapshot,
    grant_reward_credits,
    mark_last_seen,
)
from apps.usage.models import UsageEvent
from apps.users.models import CustomUser
from apps.users.services import register_user, resend_verification, verify_email
from apps.webhooks.models import WebhookEvent
from apps.webhooks.services import process_whop_webhook

from .serializers import (
    GrantRewardSerializer,
    LoginSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    UsageEventSerializer,
)

logger = logging.getLogger(__name__)


# ================================================================
# AUTH
# ================================================================


# Disposable/throwaway email domains commonly used by bots
DISPOSABLE_EMAIL_DOMAINS = {
    "mydefipet.live", "bltiwd.com", "m3player.com", "guerrillamail.com",
    "mailinator.com", "tempmail.com", "throwaway.email", "yopmail.com",
    "guerrillamailblock.com", "grr.la", "sharklasers.com", "guerrillamail.info",
    "guerrillamail.net", "guerrillamail.org", "guerrillamail.de",
    "10minutemail.com", "trashmail.com", "tempinbox.com", "fakeinbox.com",
    "dispostable.com", "maildrop.cc", "mailnesia.com", "mailcatch.com",
    "temp-mail.org", "emailondeck.com", "mohmal.com",
}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # Rate limit: max 5 registrations per IP per hour
        from django.core.cache import cache
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")
        cache_key = f"register_rate:{ip}"
        attempts = cache.get(cache_key, 0)
        if attempts >= 5:
            return Response(
                {"detail": "Too many registration attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        cache.set(cache_key, attempts + 1, timeout=3600)  # 1 hour

        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Block disposable email domains
        email = serializer.validated_data["email"].lower()
        domain = email.split("@")[-1] if "@" in email else ""
        if domain in DISPOSABLE_EMAIL_DOMAINS:
            return Response(
                {"detail": "Please use a real email address. Disposable emails are not allowed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            register_user(
                email=email,
                password=serializer.validated_data["password"],
            )
        except Exception as e:
            import traceback
            logger.error("Registration failed: %s\n%s", str(e), traceback.format_exc())
            return Response(
                {"detail": f"Registration failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"message": "Account created! Check your email to verify and log in."},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from django.core.cache import cache
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")
        cache_key = f"login_rate:{ip}"
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 10:
            return Response(
                {"detail": "Too many failed login attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        password = serializer.validated_data["password"]

        # Validate password FIRST — never reveal account existence before auth
        user = authenticate(request, username=email, password=password)
        if user is None:
            cache.set(cache_key, attempts + 1, timeout=300)  # 5 minutes lockout
            # Check if the account exists but is unverified (only after password
            # would have matched — authenticate returns None for inactive users too)
            try:
                user_obj = CustomUser.objects.get(email=email)
                if not user_obj.is_active and user_obj.check_password(password):
                    return Response(
                        {"message": "Please verify your email before logging in."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except CustomUser.DoesNotExist:
                pass
            return Response(
                {"message": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        cache.delete(cache_key)  # clear attempts on success
        mark_last_seen(user)
        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })


class RefreshTokenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"message": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            refresh = RefreshToken(refresh_token)
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            })
        except Exception:
            return Response(
                {"message": "Invalid or expired refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = user.profile
        
        # Self-healing check: if they have an approved review claim but aren't pro
        if not profile.is_pro_active:
            from apps.rewards.models import ReviewRewardClaim
            claim = ReviewRewardClaim.objects.filter(user=user, status="approved").first()
            if claim:
                from django.utils import timezone
                is_expired = claim.pro_granted_until and timezone.now() > claim.pro_granted_until
                
                if not is_expired:
                    from apps.plans.models import PlanType
                    profile.plan_type = PlanType.PRO
                    profile.is_pro_active = True
                    if claim.pro_granted_until:
                        profile.pro_expires_at = claim.pro_granted_until
                    profile.save()
        
        mark_last_seen(user)
        return Response({
            "user": {
                "id": str(user.id),
                "email": user.email,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat(),
            },
            "profile": {
                "plan_type": profile.plan_type,
                "is_pro_active": profile.is_pro,
                "display_name": profile.display_name,
            },
        })


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from django.shortcuts import render

        token = request.query_params.get("token")
        if not token:
            return render(request, "users/verify_result.html", {
                "status_class": "error",
                "icon": "⚠️",
                "title": "Missing Token",
                "message": "No verification token provided. Please use the link from your email.",
            }, status=400)

        success, message = verify_email(token)
        if success:
            return render(request, "users/verify_result.html", {
                "status_class": "success",
                "icon": "✅",
                "title": "Email Verified!",
                "message": "Your email has been verified. You can now log in from the AutoFlow extension.",
            })
        return render(request, "users/verify_result.html", {
            "status_class": "error",
            "icon": "❌",
            "title": "Verification Failed",
            "message": message,
        }, status=400)


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from django.core.cache import cache

        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()

        # Rate limit: max 1 resend per email per 2 minutes
        cache_key = f"resend_rate:{email}"
        if cache.get(cache_key):
            return Response(
                {"message": "Verification email was sent recently. Please wait 2 minutes before requesting again."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        cache.set(cache_key, True, timeout=120)  # 2 minutes

        _, message = resend_verification(email)
        return Response({"message": message})


# ================================================================
# ENTITLEMENTS
# ================================================================


class EntitlementsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        snapshot = get_entitlement_snapshot(request.user)
        return Response(snapshot)


# ================================================================
# USAGE
# ================================================================


class ConsumePromptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        prompt_type = request.data.get("prompt_type", "text")
        prompt_count = int(request.data.get("prompt_count", 1))

        # ── Dedup guard: skip COUNTING if queue_run already pre-consumed ──
        # Old extension versions still call trackUsage() per-prompt AFTER the
        # queue_run pre-consumed them server-side, causing double-counting.
        # We still LOG the event (so admin can see prompt-by-prompt) but
        # don't increment the usage counters.
        from datetime import timedelta
        from django.utils import timezone as tz
        cutoff = tz.now() - timedelta(minutes=30)
        recent_queue_run = UsageEvent.objects.filter(
            user=request.user,
            event_type__startswith="queue_run",
            created_at__gte=cutoff,
        ).exists()

        if recent_queue_run:
            # Log the event for visibility (prompt-by-prompt in admin)
            # but DON'T increment daily usage counters
            UsageEvent.objects.create(
                user=request.user,
                event_type=UsageEvent.EventType.CONSUME_PROMPT,
                prompt_count=1,
                metadata={
                    "source": "extension",
                    "prompt_type": prompt_type,
                    "source_used": "pre_consumed",
                    "dedup": True,
                },
            )
            from apps.plans.services import get_reward_credit_balance
            from apps.plans.services import (
                FREE_TEXT_DAILY_LIMIT, FREE_FULL_DAILY_LIMIT,
                get_or_create_daily_usage,
            )
            today = tz.now().date()
            usage = get_or_create_daily_usage(request.user, today)
            profile = request.user.profile
            return Response({
                "allowed": True,
                "source_used": "pre_consumed",
                "prompt_type": prompt_type,
                "text_remaining_today": max(0, FREE_TEXT_DAILY_LIMIT - usage.free_prompts_used) if not profile.is_pro else 999,
                "full_remaining_today": max(0, FREE_FULL_DAILY_LIMIT - usage.full_prompts_used) if not profile.is_pro else 999,
                "reward_credit_balance": get_reward_credit_balance(request.user),
                "message": "Already tracked via queue run.",
            })

        results = []
        for _ in range(prompt_count):
            result = consume_prompt(request.user, source="extension", prompt_type=prompt_type)
            results.append(result)
            if not result["allowed"]:
                break

        # Return the last result (has current remaining counts)
        final = results[-1]
        http_status = status.HTTP_200_OK if final["allowed"] else status.HTTP_403_FORBIDDEN
        return Response(final, status=http_status)


class ConsumeDownloadView(APIView):
    """Track download consumption server-side. Free users: 20/day."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = int(request.data.get("count", 1))
        if count < 1:
            return Response(
                {"detail": "Count must be at least 1."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = consume_download(request.user, count=count)
        http_status = status.HTTP_200_OK if result["allowed"] else status.HTTP_403_FORBIDDEN
        return Response(result, status=http_status)


class UsageEventView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UsageEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UsageEvent.objects.create(
            user=request.user,
            event_type=serializer.validated_data["event_type"],
            prompt_count=serializer.validated_data.get("prompt_count", 0),
            metadata=serializer.validated_data.get("metadata", {}),
        )
        return Response({"message": "Event recorded."}, status=status.HTTP_201_CREATED)


class ConsumeQueueRunView(APIView):
    """Check + consume a queue run for a given automation mode (lite/flow/full)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        mode = request.data.get("mode", "lite")
        if mode not in ("lite", "flow", "full"):
            return Response(
                {"detail": f"Invalid mode: {mode}. Must be lite, flow, or full."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        prompt_count = int(request.data.get("prompt_count", 1))
        prompt_type = request.data.get("prompt_type", "text")
        if prompt_type not in ("text", "full"):
            prompt_type = "text"
        # Mixed queue support: per-type counts
        text_count = request.data.get("text_count")
        full_count = request.data.get("full_count")
        if text_count is not None and full_count is not None:
            text_count = int(text_count)
            full_count = int(full_count)
        else:
            text_count = None
            full_count = None
        result = consume_queue_run(
            request.user, mode=mode, prompt_count=prompt_count,
            prompt_type=prompt_type, text_count=text_count, full_count=full_count,
        )
        http_status = status.HTTP_200_OK if result["allowed"] else status.HTTP_403_FORBIDDEN
        return Response(result, status=http_status)


# ================================================================
# REWARDS
# ================================================================


class GrantRewardView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = GrantRewardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = CustomUser.objects.get(email=serializer.validated_data["user_email"])
        except CustomUser.DoesNotExist:
            return Response(
                {"message": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        entry = grant_reward_credits(
            user=user,
            amount=serializer.validated_data["amount"],
            source=serializer.validated_data["source"],
            reference_id=serializer.validated_data.get("reference_id"),
            metadata=serializer.validated_data.get("metadata", {}),
        )
        return Response({
            "message": "Reward credits granted.",
            "entry_id": str(entry.id),
            "amount": entry.amount,
        }, status=status.HTTP_201_CREATED)


class ClaimReviewRewardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.rewards.models import ReviewRewardClaim
        from .serializers import ClaimReviewRewardSerializer

        serializer = ClaimReviewRewardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviewer_name = serializer.validated_data["reviewer_name"]

        # ── Eligibility gate: must have real usage in last 7 days ──
        # 50+ confirmed text prompts OR 20+ confirmed full (image) prompts
        from apps.usage.models import UsageEvent
        from django.utils import timezone
        from django.db.models import Sum, Q
        from datetime import timedelta

        seven_days_ago = timezone.now() - timedelta(days=7)
        events = UsageEvent.objects.filter(
            user=request.user,
            event_type="consume_prompt",
            created_at__gte=seven_days_ago,
        )
        total_confirmed = events.aggregate(s=Sum("prompt_count"))["s"] or 0
        full_confirmed = events.filter(
            metadata__prompt_type="full"
        ).aggregate(s=Sum("prompt_count"))["s"] or 0

        if total_confirmed < 50 and full_confirmed < 20:
            return Response({
                "status": "ineligible",
                "message": f"You need at least 50 prompts or 20 image prompts in the last 7 days to claim a reward. "
                           f"You have {total_confirmed} text and {full_confirmed} image prompts.",
            }, status=status.HTTP_403_FORBIDDEN)

        claim = ReviewRewardClaim.objects.filter(user=request.user).first()
        
        if not claim:
            claim = ReviewRewardClaim.objects.create(
                user=request.user,
                reviewer_name=reviewer_name
            )
        elif claim.status == "pending":
            # Allow updating the name if it's still pending
            claim.reviewer_name = reviewer_name
            claim.save(update_fields=["reviewer_name"])

        return Response({
            "status": claim.status,
            "message": "Under review" if claim.status == "pending" else claim.status
        })


class ReviewRewardStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.rewards.models import ReviewRewardClaim

        claim = ReviewRewardClaim.objects.filter(user=request.user).first()
        if not claim:
            return Response({"status": "none"})
            
        # Self-healing: If claim is approved but profile is not pro, and the claim hasn't expired, fix the profile
        from django.utils import timezone
        is_expired = claim.pro_granted_until and timezone.now() > claim.pro_granted_until
        
        if claim.status == "approved" and not request.user.profile.is_pro_active and not is_expired:
            from apps.plans.models import PlanType
            profile = request.user.profile
            profile.plan_type = PlanType.PRO
            profile.is_pro_active = True
            if claim.pro_granted_until:
                profile.pro_expires_at = claim.pro_granted_until
            profile.save()
            
        return Response({
            "status": claim.status,
            "pro_until": claim.pro_granted_until.isoformat() if claim.pro_granted_until else None
        })


# ================================================================
# WEBHOOKS
# ================================================================


class WhopWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        import base64
        import hashlib
        import hmac
        import time

        from django.conf import settings

        raw_body = request.body

        # ── 1. Verify Webhook Signature (Standard Webhooks spec) ──
        webhook_id = request.META.get("HTTP_WEBHOOK_ID", "")
        webhook_signature = request.META.get("HTTP_WEBHOOK_SIGNATURE", "")
        webhook_timestamp = request.META.get("HTTP_WEBHOOK_TIMESTAMP", "")

        secret = getattr(settings, "WHOP_WEBHOOK_SECRET", "")

        if not secret:
            logger.error("WHOP_WEBHOOK_SECRET not configured")
            return Response(
                {"error": "Server misconfiguration"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not webhook_signature or not webhook_timestamp:
            logger.warning("Whop webhook missing signature or timestamp headers")
            return Response(
                {"error": "Missing signature headers"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Replay protection: reject if timestamp is older than 5 minutes
        try:
            ts = int(webhook_timestamp)
            if abs(time.time() - ts) > 300:
                logger.warning("Whop webhook timestamp too old: %s", webhook_timestamp)
                return Response(
                    {"error": "Timestamp too old"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid timestamp"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Compute expected signature: HMAC-SHA256(secret, "msg_id.timestamp.body")
        # Standard Webhooks secret may be base64-encoded with "whsec_" prefix
        signing_secret = secret
        if signing_secret.startswith("whsec_"):
            signing_secret = signing_secret[6:]
        try:
            secret_bytes = base64.b64decode(signing_secret)
        except Exception:
            secret_bytes = signing_secret.encode("utf-8")

        signed_content = f"{webhook_id}.{webhook_timestamp}.".encode("utf-8") + raw_body
        expected_sig = base64.b64encode(
            hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
        ).decode("utf-8")

        # webhook-signature header can contain multiple "v1,<sig>" entries
        valid = False
        for sig_part in webhook_signature.split(" "):
            if sig_part.startswith("v1,"):
                provided_sig = sig_part[3:]
                if hmac.compare_digest(expected_sig, provided_sig):
                    valid = True
                    break

        if not valid:
            logger.warning("Whop webhook signature mismatch")
            return Response(
                {"error": "Invalid signature"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── 2. Parse payload ──
        payload = request.data
        event_type = payload.get("type", "unknown")
        external_id = payload.get("id", "") or webhook_id

        # ── 3. Idempotency: skip if already processed ──
        if external_id and WebhookEvent.objects.filter(
            external_event_id=external_id, processed=True
        ).exists():
            logger.info("Skipping duplicate Whop webhook: %s", external_id)
            return Response({"received": True, "duplicate": True}, status=status.HTTP_200_OK)

        # ── 4. Store and process ──
        event = WebhookEvent.objects.create(
            provider="whop",
            external_event_id=external_id,
            event_type=event_type,
            raw_payload=payload,
        )

        process_whop_webhook(event)

        return Response({"received": True}, status=status.HTTP_200_OK)


# ================================================================
# HEALTH
# ================================================================


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "autoflow-backend"})




# ================================================================
# EXTRACTIONS
# ================================================================


class PublicExtractionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.extractions.models import SavedExtraction
        from .serializers import SavedExtractionSerializer
        
        # Get the 50 most recent extractions
        extractions = SavedExtraction.objects.all().order_by("-created_at")[:50]
        serializer = SavedExtractionSerializer(extractions, many=True)
        return Response(serializer.data)


class PublicExtractionDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        from apps.extractions.models import SavedExtraction
        from .serializers import SavedExtractionSerializer
        from django.shortcuts import get_object_or_404
        
        extraction = get_object_or_404(SavedExtraction, pk=pk)
        serializer = SavedExtractionSerializer(extraction)
        return Response(serializer.data)


class SavedExtractionCheckLimitView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.extractions.models import SavedExtraction
        from django.utils import timezone
        
        user = request.user
        profile = getattr(user, "profile", None)
        is_pro = profile.is_pro if profile else False
        
        now = timezone.now()
        
        if is_pro:
            # PRO: 20 per day
            count = SavedExtraction.objects.filter(
                user=user,
                created_at__year=now.year,
                created_at__month=now.month,
                created_at__day=now.day
            ).count()
            limit = 20
            period = "day"
        else:
            # FREE: 4 per month
            count = SavedExtraction.objects.filter(
                user=user,
                created_at__year=now.year,
                created_at__month=now.month
            ).count()
            limit = 4
            period = "month"
            
        allowed = count < limit
        remaining = max(0, limit - count)
        
        return Response({
            "allowed": allowed,
            "used": count,
            "limit": limit,
            "remaining": remaining,
            "period": period,
            "is_pro": is_pro
        })


class SavedExtractionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.extractions.models import SavedExtraction
        from .serializers import SavedExtractionSerializer
        
        extractions = SavedExtraction.objects.filter(user=request.user)
        serializer = SavedExtractionSerializer(extractions, many=True)
        return Response(serializer.data)

    def post(self, request):
        from .serializers import SavedExtractionSerializer
        
        serializer = SavedExtractionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Save to database
        serializer.save(user=request.user)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SavedExtractionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        from apps.extractions.models import SavedExtraction
        
        try:
            extraction = SavedExtraction.objects.get(pk=pk, user=request.user)
            extraction.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except SavedExtraction.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
