"""
Support — Desk Views
====================
Hero support staff desk: inbox, ticket detail, replies, and actions.
"""

import logging

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views import View
from django.views.generic import ListView
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

from apps.core.utils import get_client_ip
from apps.support.decorators import support_required, lead_required
from apps.wallet.models import Wallet, WalletTransaction
from apps.vtu.models import VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder
from apps.smm.models import SMMOrder
from apps.wallet.services import credit_wallet

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


class DeskInboxView(LoginRequiredMixin, ListView):
    """
    Staff inbox — /desk/
    Tabs: Unassigned, Mine, Waiting on customer, All open, Resolved.
    Filters: category, priority. Search: reference, phone, email, order reference.
    """
    model = Ticket
    template_name = "support/desk/inbox.html"
    context_object_name = "tickets"
    paginate_by = 25

    @method_decorator(support_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_queryset(self):
        qs = Ticket.objects.select_related("user", "assigned_to").order_by("-created_at")
        tab = self.request.GET.get("tab", "pending")

        if tab == "ongoing":
            qs = qs.filter(assigned_to=self.request.user)
        elif tab == "waiting":
            qs = qs.filter(status=Ticket.Status.WAITING_CUSTOMER)
        elif tab == "all":
            qs = qs.exclude(status__in=[Ticket.Status.CLOSED])
        elif tab == "resolved":
            qs = qs.filter(status=Ticket.Status.RESOLVED)
        else:  # pending — unassigned
            qs = qs.filter(assigned_to__isnull=True).exclude(
                status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
            )

        category = self.request.GET.get("category")
        if category:
            qs = qs.filter(category=category)

        priority = self.request.GET.get("priority")
        if priority:
            qs = qs.filter(priority=priority)

        search = self.request.GET.get("search")
        if search:
            qs = qs.filter(
                Q(reference__icontains=search)
                | Q(user__phone_number__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__full_name__icontains=search)
                | Q(related_reference__icontains=search)
            )

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tab"] = self.request.GET.get("tab", "pending")
        context["category_filter"] = self.request.GET.get("category", "")
        context["priority_filter"] = self.request.GET.get("priority", "")
        context["search"] = self.request.GET.get("search", "")
        context["categories"] = Ticket.Category.choices
        context["priorities"] = Ticket.Priority.choices
        context["staff_profile"] = getattr(self.request.user, "staff_profile", None)

        base_qs = Ticket.objects.all()
        pending_count = base_qs.filter(
            assigned_to__isnull=True
        ).exclude(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
        ).count()
        ongoing_count = base_qs.filter(
            assigned_to=self.request.user
        ).exclude(
            status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
        ).count()
        waiting_count = base_qs.filter(
            status=Ticket.Status.WAITING_CUSTOMER
        ).count()

        context["tabs"] = [
            ("pending", "Pending", pending_count),
            ("ongoing", "Ongoing", ongoing_count),
            ("waiting", "Waiting on Customer", waiting_count),
            ("all", "All Open", base_qs.exclude(status__in=[Ticket.Status.CLOSED]).count()),
            ("resolved", "Resolved", base_qs.filter(status=Ticket.Status.RESOLVED).count()),
        ]
        return context


class DeskTicketView(LoginRequiredMixin, View):
    """
    Staff ticket page — /desk/tickets/<uuid:ticket_id>/
    Chat with internal notes, canned replies, claim/assign/reassign,
    status/priority change, customer side panel.
    """

    @method_decorator(support_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request, ticket_id):
        ticket = get_object_or_404(
            Ticket.objects.select_related("user", "assigned_to"),
            id=ticket_id,
        )
        messages_qs = (
            ticket.messages.select_related("author", "author__staff_profile")
            .prefetch_related("attachments")
            .order_by("created_at")
        )
        events = ticket.events.select_related("actor").order_by("-created_at")[:20]
        canned_replies = CannedReply.objects.filter(is_active=True)

        # Customer side panel
        customer = ticket.user
        wallet = Wallet.objects.filter(user=customer).first()
        recent_transactions = (
            WalletTransaction.objects.filter(wallet=wallet)
            .order_by("-created_at")[:5]
            if wallet
            else []
        )

        # Linked order info
        linked_order = self._get_linked_order(ticket)

        # Can this staff member view exam PINs? Only leads.
        can_view_exam_pins = (
            request.user.is_staff
            and hasattr(request.user, "staff_profile")
            and request.user.staff_profile.role == "lead"
        )

        return render(
            request,
            "support/desk/ticket.html",
            {
                "ticket": ticket,
                "messages": messages_qs,
                "events": events,
                "canned_replies": canned_replies,
                "customer": customer,
                "wallet": wallet,
                "recent_transactions": recent_transactions,
                "linked_order": linked_order,
                "can_view_exam_pins": can_view_exam_pins,
                "is_lead": (
                    hasattr(request.user, "staff_profile")
                    and request.user.staff_profile.role == "lead"
                ),
            },
        )

    def _get_linked_order(self, ticket):
        """Fetch linked order info if related_type and related_reference are set."""
        if not ticket.related_type or not ticket.related_reference:
            return None

        model_map = {
            "vtu_order": VTUOrder,
            "airtime_order": AirtimeOrder,
            "cable_order": CableOrder,
            "electricity_order": ElectricityOrder,
            "exam_pin_order": ExamPinOrder,
            "smm_order": SMMOrder,
            "wallet_transaction": WalletTransaction,
        }

        model = model_map.get(ticket.related_type)
        if not model:
            return None

        try:
            obj = model.objects.get(reference=ticket.related_reference)
            return {
                "type": ticket.related_type,
                "reference": obj.reference,
                "status": getattr(obj, "status", "unknown"),
                "amount": getattr(obj, "amount", None),
                "url": None,
            }
        except model.DoesNotExist:
            return {"type": ticket.related_type, "reference": ticket.related_reference, "status": "not_found", "amount": None, "url": None}


@method_decorator(support_required, name="dispatch")
class DeskReplyView(View):
    """Staff reply to a ticket — POST /desk/tickets/<uuid:ticket_id>/reply/"""

    def post(self, request, ticket_id):
        ticket = get_object_or_404(Ticket, id=ticket_id)
        body = escape((request.POST.get("body") or "").strip())
        is_internal = request.POST.get("is_internal") == "1"

        if not body:
            return JsonResponse({"error": "Message cannot be empty."}, status=400)
        if len(body) > 2000:
            return JsonResponse({"error": "Message too long (max 2000 characters)."}, status=400)

        with transaction.atomic():
            msg = TicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                sender_type=TicketMessage.SenderType.STAFF,
                body=body,
                is_internal=is_internal,
            )

            # Handle attachments
            files = request.FILES.getlist("attachments")
            if len(files) > 3:
                return JsonResponse({"error": "Maximum 3 attachments per message."}, status=400)
            for f in files:
                TicketAttachment.objects.create(
                    message=msg,
                    file=f,
                    filename=f.name,
                    content_type=f.content_type or "",
                    size=f.size,
                )

            # Update ticket state
            ticket.last_staff_message_at = timezone.now()
            if not ticket.first_response_at:
                ticket.first_response_at = timezone.now()
            if ticket.status == Ticket.Status.WAITING_CUSTOMER:
                ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save(
                update_fields=["last_staff_message_at", "first_response_at", "status", "updated_at"]
            )

            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.SYSTEM_MESSAGE,
                description="Staff replied",
                metadata={"internal": is_internal},
            )

        # Notify customer if not internal
        if not is_internal:
            from apps.notifications.models import Notification
            from apps.notifications.services import send_push_notification

            Notification.add(
                user=ticket.user,
                title=f"Hero replied on {ticket.reference}",
                description=body[:100],
                level="info",
            )
            send_push_notification(
                user=ticket.user,
                title=f"Hero replied on {ticket.reference}",
                body=body[:200],
                action_url=f"{settings.SITE_URL}/support/{ticket.reference}/",
                level="info",
            )

        return JsonResponse({"status": "ok", "message_id": str(msg.id)})


