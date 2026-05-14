"""Reward credit ledger — tracks grants and consumptions."""
import uuid

from django.conf import settings
from django.db import models


class CreditStatus(models.TextChoices):
    COMPLETED = "completed", "Completed"
    PENDING = "pending", "Pending"
    REVERSED = "reversed", "Reversed"


class RewardCreditLedger(models.Model):
    """Ledger-style model for reward credit transactions.

    Positive amounts = grants, negative amounts = consumptions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reward_credits",
    )
    amount = models.IntegerField(help_text="Positive = grant, negative = consumption")
    source = models.CharField(
        max_length=50,
        db_index=True,
        help_text="e.g. rewarded_ad, manual_grant, prompt_consumption",
    )
    status = models.CharField(
        max_length=20, choices=CreditStatus.choices, default=CreditStatus.COMPLETED
    )
    reference_id = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_index=True,
        help_text="Idempotency key — prevents duplicate grants",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "reward credit entry"
        verbose_name_plural = "reward credit entries"

    def __str__(self):
        sign = "+" if self.amount > 0 else ""
        return f"{self.user.email} {sign}{self.amount} ({self.source})"


class ReviewClaimStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ReviewRewardClaim(models.Model):
    """Tracks review-for-pro claims. One per user, ever.

    User leaves a 5-star review on Chrome Web Store → clicks 'I left my review'
    → this record is created with status=pending → admin approves from Django admin
    → user gets 1 month of Pro.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_claim",
    )
    status = models.CharField(
        max_length=20,
        choices=ReviewClaimStatus.choices,
        default=ReviewClaimStatus.PENDING,
    )
    reviewer_name = models.CharField(
        max_length=100, 
        blank=True, 
        help_text="Chrome Web Store display name provided by user for verification"
    )
    claimed_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(
        null=True, blank=True, help_text="When admin approved or rejected"
    )
    pro_granted_until = models.DateTimeField(
        null=True, blank=True, help_text="Pro access expires at this time"
    )
    admin_notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "review reward claim"
        verbose_name_plural = "review reward claims"

    def __str__(self):
        return f"{self.user.email} — {self.status}"
