"""Auth service — registration, verification token, and email sending."""
import logging
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from apps.plans.models import Profile
from apps.users.models import CustomUser, EmailVerificationToken, PasswordResetToken

logger = logging.getLogger(__name__)


def register_user(email: str, password: str) -> CustomUser:
    """Create user + profile, send verification email in background thread."""
    import threading

    user = CustomUser.objects.create_user(email=email, password=password, is_active=False)
    Profile.objects.create(user=user)
    token = create_verification_token(user)
    # Send email in background thread so registration returns instantly
    threading.Thread(
        target=send_verification_email,
        args=(user, token),
        daemon=True,
    ).start()

    # Auto-link any pending Whop webhooks (user paid before registering)
    try:
        from apps.webhooks.services import link_pending_webhooks_for_user
        link_pending_webhooks_for_user(user)
    except Exception as exc:
        logger.warning("Failed to auto-link webhooks for %s: %s", email, exc)

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

    # Auto-link any pending Whop webhooks (user paid before registering)
    try:
        from apps.webhooks.services import link_pending_webhooks_for_user
        link_pending_webhooks_for_user(user)
    except Exception as exc:
        logger.warning("Failed to auto-link webhooks on verify for %s: %s", user.email, exc)

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
    """Send the verification email using Resend API."""
    try:
        import resend

        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            logger.warning("RESEND_API_KEY not set — skipping verification email for %s", user.email)
            return

        resend.api_key = api_key

        base_url = getattr(settings, "VERIFY_EMAIL_BASE_URL", "https://api.auto-flow.studio/api/auth/verify-email")
        verify_url = f"{base_url}?token={token.token}"
        expiry_hours = getattr(settings, "VERIFICATION_TOKEN_EXPIRY_HOURS", 24)

        # Plain text fallback
        text_content = (
            f"Hi,\n\n"
            f"Welcome to AutoFlow! Please verify your email:\n\n"
            f"{verify_url}\n\n"
            f"This link expires in {expiry_hours} hours.\n\n"
            f"— The AutoFlow Team"
        )

        # HTML content
        try:
            html_content = render_to_string("users/verify_email.html", {
                "verify_url": verify_url,
                "expiry_hours": expiry_hours,
                "year": datetime.now().year,
            })
        except Exception:
            html_content = None

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "AutoFlow <noreply@auto-flow.studio>")

        params = {
            "from": from_email,
            "to": [user.email],
            "subject": "Verify Your Email — AutoFlow",
            "text": text_content,
        }
        if html_content:
            params["html"] = html_content

        resend.Emails.send(params)
        logger.info("Verification email sent to %s via Resend", user.email)

    except Exception as exc:
        logger.error("Failed to send verification email to %s: %s", user.email, exc)


def request_password_reset(email: str) -> tuple[bool, str]:
    """Request a password reset. Generates a 6-digit code and emails it."""
    try:
        user = CustomUser.objects.get(email=email)
    except CustomUser.DoesNotExist:
        # Avoid user enumeration attacks: return generic success message
        return True, "If this email is registered, a password reset code has been sent."

    # Check if this user is a Google-only user (no password set)
    if not user.has_usable_password():
        return False, "This account uses Google Sign-in. Please log in with Google."

    # Create password reset token
    token = PasswordResetToken.objects.create(
        user=user,
        code=PasswordResetToken.generate_code(),
        expires_at=PasswordResetToken.default_expiry(),
    )

    # Send email in background thread
    import threading
    threading.Thread(
        target=send_password_reset_email,
        args=(user, token),
        daemon=True,
    ).start()

    return True, "If this email is registered, a password reset code has been sent."


def confirm_password_reset(email: str, code: str, new_password: str) -> tuple[bool, str]:
    """Verify reset code and update password."""
    try:
        user = CustomUser.objects.get(email=email)
    except CustomUser.DoesNotExist:
        return False, "Invalid email or reset code."

    # Find the latest valid token for this user and code
    try:
        token = PasswordResetToken.objects.filter(
            user=user,
            code=code,
            used_at__isnull=True,
        ).latest("created_at")
    except PasswordResetToken.DoesNotExist:
        return False, "Invalid email or reset code."

    if token.is_expired:
        return False, "This code has expired. Please request a new one."

    # Mark token as used
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])

    # Update user password
    user.set_password(new_password)
    user.save(update_fields=["password"])

    logger.info("Password successfully reset for user %s", email)
    return True, "Password reset successfully. You can now log in with your new password."


def send_password_reset_email(user: CustomUser, token: PasswordResetToken):
    """Send password reset email containing the 6-digit code."""
    try:
        import resend

        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            logger.warning("RESEND_API_KEY not set — skipping password reset email for %s", user.email)
            return

        resend.api_key = api_key

        # Plain text content
        text_content = (
            f"Hi,\n\n"
            f"You requested a password reset for your AutoFlow account.\n\n"
            f"Your password reset code is: {token.code}\n\n"
            f"This code is valid for 1 hour. If you did not make this request, you can safely ignore this email.\n\n"
            f"— The AutoFlow Team"
        )

        # HTML content
        try:
            html_content = render_to_string("users/password_reset_email.html", {
                "code": token.code,
                "year": datetime.now().year,
            })
        except Exception:
            html_content = None

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "AutoFlow <noreply@auto-flow.studio>")

        params = {
            "from": from_email,
            "to": [user.email],
            "subject": "Reset Your Password — AutoFlow",
            "text": text_content,
        }
        if html_content:
            params["html"] = html_content

        resend.Emails.send(params)
        logger.info("Password reset email sent to %s via Resend", user.email)

    except Exception as exc:
        logger.error("Failed to send password reset email to %s: %s", user.email, exc)


