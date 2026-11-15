"""
Initial migration for support app.
"""

import uuid
from decimal import Decimal

import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffProfile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("agent", "Agent"), ("lead", "Team Lead")], default="agent", max_length=10)),
                ("display_name", models.CharField(blank=True, default="", max_length=60)),
                ("is_available", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="staff_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Staff Profile", "verbose_name_plural": "Staff Profiles", "db_table": "support_staff_profile"},
        ),
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reference", models.CharField(max_length=20, unique=True)),
                ("category", models.CharField(choices=[("wallet", "Wallet"), ("vtu", "VTU / Airtime & Data"), ("smm", "Social Media Growth"), ("giveaway", "Giveaway"), ("account", "Account"), ("other", "Other")], default="other", max_length=20)),
                ("subject", models.CharField(max_length=200)),
                ("status", models.CharField(choices=[("open", "Open"), ("in_progress", "In Progress"), ("waiting_customer", "Waiting on Customer"), ("resolved", "Resolved"), ("closed", "Closed")], default="open", max_length=20)),
                ("priority", models.CharField(choices=[("normal", "Normal"), ("high", "High")], default="normal", max_length=10)),
                ("related_type", models.CharField(blank=True, default="", max_length=20)),
                ("related_reference", models.CharField(blank=True, default="", max_length=50)),
                ("sla_due_at", models.DateTimeField(blank=True, null=True)),
                ("first_response_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("last_customer_message_at", models.DateTimeField(blank=True, null=True)),
                ("last_staff_message_at", models.DateTimeField(blank=True, null=True)),
                ("csat", models.SmallIntegerField(blank=True, null=True)),
                ("csat_comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_support_tickets", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="support_tickets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Ticket", "verbose_name_plural": "Tickets", "ordering": ["-created_at"], "db_table": "support_ticket", "indexes": [models.Index(fields=["user", "-created_at"], name="ticket_user_created_idx"), models.Index(fields=["status", "assigned_to"], name="ticket_status_assigned_idx"), models.Index(fields=["reference"], name="ticket_reference_idx")]},
        ),
        migrations.CreateModel(
            name="TicketMessage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sender_type", models.CharField(choices=[("customer", "Customer"), ("staff", "Staff"), ("system", "System")], max_length=10)),
                ("body", models.TextField(max_length=2000, help_text="Message body — HTML is escaped on render.")),
                ("is_internal", models.BooleanField(default=False, help_text="Staff-only note; never shown to the customer.")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="support_messages", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="support.Ticket")),
            ],
            options={"verbose_name": "Ticket Message", "verbose_name_plural": "Ticket Messages", "ordering": ["created_at"], "db_table": "support_ticket_message"},
        ),
        migrations.CreateModel(
            name="TicketAttachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("file", models.ImageField(help_text="Image attachment — jpg/png/webp, max 3 MB.", upload_to="support/attachments/%Y/%m/")),
                ("filename", models.CharField(default="", max_length=255)),
                ("content_type", models.CharField(default="", max_length=60)),
                ("size", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="support.TicketMessage")),
            ],
            options={"verbose_name": "Ticket Attachment", "verbose_name_plural": "Ticket Attachments", "db_table": "support_ticket_attachment"},
        ),
        migrations.CreateModel(
            name="TicketEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(choices=[("status_change", "Status Change"), ("assignment", "Assignment"), ("internal_note", "Internal Note"), ("refund_request", "Refund Request"), ("refund_approved", "Refund Approved"), ("refund_rejected", "Refund Rejected"), ("csat_submitted", "CSAT Submitted"), ("auto_close", "Auto Close"), ("system_message", "System Message")], max_length=30)),
                ("description", models.CharField(max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="support_events", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="support.Ticket")),
            ],
            options={"verbose_name": "Ticket Event", "verbose_name_plural": "Ticket Events", "ordering": ["created_at"], "db_table": "support_ticket_event"},
        ),
        migrations.CreateModel(
            name="CannedReply",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=120)),
                ("body", models.TextField()),
                ("category", models.CharField(choices=[("general", "General"), ("refund", "Refund"), ("vtu", "VTU"), ("smm", "SMM"), ("wallet", "Wallet"), ("account", "Account")], default="general", max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Canned Reply", "verbose_name_plural": "Canned Replies", "ordering": ["category", "title"], "db_table": "support_canned_reply"},
        ),
        migrations.CreateModel(
            name="RefundRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("order_reference", models.CharField(max_length=50)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("reason", models.TextField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=15)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="refund_requests_decided", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="refund_requests_requested", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="refund_requests", to="support.Ticket")),
            ],
            options={"verbose_name": "Refund Request", "verbose_name_plural": "Refund Requests", "ordering": ["-created_at"], "db_table": "support_refund_request"},
        ),
    ]
