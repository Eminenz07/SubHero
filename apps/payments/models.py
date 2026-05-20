"""
Payments — Models
==================
PRD Section 8.2: Webhook audit log.
Every incoming webhook is logged regardless of outcome.
"""

import uuid

from django.db import models


class WebhookLog(models.Model):
    """
    Audit log for all incoming payment webhooks.
    Stores the full payload hash and processing result for compliance.
    """

    class Provider(models.TextChoices):
        PROVIDUS = "PROVIDUS", "Providus Bank"
        BLOC = "BLOC", "Bloc"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        VERIFIED = "VERIFIED", "Signature Verified"
        PROCESSED = "PROCESSED", "Processed Successfully"
        DUPLICATE = "DUPLICATE", "Duplicate Reference"
        REJECTED = "REJECTED", "Signature Rejected"
        FAILED = "FAILED", "Processing Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    provider = models.CharField(
        max_length=15,
        choices=Provider.choices,
        default=Provider.PROVIDUS,
    )
    reference = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Payment reference from provider",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    account_number = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Virtual account number credited",
    )
    payload_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hash of raw payload body",
    )
    source_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
    )
    signature_valid = models.BooleanField(
        default=False,
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.RECEIVED,
    )
    error_message = models.TextField(
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        db_table = "payments_webhook_log"
        verbose_name = "Webhook Log"
        verbose_name_plural = "Webhook Logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Webhook {self.provider} - {self.reference} ({self.status})"
