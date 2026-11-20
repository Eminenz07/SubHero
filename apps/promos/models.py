"""
Promo Campaigns — Models
========================
Signup-bonus campaigns run by admins to acquire new users.
All monetary amounts are Decimals with strict validation.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.wallet.models import WalletTransaction

CODE_RE = re.compile(r"^[A-Za-z0-9-]{4,32}$")


class PromoCampaign(models.Model):
    """
    Admin-run promo campaign granting a signup bonus to new users.
    Code is unique and case-insensitive. Immutable after creation.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        CLOSED = "CLOSED", "Closed"
        FULL = "FULL", "Full"
        EXPIRED = "EXPIRED", "Expired"

    class Meta:
        db_table = "promos_campaign"
        ordering = ["-created_at"]
        verbose_name = "Promo Campaign"
        verbose_name_plural = "Promo Campaigns"
        indexes = [
            models.Index(fields=["code"], name="promo_code_idx"),
            models.Index(fields=["status"], name="promo_status_idx"),
            models.Index(fields=["starts_at", "ends_at"], name="promo_dates_idx"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, help_text="Internal campaign name")
    code = models.CharField(
        max_length=32,
        unique=True,
        help_text="Unique case-insensitive invite code (4–32 chars: A-Z 0-9 -)",
    )
    bonus_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Welcome bonus credited to each new user (₦).",
    )
    max_claims = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Maximum number of claims allowed.",
    )
    claimed_count = models.PositiveIntegerField(default=0)
    visits = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    starts_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Campaign becomes active at this time.",
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Campaign expires at this time.",
    )
    max_claims_per_ip = models.PositiveIntegerField(
        default=5,
        help_text="Max claims per IP address (0 = unlimited).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promo_campaigns_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def effective_status(self):
        """Computed effective status for claim evaluation."""
        now = timezone.now()
        if self.status == self.Status.EXPIRED:
            return self.Status.EXPIRED
        if self.status == self.Status.CLOSED:
            return self.Status.CLOSED
        if self.status == self.Status.PAUSED:
            return self.Status.PAUSED
        if self.status == self.Status.DRAFT:
            return self.Status.DRAFT
        if self.ends_at and self.ends_at <= now:
            return self.Status.EXPIRED
        if self.claimed_count >= self.max_claims:
            return self.Status.FULL
        if self.starts_at and self.starts_at > now:
            return self.Status.DRAFT
        return self.Status.ACTIVE

    def clean(self):
        if self.code:
            self.code = self.code.strip().upper()
        if not CODE_RE.match(self.code or ""):
            raise ValidationError({"code": "Code must be 4–32 chars: A-Z 0-9 -."})


class PromoClaim(models.Model):
    """
    One claim per campaign per user. Snapshots the bonus amount paid.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        GRANTED = "GRANTED", "Granted"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        PromoCampaign,
        on_delete=models.CASCADE,
        related_name="claims",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="promo_claims",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reject_reason = models.TextField(blank=True, default="")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Snapshot of the bonus amount paid.",
    )
    source = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional ?s= label from the join link.",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    wallet_transaction = models.ForeignKey(
        WalletTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promo_claims",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    granted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "promos_claim"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "user"],
                name="unique_promo_claim_per_user_per_campaign",
            )
        ]
        indexes = [
            models.Index(fields=["campaign", "user"], name="promo_claim_user_idx"),
            models.Index(fields=["status"], name="promo_claim_status_idx"),
        ]

    def __str__(self):
        return f"{self.user.phone_number} → {self.campaign.code} ({self.status})"


class PromoAuditLog(models.Model):
    """
    Immutable audit trail of admin actions on promo campaigns.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promo_audit_logs",
    )
    campaign = models.ForeignKey(
        PromoCampaign,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=30)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "promos_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["campaign", "action"], name="promo_audit_campaign_idx"),
        ]

    def __str__(self):
        return f"{self.action} on {self.campaign.code} by {self.actor}"
