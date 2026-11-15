"""
Support — Models
================
Hero Support Ticketing System.

PRD-aligned models for customer support tickets, messages, attachments,
audit events, canned replies, staff profiles, and refund requests.

All models use UUID primary keys (PRD Section 7).
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.utils import generate_reference


class StaffProfile(models.Model):
    """
    Staff profile for support desk agents and leads.
    Display name is shown to customers as "Hero · {display_name}".
    """

    class Role(models.TextChoices):
        AGENT = "agent", "Agent"
        LEAD = "lead", "Team Lead"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
        help_text="Must have is_staff=True on the User model.",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.AGENT,
    )
    display_name = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text="Shown to customers as 'Hero · {display_name}'. Falls back to user full_name.",
    )
    is_available = models.BooleanField(
        default=True,
        help_text="Whether this staff member should receive new ticket alerts.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_staff_profile"
        verbose_name = "Staff Profile"
        verbose_name_plural = "Staff Profiles"

    def __str__(self):
        return f"StaffProfile({self.user.full_name or self.user.phone_number})"

    @property
    def hero_label(self):
        """Customer-facing label, e.g. 'Hero · Ada'."""
        name = self.display_name or self.user.full_name or self.user.phone_number
        return f"Hero · {name}"


class Ticket(models.Model):
    """
    Customer support ticket.

    Each ticket belongs to one user and may be linked to an order or
    transaction via related_type / related_reference.
    """

    class Category(models.TextChoices):
        WALLET = "wallet", "Wallet"
        VTU = "vtu", "VTU / Airtime & Data"
        SMM = "smm", "Social Media Growth"
        GIVEAWAY = "giveaway", "Giveaway"
        ACCOUNT = "account", "Account"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        WAITING_CUSTOMER = "waiting_customer", "Waiting on Customer"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(
        max_length=20,
        unique=True,
        help_text="Human-readable ticket reference, e.g. HRO-000123",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
    )
    subject = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_support_tickets",
        help_text="Staff member currently owning this ticket.",
    )

    # Optional link to an order or transaction for context
    related_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="e.g. 'vtu_order', 'smm_order', 'wallet_transaction'",
    )
    related_reference = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Reference of the linked order or transaction.",
    )

    # Timestamps
    sla_due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Deadline for first response based on priority.",
    )
    first_response_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the first staff reply was sent.",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the ticket was first marked resolved.",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the ticket was closed (7 days after resolved).",
    )
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_staff_message_at = models.DateTimeField(null=True, blank=True)

    # CSAT
    csat = models.SmallIntegerField(
        null=True,
        blank=True,
        help_text="1 = positive, -1 = negative",
    )
    csat_comment = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_ticket"
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="ticket_user_created_idx"),
            models.Index(fields=["status", "assigned_to"], name="ticket_status_assigned_idx"),
            models.Index(fields=["reference"], name="ticket_reference_idx"),
        ]

    def __str__(self):
        return f"{self.reference} — {self.subject} ({self.user.phone_number})"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_reference("HRO")
        # Auto-set SLA due date based on priority if not already set
        if not self.sla_due_at and self.pk is None:
            from datetime import timedelta

            hours = 1 if self.priority == self.Priority.HIGH else 4
            self.sla_due_at = timezone.now() + timedelta(hours=hours)
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in (self.Status.OPEN, self.Status.IN_PROGRESS)

    @property
    def can_customer_reply(self):
        """Customers can reply while open, waiting_customer, or resolved (within 7 days)."""
        if self.status in (self.Status.OPEN, self.Status.IN_PROGRESS, self.Status.WAITING_CUSTOMER):
            return True
        if self.status == self.Status.RESOLVED and self.resolved_at:
            return (timezone.now() - self.resolved_at).days <= 7
        return False

    @property
    def is_sla_breached(self):
        if self.sla_due_at and self.status not in (self.Status.RESOLVED, self.Status.CLOSED):
            if not self.first_response_at:
                return timezone.now() > self.sla_due_at
        return False


class TicketMessage(models.Model):
    """
    Individual message within a ticket thread.
    """

    class SenderType(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STAFF = "staff", "Staff"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_messages",
    )
    sender_type = models.CharField(max_length=10, choices=SenderType.choices)
    body = models.TextField(
        max_length=2000,
        help_text="Message body — HTML is escaped on render.",
    )
    is_internal = models.BooleanField(
        default=False,
        help_text="Staff-only note; never shown to the customer.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "support_ticket_message"
        verbose_name = "Ticket Message"
        verbose_name_plural = "Ticket Messages"
        ordering = ["created_at"]

    def __str__(self):
        return f"Message {self.id} on {self.ticket.reference}"


class TicketAttachment(models.Model):
    """
    File attachment on a ticket message.

    Constraints:
    - jpg / png / webp only
    - max 3 MB per file
    - max 3 attachments per message
    - EXIF stripped on save
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.ImageField(
        upload_to="support/attachments/%Y/%m/",
        help_text="Image attachment — jpg/png/webp, max 3 MB.",
    )
    filename = models.CharField(max_length=255, default="")
    content_type = models.CharField(max_length=60, default="")
    size = models.PositiveIntegerField(default=0, help_text="File size in bytes.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "support_ticket_attachment"
        verbose_name = "Ticket Attachment"
        verbose_name_plural = "Ticket Attachments"

    def __str__(self):
        return f"Attachment {self.filename or self.file.name}"


class TicketEvent(models.Model):
    """
    Immutable audit log for ticket lifecycle changes.

    Events include: status change, assignment, internal note, refund
    request / approval. Once created, rows are never updated or deleted.
    """

    class EventType(models.TextChoices):
        STATUS_CHANGE = "status_change", "Status Change"
        ASSIGNMENT = "assignment", "Assignment"
        INTERNAL_NOTE = "internal_note", "Internal Note"
        REFUND_REQUEST = "refund_request", "Refund Request"
        REFUND_APPROVED = "refund_approved", "Refund Approved"
        REFUND_REJECTED = "refund_rejected", "Refund Rejected"
        CSAT_SUBMITTED = "csat_submitted", "CSAT Submitted"
        AUTO_CLOSE = "auto_close", "Auto Close"
        SYSTEM_MESSAGE = "system_message", "System Message"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_events",
        help_text="Staff or system user who triggered the event.",
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    description = models.CharField(max_length=255, help_text="Human-readable event summary.")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "support_ticket_event"
        verbose_name = "Ticket Event"
        verbose_name_plural = "Ticket Events"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.event_type} on {self.ticket.reference}"


class CannedReply(models.Model):
    """
    Pre-written replies staff can insert into ticket threads.
    """

    class Category(models.TextChoices):
        GENERAL = "general", "General"
        REFUND = "refund", "Refund"
        VTU = "vtu", "VTU"
        SMM = "smm", "SMM"
        WALLET = "wallet", "Wallet"
        ACCOUNT = "account", "Account"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=120)
    body = models.TextField(help_text="Plain text reply body.")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GENERAL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_canned_reply"
        verbose_name = "Canned Reply"
        verbose_name_plural = "Canned Replies"
        ordering = ["category", "title"]

    def __str__(self):
        return self.title


class RefundRequest(models.Model):
    """
    Refund request created by an agent from a ticket.
    Must be approved by a lead or admin before funds are moved.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="refund_requests",
    )
    order_reference = models.CharField(
        max_length=50,
        help_text="Reference of the order/transaction being refunded.",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Refund amount in Naira.",
    )
    reason = models.TextField(help_text="Reason for the refund request.")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refund_requests_requested",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refund_requests_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "support_refund_request"
        verbose_name = "Refund Request"
        verbose_name_plural = "Refund Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"RefundRequest {self.id} — ₦{self.amount} ({self.status})"
