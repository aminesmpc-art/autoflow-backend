"""API views — thin controllers that delegate to service layer."""
import logging

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.plans.services import (
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
            return Response(
                {"message": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

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
                "is_pro_active": profile.is_pro_active,
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
        result = consume_prompt(request.user, source="extension")
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


# ================================================================
# WEBHOOKS
# ================================================================


class WhopWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # TODO: Verify Whop signature (placeholder for now)
        payload = request.data
        event_type = payload.get("type", "unknown")
        external_id = payload.get("id", "")

        # Store raw event
        event = WebhookEvent.objects.create(
            provider="whop",
            external_event_id=external_id,
            event_type=event_type,
            raw_payload=payload,
        )

        # Process
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
