"""API URL routing."""
from django.urls import path

from . import views

urlpatterns = [
    # Auth
    path("auth/register", views.RegisterView.as_view(), name="auth-register"),
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh", views.RefreshTokenView.as_view(), name="auth-refresh"),
    path("auth/me", views.MeView.as_view(), name="auth-me"),
    path("auth/verify-email", views.VerifyEmailView.as_view(), name="auth-verify-email"),
    path("auth/resend-verification", views.ResendVerificationView.as_view(), name="auth-resend-verification"),

    # Entitlements
    path("entitlements", views.EntitlementsView.as_view(), name="entitlements"),

    # Usage
    path("usage/consume", views.ConsumePromptView.as_view(), name="usage-consume"),
    path("usage/events", views.UsageEventView.as_view(), name="usage-events"),

    # Rewards
    path("rewards/grant", views.GrantRewardView.as_view(), name="rewards-grant"),

    # Webhooks
    path("webhooks/whop", views.WhopWebhookView.as_view(), name="webhooks-whop"),

    # Health
    path("health", views.HealthView.as_view(), name="health"),
]
