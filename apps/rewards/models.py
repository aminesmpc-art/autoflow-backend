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
