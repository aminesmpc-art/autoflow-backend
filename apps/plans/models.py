"""Profile model — plan type, entitlement flags, Whop integration fields."""
import uuid

from django.conf import settings
from django.db import models


class PlanType(models.TextChoices):
    FREE = "free", "Free"
    PRO = "pro", "Pro"


class Profile(models.Model):
    """One-to-one extension of User for plan and preference data."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=100, blank=True, default="")
    plan_type = models.CharField(
        max_length=10, choices=PlanType.choices, default=PlanType.FREE
    )
    is_pro_active = models.BooleanField(default=False)
    fair_use_flag = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, blank=True, default="UTC")
    last_seen_at = models.DateTimeField(null=True, blank=True)

    # Whop integration (nullable until connected)
    whop_user_id = models.CharField(max_length=128, null=True, blank=True)
    whop_membership_id = models.CharField(max_length=128, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"

    def __str__(self):
        return f"{self.user.email} ({self.plan_type})"

    @property
    def is_pro(self) -> bool:
        return self.plan_type == PlanType.PRO and self.is_pro_active
