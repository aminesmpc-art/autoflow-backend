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
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        register_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        return Response(
            {"message": "Account created. Please check your email to verify your account."},
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
        token = request.query_params.get("token")
        if not token:
            return Response(
                {"message": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        success, message = verify_email(token)
        if success:
            return Response({"message": message})
        return Response({"message": message}, status=status.HTTP_400_BAD_REQUEST)


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
