"""
Support — Views
===============
Customer-facing Hero support ticketing.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views import View
from django.views.generic import ListView, DetailView, CreateView

from apps.core.utils import get_client_ip
from apps.notifications.models import Notification
from apps.notifications.services import send_push_notification
from apps.wallet.models import Wallet, WalletTransaction

from .models import (
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketEvent,
    StaffProfile,
    CannedReply,
    RefundRequest,
)

logger = logging.getLogger(__name__)

User = get_user_model()

# Maximum message body length
MAX_BODY_LENGTH = 2000

# Maximum attachments per message
MAX_ATTACHMENTS_PER_MESSAGE = 3

# Supported attachment content types
ALLOWED_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Maximum attachment size (3 MB)
MAX_ATTACHMENT_SIZE = 3 * 1024 * 1024


def _rate_limit_key(request, group):
    """Build a rate-limit key keyed by user + group."""
    if request.user.is_authenticated:
        return f"{request.user.id}:{group}"
    return f"anon:{get_client_ip(request)}:{group}"


def _create_system_event(ticket, actor, event_type, description, metadata=None):
    TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        event_type=event_type,
        description=description,
        metadata=metadata or {},
    )


def _create_system_message(ticket, body):
    """Add a system-generated message to a ticket."""
    # Use a synthetic system author - the ticket's user is the fallback
    # so messages always have an author, but marked as SYSTEM sender_type.
    return TicketMessage.objects.create(
        ticket=ticket,
        author=ticket.user,
        sender_type=TicketMessage.SenderType.SYSTEM,
        body=body,
        is_internal=False,
    )


def _notify_staff_about_ticket(ticket, actor=None, extra_context=None):
    """Create in-app + push notifications for available staff about a new ticket."""
    try:
        from apps.support.models import StaffProfile

        staff_users = (
            User.objects.filter(is_staff=True, staff_profile__is_available=True)
            .select_related("staff_profile")
        )
        title = f"New Hero Ticket {ticket.reference}"
        body = f"{ticket.subject} — {ticket.user.full_name or ticket.user.phone_number}"
        site_url = getattr(settings, "SITE_URL", "")
        url = f"{site_url}/desk/tickets/{ticket.id}/"

        for staff in staff_users:
            try:
                Notification.add(
                    user=staff,
                    title=title,
                    description=body,
                    level="info",
                )
                send_push_notification(
                    user=staff,
                    title=title,
                    body=body,
                    action_url=url,
                    level="info",
                )
            except Exception:
                logger.exception("Failed to notify staff %s about ticket %s", staff.id, ticket.reference)
    except Exception:
        logger.exception("Failed to notify staff about ticket %s", ticket.reference)


class TicketListView(LoginRequiredMixin, ListView):
    """My tickets page — /support/"""

    model = Ticket
    template_name = "support/ticket_list.html"
    context_object_name = "tickets"
    paginate_by = 20

    def get_queryset(self):
        # Only the ticket owner can view it — filter by user strictly
        return (
            Ticket.objects.filter(user=self.request.user)
            .select_related("assigned_to")
            .order_by("-created_at")
        )


class TicketCreateView(LoginRequiredMixin, View):
    """Create a new support ticket — /support/new/"""

    def get(self, request):
        categories = [
            ("wallet", "Wallet"),
            ("vtu", "VTU / Airtime & Data"),
            ("smm", "Social Media Growth"),
            ("giveaway", "Giveaway"),
            ("account", "Account"),
            ("other", "Other"),
        ]
        return render(request, "support/ticket_create.html", {"categories": categories})

    def post(self, request):
        try:
            return self._post_inner(request)
        except Exception as exc:
            logger.exception("Ticket creation failed: %s", exc)
            messages.error(request, f"Ticket creation failed: {str(exc)[:200]}. Please try again.")
            return redirect("support:ticket_create")

    def _post_inner(self, request):
        # Rate limit: 5 new tickets per hour per user
        key = _rate_limit_key(request, "new_tickets")
        # Use django-ratelimit-style check manually via cache
        from django.core.cache import cache

        count = cache.get(key, 0)
        if count >= 5:
            messages.error(request, "You've reached the limit of 5 new tickets per hour. Please try again later.")
            return redirect("support:ticket_list")

        category = request.POST.get("category", "other")
        subject = escape((request.POST.get("subject") or "").strip())[:200]
        body = escape((request.POST.get("body") or "").strip())
        related_ref = escape((request.POST.get("related_reference") or "").strip())
        related_type = escape((request.POST.get("related_type") or "").strip())

        if not subject:
            messages.error(request, "Subject is required.")
            return redirect("support:ticket_create")
        if not body:
            messages.error(request, "Please describe your issue.")
            return redirect("support:ticket_create")
        if len(body) > MAX_BODY_LENGTH:
            messages.error(request, f"Message is too long (max {MAX_BODY_LENGTH} characters).")
            return redirect("support:ticket_create")

        # Max 3 open tickets per user
        open_count = Ticket.objects.filter(user=request.user).exclude(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
        ).count()
        if open_count >= 3:
            messages.error(request, "You already have 3 open tickets. Please wait for one to be resolved before opening a new one.")
            return redirect("support:ticket_list")

        # Determine priority: auto-high for debited-but-undelivered orders
        priority = Ticket.Priority.NORMAL
        # Check if this looks like a payment/order issue
        if related_ref:
            from apps.wallet.models import WalletTransaction
            from apps.vtu.models import VTUOrder
            from apps.smm.models import SMMOrder

            # Quick check: is there a pending/failed transaction with this ref?
            pending_txn = WalletTransaction.objects.filter(
                reference=related_ref,
                status__in=["PENDING", "FAILED"],
            ).first()
            if pending_txn:
                priority = Ticket.Priority.HIGH

        with transaction.atomic():
            ticket = Ticket.objects.create(
                user=request.user,
                category=category,
                subject=subject,
                priority=priority,
                related_type=related_type,
                related_reference=related_ref,
            )
            # First customer message
            TicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                sender_type=TicketMessage.SenderType.CUSTOMER,
                body=body,
                is_internal=False,
            )
            ticket.last_customer_message_at = timezone.now()
            ticket.save(update_fields=["last_customer_message_at"])

            # System message with ticket ID, business hours, expected response
            biz_hours = getattr(settings, "SUPPORT_BUSINESS_HOURS", "Mon–Fri 9am–6pm WAT")
            resp_time = getattr(settings, "SUPPORT_FIRST_RESPONSE_NORMAL_HOURS", 4)
            _create_system_message(
                ticket,
                f"Ticket {ticket.reference} created. "
                f"Support hours: {biz_hours}. "
                f"Expected first response: within {resp_time} hours "
                f"({'1 hour' if priority == Ticket.Priority.HIGH else resp_time + ' hours'} for high priority).",
            )
            _create_system_event(
                ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.SYSTEM_MESSAGE,
                description="Ticket created by customer",
                metadata={"category": category, "priority": priority},
            )

        cache.set(key, count + 1, 3600)  # 1 hour window
        try:
            _notify_staff_about_ticket(ticket, actor=request.user)
        except Exception:
            logger.exception("Failed to notify staff about ticket %s", ticket.reference)

        messages.success(request, f"Ticket {ticket.reference} created. Our Hero team will get back to you soon.")
        return redirect("support:ticket_detail", reference=ticket.reference)


class TicketDetailView(LoginRequiredMixin, DetailView):
    """Ticket chat thread — /support/<reference>/"""

    model = Ticket
    template_name = "support/ticket_detail.html"
    context_object_name = "ticket"
    slug_field = "reference"
    slug_url_kwarg = "reference"

    def get_queryset(self):
        # Only the ticket owner can view it
        return Ticket.objects.filter(user=self.request.user).select_related("assigned_to")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ticket = self.object
        context["messages"] = ticket.messages.select_related("author").prefetch_related("attachments").all()
        context["events"] = ticket.events.select_related("actor").order_by("-created_at")[:10]
        context["can_reply"] = ticket.can_customer_reply
        context["show_csat"] = ticket.status == Ticket.Status.RESOLVED and ticket.csat is None
        context["support_warning"] = "Hero will never ask for your PIN or OTP."
        context["business_hours"] = getattr(settings, "SUPPORT_BUSINESS_HOURS", "Mon–Fri 9am–6pm WAT")
        return context


class TicketMessagesPartialView(LoginRequiredMixin, View):
    """HTMX partial for polling new messages — /support/<reference>/messages/"""

    def get(self, request, reference):
        ticket = get_object_or_404(Ticket, reference=reference, user=request.user)
        messages_qs = ticket.messages.select_related("author").prefetch_related("attachments").all()
        return render(request, "support/partials/_message_list.html", {"messages": messages_qs, "ticket": ticket})


class TicketReplyView(LoginRequiredMixin, View):
    """Post a reply to a ticket — /support/<reference>/reply/"""

    def post(self, request, reference):
        ticket = get_object_or_404(Ticket, reference=reference, user=request.user)

        if not ticket.can_customer_reply:
            return JsonResponse({"error": "Cannot reply to this ticket at this time."}, status=403)

        # Rate limit: 30 messages per hour per user
        key = _rate_limit_key(request, "ticket_messages")
        from django.core.cache import cache
        count = cache.get(key, 0)
        if count >= 30:
            return JsonResponse({"error": "You've reached the message limit. Please try again later."}, status=429)

        body = escape((request.POST.get("body") or "").strip())
        if not body:
            return JsonResponse({"error": "Message cannot be empty."}, status=400)
        if len(body) > MAX_BODY_LENGTH:
            return JsonResponse({"error": f"Message too long (max {MAX_BODY_LENGTH} characters)."}, status=400)

        with transaction.atomic():
            msg = TicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                sender_type=TicketMessage.SenderType.CUSTOMER,
                body=body,
                is_internal=False,
            )
            # Handle attachments
            files = request.FILES.getlist("attachments")
            if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
                return JsonResponse({"error": "Maximum 3 attachments per message."}, status=400)
            for f in files:
                TicketAttachment.objects.create(
                    message=msg,
                    file=f,
                    filename=f.name,
                    content_type=f.content_type or "",
                    size=f.size,
                )

            ticket.last_customer_message_at = timezone.now()
            # If ticket was resolved, reopen it
            if ticket.status == Ticket.Status.RESOLVED:
                ticket.status = Ticket.Status.OPEN
                ticket.resolved_at = None
                _create_system_event(
                    ticket,
                    actor=request.user,
                    event_type=TicketEvent.EventType.STATUS_CHANGE,
                    description="Customer replied — ticket reopened",
                )
            ticket.save(update_fields=["last_customer_message_at", "status", "resolved_at", "updated_at"])

            _create_system_event(
                ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.SYSTEM_MESSAGE,
                description="Customer sent a message",
            )

        cache.set(key, count + 1, 3600)

        # Notify staff
        staff_users = User.objects.filter(is_staff=True, staff_profile__is_available=True)
        for staff in staff_users:
            Notification.add(
                user=staff,
                title=f"New reply on {ticket.reference}",
                description=f"{request.user.full_name or request.user.phone_number} replied.",
                level="info",
            )

        return JsonResponse({"status": "ok", "message_id": str(msg.id)})


class TicketCsatView(LoginRequiredMixin, View):
    """Submit CSAT rating — /support/<reference>/csat/"""

    def post(self, request, reference):
        ticket = get_object_or_404(Ticket, reference=reference, user=request.user)

        if ticket.status != Ticket.Status.RESOLVED or ticket.csat is not None:
            return JsonResponse({"error": "CSAT not available for this ticket."}, status=400)

        rating = request.POST.get("rating")
        comment = escape((request.POST.get("comment") or "").strip())

        if rating not in ("1", "-1"):
            return JsonResponse({"error": "Invalid rating."}, status=400)

        ticket.csat = int(rating)
        ticket.csat_comment = comment
        ticket.save(update_fields=["csat", "csat_comment"])

        _create_system_event(
            ticket,
            actor=request.user,
            event_type=TicketEvent.EventType.CSAT_SUBMITTED,
            description=f"Customer rated the support {'positive' if rating == '1' else 'negative'}",
            metadata={"rating": rating, "comment": comment},
        )

        return JsonResponse({"status": "ok", "csat": ticket.csat})


class HelpWithOrderView(LoginRequiredMixin, View):
    """Pre-fill ticket creation from a failed order screen — /support/help-with-order/"""

    def get(self, request):
        order_ref = request.GET.get("ref", "")
        order_type = request.GET.get("type", "vtu")
        return render(
            request,
            "support/help_with_order.html",
            {"order_ref": order_ref, "order_type": order_type},
        )


class RefundRequestCreateView(LoginRequiredMixin, View):
    """Agent creates a refund request from a ticket — POST /support/refund-request/<ticket_id>/"""

    def post(self, request, ticket_id):
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff only."}, status=403)

        ticket = get_object_or_404(Ticket, id=ticket_id)
        amount_str = (request.POST.get("amount") or "").strip()
        order_reference = (request.POST.get("order_reference") or "").strip()
        reason = (request.POST.get("reason") or "").strip()

        if not amount_str:
            return JsonResponse({"error": "Amount is required."}, status=400)
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)
        if not order_reference:
            return JsonResponse({"error": "Order reference is required."}, status=400)
        if not reason:
            return JsonResponse({"error": "Reason is required."}, status=400)

        with transaction.atomic():
            refund_request = RefundRequest.objects.create(
                ticket=ticket,
                order_reference=order_reference,
                amount=amount,
                reason=reason,
                requested_by=request.user,
                status=RefundRequest.Status.PENDING,
            )
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.REFUND_REQUEST,
                description=f"Refund request created: ₦{amount:,.2f} for {order_reference}",
                metadata={"refund_request_id": str(refund_request.id), "amount": str(amount)},
            )

        # Notify leads for approval
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
                title=f"Refund Request: {ticket.reference}",
                description=f"₦{amount:,.2f} refund for {order_reference} awaits approval.",
                level="warning",
            )
            send_push_notification(
                user=lead,
                title=f"Refund Request: {ticket.reference}",
                body=f"₦{amount:,.2f} refund for {order_reference} awaits approval.",
                action_url=f"{settings.SITE_URL}/desk/tickets/{ticket.id}/",
                level="warning",
            )

        return JsonResponse({
            "status": "ok",
            "refund_request_id": str(refund_request.id),
            "status": refund_request.status,
        })


class RefundRequestDecideView(LoginRequiredMixin, View):
    """Lead/admin approves or rejects a refund request — POST /support/refund-request/<uuid>/decide/"""

    def post(self, request, refund_id):
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff only."}, status=403)

        try:
            is_lead = (
                hasattr(request.user, "staff_profile")
                and request.user.staff_profile.role == "lead"
            )
        except AttributeError:
            is_lead = False
        if not is_lead and not request.user.is_superuser:
            return JsonResponse({"error": "Leads or admins only."}, status=403)

        refund_request = get_object_or_404(RefundRequest, id=refund_id)
        if refund_request.status != RefundRequest.Status.PENDING:
            return JsonResponse({"error": "Refund request already decided."}, status=400)

        decision = (request.POST.get("decision") or "").strip()
        if decision not in ("approve", "reject"):
            return JsonResponse({"error": "Invalid decision."}, status=400)

        with transaction.atomic():
            if decision == "approve":
                refund_request.status = RefundRequest.Status.APPROVED
                refund_request.decided_by = request.user
                refund_request.decided_at = timezone.now()
                refund_request.save(
                    update_fields=["status", "decided_by", "decided_at"]
                )

                # Run manual refund logic via wallet services
                from apps.wallet.services import credit_wallet

                ticket = refund_request.ticket
                wallet, _ = Wallet.objects.get_or_create(user=ticket.user)
                credit_wallet(
                    wallet_id=wallet.id,
                    amount=refund_request.amount,
                    txn_type=WalletTransaction.TxnType.REFUND,
                    reference=f"REFUND-{refund_request.id}",
                    description=f"Approved refund for {refund_request.order_reference}",
                    metadata={
                        "refund_request_id": str(refund_request.id),
                        "ticket_id": str(ticket.id),
                        "approved_by": str(request.user.id),
                    },
                    ip_address=get_client_ip(request),
                )

                TicketEvent.objects.create(
                    ticket=ticket,
                    actor=request.user,
                    event_type=TicketEvent.EventType.REFUND_APPROVED,
                    description=(
                        f"Refund approved: ₦{refund_request.amount:,.2f} "
                        f"for {refund_request.order_reference}"
                    ),
                    metadata={"refund_request_id": str(refund_request.id)},
                )

                # Notify customer
                Notification.add(
                    user=ticket.user,
                    title=f"Refund Approved: {ticket.reference}",
                    description=f"₦{refund_request.amount:,.2f} has been refunded to your wallet.",
                    level="success",
                )
                send_push_notification(
                    user=ticket.user,
                    title=f"Refund Approved: {ticket.reference}",
                    body=f"₦{refund_request.amount:,.2f} refunded to your wallet.",
                    action_url=f"{settings.SITE_URL}/support/{ticket.reference}/",
                    level="success",
                )
            else:
                refund_request.status = RefundRequest.Status.REJECTED
                refund_request.decided_by = request.user
                refund_request.decided_at = timezone.now()
                refund_request.save(
                    update_fields=["status", "decided_by", "decided_at"]
                )

                TicketEvent.objects.create(
                    ticket=ticket,
                    actor=request.user,
                    event_type=TicketEvent.EventType.REFUND_REJECTED,
                    description=(
                        f"Refund rejected: ₦{refund_request.amount:,.2f} "
                        f"for {refund_request.order_reference}"
                    ),
                    metadata={"refund_request_id": str(refund_request.id)},
                )

        return JsonResponse({
            "status": "ok",
            "decision": decision,
            "refund_request_status": refund_request.status,
        })

