"""
Support — Celery Tasks
======================
Hero support background tasks for auto-closing tickets, SLA monitoring,
and notification alerts.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from apps.support.models import Ticket, TicketMessage, TicketEvent
from apps.notifications.models import Notification
from apps.notifications.services import send_push_notification

logger = logging.getLogger(__name__)


@shared_task
def auto_close_waiting_customer_tickets():
    """
    Move tickets in WAITING_CUSTOMER status with no reply for 72h to RESOLVED.
    Runs every 6 hours via Celery Beat.
    """
    hours = getattr(settings, "SUPPORT_WAITING_CUSTOMER_AUTO_RESOLVE_HOURS", 72)
    cutoff = timezone.now() - timedelta(hours=hours)

    tickets = Ticket.objects.filter(
        status=Ticket.Status.WAITING_CUSTOMER,
        last_customer_message_at__lt=cutoff,
    )

    count = 0
    for ticket in tickets:
        ticket.status = Ticket.Status.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at", "updated_at"])

        TicketMessage.objects.create(
            ticket=ticket,
            author=ticket.user,
            sender_type=TicketMessage.SenderType.SYSTEM,
            body=(
                f"This ticket has been automatically resolved due to inactivity "
                f"(no customer reply for {hours} hours). "
                f"Reply to reopen within 7 days of resolution."
            ),
            is_internal=False,
        )
        TicketEvent.objects.create(
            ticket=ticket,
            actor=None,
            event_type=TicketEvent.EventType.AUTO_CLOSE,
            description=f"Auto-closed after {hours}h of customer inactivity",
        )
        count += 1

    logger.info("Auto-closed %d waiting_customer tickets due to inactivity.", count)
    return count


@shared_task
def auto_close_resolved_tickets():
    """
    Move tickets in RESOLVED status for 7+ days to CLOSED.
    Runs daily at 01:00 via Celery Beat.
    """
    days = getattr(settings, "SUPPORT_AUTO_CLOSE_RESOLVED_DAYS", 7)
    cutoff = timezone.now() - timedelta(days=days)

    tickets = Ticket.objects.filter(
        status=Ticket.Status.RESOLVED,
        resolved_at__lt=cutoff,
    )

    count = 0
    for ticket in tickets:
        ticket.status = Ticket.Status.CLOSED
        ticket.closed_at = timezone.now()
        ticket.save(update_fields=["status", "closed_at", "updated_at"])

        TicketMessage.objects.create(
            ticket=ticket,
            author=ticket.user,
            sender_type=TicketMessage.SenderType.SYSTEM,
            body="This ticket has been closed after 7 days of resolution.",
            is_internal=False,
        )
        TicketEvent.objects.create(
            ticket=ticket,
            actor=None,
            event_type=TicketEvent.EventType.AUTO_CLOSE,
            description="Auto-closed after 7 days of resolution",
        )
        count += 1

    logger.info("Auto-closed %d resolved tickets after %d days.", count, days)
    return count


@shared_task
def check_sla_breach():
    """
    Check for SLA breaches (no first response within target hours).
    Runs every 5 minutes via Celery Beat.
    Alerts leads if a ticket is past its SLA due date and hasn't had
    a first response yet.
    """
    tickets = Ticket.objects.filter(
        status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS],
        sla_due_at__lt=timezone.now(),
        first_response_at__isnull=True,
    ).select_related("assigned_to")

    count = 0
    for ticket in tickets:
        # Notify leads about SLA breach
        from django.contrib.auth import get_user_model
        User = get_user_model()

        leads = User.objects.filter(
            is_staff=True,
            staff_profile__role="lead",
            staff_profile__is_available=True,
        )

        for lead in leads:
            Notification.add(
                user=lead,
                title=f"SLA Breach: {ticket.reference}",
                description=(
                    f"Ticket {ticket.reference} ({ticket.subject}) has breached its "
                    f"SLA first-response deadline. No staff response yet."
                ),
                level="warning",
            )
            send_push_notification(
                user=lead,
                title=f"SLA Breach: {ticket.reference}",
                body=f"No first response yet for {ticket.subject}",
                action_url=f"{settings.SITE_URL}/desk/tickets/{ticket.id}/",
                level="warning",
            )

        count += 1

    logger.info("SLA breach check: %d tickets past SLA deadline.", count)
    return count


@shared_task
def alert_unassigned_tickets():
    """
    Alert leads if a ticket has been unassigned for 10+ minutes.
    Can be run independently or via Celery Beat.
    """
    cutoff = timezone.now() - timedelta(minutes=10)

    tickets = Ticket.objects.filter(
        status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS],
        assigned_to__isnull=True,
        created_at__lt=cutoff,
    )

    count = 0
    for ticket in tickets:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        leads = User.objects.filter(
            is_staff=True,
            staff_profile__role="lead",
            staff_profile__is_available=True,
        )

        for lead in leads:
            Notification.add(
                user=lead,
                title=f"Unassigned Ticket: {ticket.reference}",
                description=(
                    f"Ticket {ticket.reference} ({ticket.subject}) has been "
                    f"unassigned for over 10 minutes."
                ),
                level="warning",
            )
        count += 1

    logger.info("Unassigned ticket alert: %d tickets unassigned for 10+ min.", count)
    return count
