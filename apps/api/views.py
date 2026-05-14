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
        try:
            register_user(
                email=serializer.validated_data["email"],
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

        # Check if user exists but is unverified
        try:
            user_obj = CustomUser.objects.get(email=email)
            if not user_obj.is_active:
                return Response(
                    {"message": "Please verify your email before logging in."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except CustomUser.DoesNotExist:
            pass

        user = authenticate(request, username=email, password=password)
        if user is None:
            cache.set(cache_key, attempts + 1, timeout=300)  # 5 minutes lockout
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
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, message = resend_verification(serializer.validated_data["email"])
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


class DiagnosticView(APIView):
    """Temporary endpoint to debug admin 500 error. Remove after fixing."""
    permission_classes = [AllowAny]

    def get(self, request):
        import traceback
        results = {}

        # Test 1: DB connection
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            results["db_connection"] = "OK"
        except Exception as e:
            results["db_connection"] = f"FAIL: {e}"

        # Test 2: Session table
        try:
            from django.contrib.sessions.models import Session
            Session.objects.count()
            results["session_table"] = "OK"
        except Exception as e:
            results["session_table"] = f"FAIL: {e}"

        # Test 3: User exists
        try:
            user = CustomUser.objects.filter(is_superuser=True).first()
            results["superuser"] = f"OK: {user.email}" if user else "FAIL: no superuser found"
        except Exception as e:
            results["superuser"] = f"FAIL: {e}"

        # Test 4: Authenticate
        try:
            user = authenticate(username="admin@auto-flow.studio", password="AutoFlow2026!")
            results["auth"] = f"OK: {user}" if user else "FAIL: returned None"
        except Exception as e:
            results["auth"] = f"FAIL: {traceback.format_exc()}"

        # Test 5: CSRF settings
        from django.conf import settings
        results["csrf_trusted_origins"] = getattr(settings, "CSRF_TRUSTED_ORIGINS", "NOT SET")
        results["secure_proxy_ssl_header"] = str(getattr(settings, "SECURE_PROXY_SSL_HEADER", "NOT SET"))
        results["debug"] = settings.DEBUG
        results["static_root"] = str(getattr(settings, "STATIC_ROOT", "NOT SET"))
        results["staticfiles_storage"] = str(getattr(settings, "STATICFILES_STORAGE", "NOT SET"))

        # Test 6: Static files manifest
        try:
            from django.contrib.staticfiles.storage import staticfiles_storage
            if hasattr(staticfiles_storage, 'read_manifest'):
                manifest = staticfiles_storage.read_manifest()
                results["static_manifest"] = "OK" if manifest else "EMPTY"
            else:
                results["static_manifest"] = "N/A (no manifest storage)"
        except Exception as e:
            results["static_manifest"] = f"FAIL: {e}"

        # Test 7: Show actual database config
        db_conf = settings.DATABASES.get("default", {})
        results["db_engine"] = db_conf.get("ENGINE", "NOT SET")
        results["db_name"] = db_conf.get("NAME", "NOT SET")
        results["db_host"] = db_conf.get("HOST", "NOT SET")

        # Test 8: List existing tables
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                tables = [row[0] for row in cursor.fetchall()]
            results["existing_tables"] = tables if tables else "NO TABLES FOUND"
        except Exception as e:
            results["existing_tables"] = f"FAIL: {e}"

        # Test 9: Email config (no send test - it causes worker timeout)
        results["email_backend"] = settings.EMAIL_BACKEND
        results["email_host"] = settings.EMAIL_HOST
        results["email_port"] = settings.EMAIL_PORT
        results["email_use_ssl"] = getattr(settings, "EMAIL_USE_SSL", False)
        results["email_use_tls"] = settings.EMAIL_USE_TLS

        return Response(results)


class RunMigrateView(APIView):
    """Temporary endpoint to trigger migrations. Remove after fixing."""
    permission_classes = [AllowAny]

    def get(self, request):
        import io
        from django.core.management import call_command

        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            call_command("migrate", "--noinput", verbosity=2, stdout=stdout, stderr=stderr)
            call_command("collectstatic", "--noinput", stdout=stdout, stderr=stderr)
            call_command("ensure_superuser", stdout=stdout, stderr=stderr)
            return Response({
                "status": "OK",
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            })
        except Exception as e:
            import traceback
            return Response({
                "status": "FAIL",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            })

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
