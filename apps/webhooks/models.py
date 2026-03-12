"""Webhook event storage for external providers (Whop, etc.)."""
import uuid

from django.conf import settings
from django.db import models


class WebhookEvent(models.Model):
    """Stores raw incoming webhook payloads for audit and processing."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=50, default="whop", db_index=True)
    external_event_id = models.CharField(
        max_length=256, blank=True, default="", db_index=True
    )
    event_type = models.CharField(max_length=100, db_index=True)
    raw_payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "webhook event"
        verbose_name_plural = "webhook events"

    def __str__(self):
        return f"[{self.provider}] {self.event_type} @ {self.created_at}"
