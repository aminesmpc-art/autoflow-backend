"""Usage models — daily consumption tracking and event logging."""
import uuid

from django.conf import settings
from django.db import models


class DailyUsage(models.Model):
    """Tracks per-day prompt consumption for a user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_usages",
    )
    date = models.DateField(db_index=True)
    free_prompts_used = models.PositiveIntegerField(default=0)
    reward_prompts_used = models.PositiveIntegerField(default=0)
    total_prompts_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "date")
        verbose_name = "daily usage"
        verbose_name_plural = "daily usages"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.user.email} — {self.date} ({self.total_prompts_used} used)"


class UsageEvent(models.Model):
    """Individual usage/telemetry events from the extension or backend."""

    class EventType(models.TextChoices):
        CONSUME_PROMPT = "consume_prompt", "Consume Prompt"
        QUEUE_STARTED = "queue_started", "Queue Started"
        QUEUE_FINISHED = "queue_finished", "Queue Finished"
        PROMPT_FAILED = "prompt_failed", "Prompt Failed"
        DOWNLOAD_COMPLETED = "download_completed", "Download Completed"
        RUN_ABORTED = "run_aborted", "Run Aborted"
        REWARD_GRANTED = "reward_granted", "Reward Granted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usage_events",
    )
    event_type = models.CharField(max_length=50, choices=EventType.choices, db_index=True)
    prompt_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "usage event"
        verbose_name_plural = "usage events"

    def __str__(self):
        return f"{self.user.email} — {self.event_type} @ {self.created_at}"
