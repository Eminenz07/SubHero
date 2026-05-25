"""
Wallet — Views
================
PRD Section 6.2: Wallet overview, funding info, P2P transfers,
transaction history with pagination and filters.
All views require login + PIN (via mixins).
"""

import logging

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django_ratelimit.decorators import ratelimit

from apps.core.mixins import LoginRequiredMixin, PinRequiredMixin
from apps.core.utils import get_client_ip, normalize_phone
from .forms import P2PTransferForm
from .models import Wallet, WalletTransaction
from .services import (
    DailyLimitExceededError,
    InsufficientBalanceError,
    RecipientNotFoundError,
    SelfTransferError,
    WalletFrozenError,
    transfer_p2p,
)

logger = logging.getLogger(__name__)


class WalletOverviewView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    PRD Table 27: /wallet/ — Wallet overview page.
    Shows balance, virtual account info, and recent transactions.
    """

    template_name = "wallet/overview.html"

    def get(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)
        recent_txns = wallet.transactions.all()[:5]

        return render(request, self.template_name, {
            "wallet": wallet,
            "recent_txns": recent_txns,
        })


class FundWalletView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    PRD Table 27: /wallet/fund/ — Shows user's virtual account for bank transfer.
    PRD Section 6.2.1: User funds by transferring to their Providus account.
    """

    template_name = "wallet/fund.html"

    def get(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)

        return render(request, self.template_name, {
            "wallet": wallet,
            "min_amount": settings.FUND_MIN_AMOUNT,
            "max_amount": settings.FUND_MAX_AMOUNT,
        })


class P2PTransferView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    PRD Table 27: /wallet/transfer/ — P2P transfer form.
    PRD Section 6.2.3: Fee-free, atomic, min ₦50, max ₦100,000.
    Rate limit: 20 req/hour per user (PRD Table 21).
    """

    template_name = "wallet/transfer.html"

    @method_decorator(ratelimit(key="user", rate="20/h", method="POST", block=True))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)
        form = P2PTransferForm()

        return render(request, self.template_name, {
            "form": form,
            "wallet": wallet,
        })

    def post(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)
        form = P2PTransferForm(request.POST)

        if form.is_valid():
            recipient_phone = form.cleaned_data["recipient_phone"]
            amount = form.cleaned_data["amount"]
            pin = form.cleaned_data["pin"]
            client_ip = get_client_ip(request)

            # Verify PIN (PRD Section 6.1.3: 3 wrong attempts → 30-min freeze)
            pin_attempts_key = f"pin_attempts:{request.user.id}"
            pin_lockout_key = f"pin_lockout:{request.user.id}"

            if cache.get(pin_lockout_key):
                messages.error(request, "PIN locked. Try again in 30 minutes.")
                return render(request, self.template_name, {
                    "form": form, "wallet": wallet,
                })

            if not request.user.check_pin(pin):
                attempts = cache.get(pin_attempts_key, 0) + 1
                cache.set(pin_attempts_key, attempts, settings.PIN_LOCKOUT_SECONDS)

                if attempts >= settings.MAX_PIN_ATTEMPTS:
                    cache.set(pin_lockout_key, True, settings.PIN_LOCKOUT_SECONDS)
                    cache.delete(pin_attempts_key)
                    logger.warning(
                        "PIN lockout: user=%s, ip=%s",
                        request.user.id, client_ip,
                    )
                    messages.error(request, "Too many incorrect PIN attempts. Wallet locked for 30 minutes.")
                else:
                    messages.error(request, f"Incorrect PIN. {settings.MAX_PIN_ATTEMPTS - attempts} attempts remaining.")

                return render(request, self.template_name, {
                    "form": form, "wallet": wallet,
                })

            # Reset PIN attempts on success
            cache.delete(pin_attempts_key)

            # Execute transfer
            try:
                send_txn, recv_txn = transfer_p2p(
                    sender_user=request.user,
                    recipient_phone=recipient_phone,
                    amount=amount,
                    ip_address=client_ip,
                )

                logger.info(
                    "P2P success: user=%s, ref=%s, amount=%s, ip=%s",
                    request.user.id, send_txn.reference, amount, client_ip,
                )

                messages.success(
                    request,
                    f"₦{amount:,.2f} sent successfully to {recipient_phone}!"
                )
                return redirect("wallet:transaction_detail", txn_id=send_txn.id)

            except RecipientNotFoundError:
                messages.error(request, "Recipient not found. Please check the phone number.")
            except SelfTransferError:
                messages.error(request, "You cannot transfer to yourself.")
            except InsufficientBalanceError as e:
                messages.error(request, str(e))
            except WalletFrozenError as e:
                messages.error(request, str(e))
            except DailyLimitExceededError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error("P2P transfer error: user=%s, error=%s", request.user.id, str(e))
                messages.error(request, "Transfer failed. Please try again.")

        return render(request, self.template_name, {
            "form": form, "wallet": wallet,
        })


class TransactionHistoryView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    PRD Table 27: /wallet/transactions/ — Paginated transaction list.
    PRD: 20 items per page, filterable by type.
    """

    template_name = "wallet/transactions.html"

    def get(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)
        txn_type = request.GET.get("type", "")

        queryset = wallet.transactions.all()
        if txn_type and txn_type in dict(WalletTransaction.TxnType.choices):
            queryset = queryset.filter(txn_type=txn_type)

        paginator = Paginator(queryset, 20)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Build filter options
        type_choices = [("", "All")] + list(WalletTransaction.TxnType.choices)

        return render(request, self.template_name, {
            "wallet": wallet,
            "page_obj": page_obj,
            "type_choices": type_choices,
            "active_type": txn_type,
        })