@method_decorator(support_required, name="dispatch")
class DeskActionView(View):
    """
    Staff ticket actions — POST /desk/tickets/<uuid:ticket_id>/action/
    Actions: claim, assign, unassign, status_change, priority_change, internal_note
    """

    def post(self, request, ticket_id):
        ticket = get_object_or_404(Ticket, id=ticket_id)
        action = request.POST.get("action", "")

        if action == "claim":
            if ticket.assigned_to and ticket.assigned_to != request.user:
                return JsonResponse({"error": "Ticket already assigned."}, status=400)
            ticket.assigned_to = request.user
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save(update_fields=["assigned_to", "status", "updated_at"])
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.ASSIGNMENT,
                description=f"Claimed by {request.user.full_name or request.user.phone_number}",
            )
            return JsonResponse({"status": "ok", "action": "claim"})

        if action == "unassign":
            if not request.user.is_staff:
                return JsonResponse({"error": "Unauthorized."}, status=403)
            ticket.assigned_to = None
            ticket.save(update_fields=["assigned_to", "updated_at"])
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.ASSIGNMENT,
                description="Unassigned",
            )
            return JsonResponse({"status": "ok", "action": "unassign"})

        if action == "assign":
            # Leads only
            if not (
                hasattr(request.user, "staff_profile")
                and request.user.staff_profile.role == "lead"
            ):
                return JsonResponse({"error": "Leads only."}, status=403)
            staff_id = request.POST.get("staff_id")
            if not staff_id:
                return JsonResponse({"error": "staff_id required."}, status=400)
            try:
                staff = User.objects.get(id=staff_id, is_staff=True)
            except User.DoesNotExist:
                return JsonResponse({"error": "Staff not found."}, status=404)
            ticket.assigned_to = staff
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save(update_fields=["assigned_to", "status", "updated_at"])
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.ASSIGNMENT,
                description=f"Assigned to {staff.full_name or staff.phone_number}",
                metadata={"assigned_to": str(staff.id)},
            )
            return JsonResponse({"status": "ok", "action": "assign"})

        if action == "status_change":
            new_status = request.POST.get("status")
            valid_statuses = [c[0] for c in Ticket.Status.choices]
            if new_status not in valid_statuses:
                return JsonResponse({"error": "Invalid status."}, status=400)
            old_status = ticket.status
            ticket.status = new_status
            if new_status == Ticket.Status.RESOLVED:
                ticket.resolved_at = timezone.now()
            ticket.save(update_fields=["status", "resolved_at", "updated_at"])
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.STATUS_CHANGE,
                description=f"Status changed from {old_status} to {new_status}",
                metadata={"old": old_status, "new": new_status},
            )
            # Notify customer of status change
            if new_status != old_status:
                from apps.notifications.models import Notification
                from apps.notifications.services import send_push_notification

                status_labels = dict(Ticket.Status.choices)
                Notification.add(
                    user=ticket.user,
                    title=f"Ticket {ticket.reference} status updated",
                    description=f"Your ticket status changed to {status_labels.get(new_status, new_status)}.",
                    level="info",
                )
                send_push_notification(
                    user=ticket.user,
                    title=f"Ticket {ticket.reference} status updated",
                    body=f"Your ticket status changed to {status_labels.get(new_status, new_status)}.",
                    action_url=f"{settings.SITE_URL}/support/{ticket.reference}/",
                    level="info",
                )
            return JsonResponse({"status": "ok", "action": "status_change", "new_status": new_status})

        if action == "priority_change":
            new_priority = request.POST.get("priority")
            valid_priorities = [c[0] for c in Ticket.Priority.choices]
            if new_priority not in valid_priorities:
                return JsonResponse({"error": "Invalid priority."}, status=400)
            old_priority = ticket.priority
            ticket.priority = new_priority
            # Recompute SLA due date from ticket creation time (1h High, 4h Normal).
            hours = 1 if new_priority == Ticket.Priority.HIGH else 4
            ticket.sla_due_at = ticket.created_at + timedelta(hours=hours)
            ticket.save(update_fields=["priority", "sla_due_at", "updated_at"])
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.STATUS_CHANGE,
                description=(
                    f"Priority changed from {old_priority} to {new_priority}; "
                    f"SLA due at {ticket.sla_due_at}"
                ),
                metadata={
                    "old_priority": old_priority,
                    "new_priority": new_priority,
                    "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
                },
            )
            return JsonResponse({
                "status": "ok",
                "action": "priority_change",
                "new_priority": new_priority,
                "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
            })

        if action == "internal_note":
            body = escape((request.POST.get("body") or "").strip())
            if not body:
                return JsonResponse({"error": "Note cannot be empty."}, status=400)
            msg = TicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                sender_type=TicketMessage.SenderType.STAFF,
                body=body,
                is_internal=True,
            )
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                event_type=TicketEvent.EventType.INTERNAL_NOTE,
                description="Internal note added",
            )
            return JsonResponse({"status": "ok", "action": "internal_note", "message_id": str(msg.id)})

        return JsonResponse({"error": "Unknown action."}, status=400)
