"""Auth service — registration, verification token, and email sending."""
import logging
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from apps.plans.models import Profile
from apps.users.models import CustomUser, EmailVerificationToken

logger = logging.getLogger(__name__)


def register_user(email: str, password: str) -> CustomUser:
    """Create user + profile, send verification email in background thread."""
    import threading

    user = CustomUser.objects.create_user(email=email, password=password, is_active=True)
    Profile.objects.create(user=user)
    token = create_verification_token(user)
    # Send email in background thread so registration returns instantly
    threading.Thread(
        target=send_verification_email,
        args=(user, token),
        daemon=True,
    ).start()
    return user


def create_verification_token(user: CustomUser) -> EmailVerificationToken:
    """Create a new verification token for the user."""
    return EmailVerificationToken.objects.create(
        user=user,
        token=EmailVerificationToken.generate_token(),
        expires_at=EmailVerificationToken.default_expiry(),
    )


def verify_email(token_str: str) -> tuple[bool, str]:
    """Verify email with the given token string.

    Returns (success, message).
    """
    try:
        token = EmailVerificationToken.objects.select_related("user").get(token=token_str)
    except EmailVerificationToken.DoesNotExist:
        return False, "Invalid verification token."

    if token.is_used:
        return False, "This token has already been used."

    if token.is_expired:
        return False, "This token has expired. Please request a new one."

    # Activate user and mark token used
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])

    user = token.user
    user.is_active = True
    user.save(update_fields=["is_active"])

    logger.info("Email verified for user %s", user.email)
    return True, "Email verified successfully. You can now log in."


def resend_verification(email: str) -> tuple[bool, str]:
    """Resend verification email for a given email address."""
    try:
        user = CustomUser.objects.get(email=email)
    except CustomUser.DoesNotExist:
        # Don't reveal whether the email exists
        return True, "If this email is registered, a verification link has been sent."

    if user.is_active:
        return True, "This account is already verified."

    token = create_verification_token(user)
    send_verification_email(user, token)
    return True, "If this email is registered, a verification link has been sent."


def send_verification_email(user: CustomUser, token: EmailVerificationToken):
    """Send the verification email with a branded HTML template."""
    try:
        base_url = getattr(settings, "VERIFY_EMAIL_BASE_URL", "http://localhost:3000/verify-email")
        verify_url = f"{base_url}?token={token.token}"
        expiry_hours = getattr(settings, "VERIFICATION_TOKEN_EXPIRY_HOURS", 24)

        subject = "Verify Your Email — AutoFlow"

        # Plain text fallback
        text_message = (
            f"Hi,\n\n"
            f"Welcome to AutoFlow! Please verify your email address by visiting:\n\n"
            f"{verify_url}\n\n"
            f"This link expires in {expiry_hours} hours.\n\n"
            f"If you didn't create an AutoFlow account, you can safely ignore this email.\n\n"
            f"— The AutoFlow Team"
        )

        # Render HTML template (may fail if template is missing)
        try:
            html_message = render_to_string("users/verify_email.html", {
                "verify_url": verify_url,
                "expiry_hours": expiry_hours,
                "year": datetime.now().year,
            })
        except Exception:
            html_message = None

        send_mail(
            subject=subject,
            message=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info("Verification email sent to %s", user.email)
    except Exception as exc:
        logger.error("Failed to send verification email to %s: %s", user.email, exc)