class TransactionDetailView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    PRD Table 27: /wallet/transactions/<uuid>/ — Single transaction detail.
    IDOR guard: filtered by request.user's wallet (PRD Section 7.2).
    """

    template_name = "wallet/transaction_detail.html"

    def get(self, request, txn_id):
        wallet = get_object_or_404(Wallet, user=request.user)
        txn = get_object_or_404(
            WalletTransaction,
            id=txn_id,
            wallet=wallet,  # IDOR protection
        )

        # Retrieve any background order associated with this transaction or its refund
        order = None
        order_type = None
        ref = txn.reference
        if ref.startswith("REFUND-"):
            ref = ref.replace("REFUND-", "")

        from apps.vtu.models import VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder
        from apps.smm.models import SMMOrder

        order = VTUOrder.objects.filter(reference=ref).first()
        if order:
            order_type = "data"
        else:
            order = AirtimeOrder.objects.filter(reference=ref).first()
            if order:
                order_type = "airtime"
            else:
                order = CableOrder.objects.filter(reference=ref).first()
                if order:
                    order_type = "cable"
                else:
                    order = ElectricityOrder.objects.filter(reference=ref).first()
                    if order:
                        order_type = "electricity"
                    else:
                        order = ExamPinOrder.objects.filter(reference=ref).first()
                        if order:
                            order_type = "exam_pin"
                        else:
                            order = SMMOrder.objects.filter(reference=ref).first()
                            if order:
                                order_type = "smm"

        return render(request, self.template_name, {
            "wallet": wallet,
            "txn": txn,
            "order": order,
            "order_type": order_type,
        })



class LookupRecipientView(LoginRequiredMixin, View):
    """
    HTMX endpoint: look up a SubHero user by phone number.
    Returns an HTML fragment with the recipient name or error.
    PRD Section 6.2.3: Recipient lookup before PIN prompt.
    """

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        phone = request.POST.get("recipient_phone", "").strip()
        if not phone:
            return HttpResponse("")

        phone = normalize_phone(phone)

        try:
            user = User.objects.get(phone_number=phone, is_active=True)
            if user.id == request.user.id:
                return HttpResponse(
                    '<div class="text-xs text-status-danger mt-1">You cannot transfer to yourself.</div>'
                )
            # Mask name for privacy: show first name + last initial
            parts = user.full_name.split()
            if len(parts) >= 2:
                display = f"{parts[0]} {parts[-1][0]}."
            else:
                display = parts[0] if parts else "SubHero User"
            return HttpResponse(
                f'<div class="text-xs text-brand-primary font-medium mt-1">✓ {display}</div>'
            )
        except User.DoesNotExist:
            return HttpResponse(
                '<div class="text-xs text-status-danger mt-1">User not found.</div>'
            )
