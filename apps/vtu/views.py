from decimal import Decimal
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import render, redirect
from django.views import View

from apps.core.mixins import PinRequiredMixin
from apps.core.utils import get_client_ip, generate_reference, normalize_phone
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import InsufficientBalanceError, WalletFrozenError
from apps.vtu.models import VTUPlan, VTUOrder
from apps.vtu.tasks import process_vtu_order

logger = logging.getLogger(__name__)

class BuyDataView(LoginRequiredMixin, PinRequiredMixin, View):
    """Buy Mobile Data Package View with active CheapDataHub background integration."""
    template_name = "vtu/data.html"

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        
        # Load plans from DB
        plans = VTUPlan.objects.filter(is_active=True)
        if not plans.exists():
            from apps.vtu.tasks import sync_vtu_plans
            sync_vtu_plans()
            plans = VTUPlan.objects.filter(is_active=True)

        plans_dict = {}
        for p in plans:
            plans_dict[p.plan_id] = {
                "name": p.name,
                "price": p.subhero_price,
                "validity": p.validity,
                "network": p.network
            }

        context = {
            "wallet": wallet,
            "plans": plans_dict,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        
        # 1. Parse inputs
        network = request.POST.get("network", "").lower()
        phone_number = request.POST.get("phone_number", "").strip()
        plan_id = request.POST.get("plan_id", "")
        pin = request.POST.get("pin", "")

        # Reload plans for context re-rendering in case of errors
        plans = VTUPlan.objects.filter(is_active=True)
        plans_dict = {}
        for p in plans:
            plans_dict[p.plan_id] = {
                "name": p.name,
                "price": p.subhero_price,
                "validity": p.validity,
                "network": p.network
            }

        context = {
            "wallet": wallet,
            "plans": plans_dict,
            "form_data": {
                "network": network,
                "phone_number": phone_number,
                "plan_id": plan_id,
            }
        }

        # 2. Check PIN Lockout
        pin_attempts_key = f"pin_attempts:{request.user.id}"
        pin_lockout_key = f"pin_lockout:{request.user.id}"

        if cache.get(pin_lockout_key):
            messages.error(request, "PIN locked due to too many attempts. Try again in 30 minutes.")
            return render(request, self.template_name, context)

        # 3. Basic validations
        if not network or not phone_number or not plan_id or not pin:
            messages.error(request, "All fields (including Transaction PIN) are required.")
            return render(request, self.template_name, context)

        if network not in ["mtn", "airtel", "glo", "9mobile"]:
            messages.error(request, "Invalid network selected.")
            return render(request, self.template_name, context)

        normalized_phone = normalize_phone(phone_number)
        if not normalized_phone.startswith("+234") or len(normalized_phone) != 14:
            messages.error(request, "Please enter a valid 11-digit Nigerian phone number.")
            return render(request, self.template_name, context)

        # 4. Verify PIN
        if not request.user.check_pin(pin):
            attempts = cache.get(pin_attempts_key, 0) + 1
            cache.set(pin_attempts_key, attempts, 300)  # expires in 5m
            if attempts >= 3:
                cache.set(pin_lockout_key, True, 1800)  # 30 minutes lockout
                messages.error(request, "Incorrect PIN. You have been locked out for 30 minutes.")
            else:
                remaining = 3 - attempts
                messages.error(request, f"Incorrect transaction PIN. {remaining} attempts remaining.")
            return render(request, self.template_name, context)

        # Reset PIN attempts on successful entry
        cache.delete(pin_attempts_key)

        # 5. Look up plan price from database (NEVER trust client price input)
        try:
            plan = VTUPlan.objects.get(plan_id=plan_id, is_active=True)
        except VTUPlan.DoesNotExist:
            messages.error(request, "Invalid or inactive data plan selected.")
            return render(request, self.template_name, context)

        amount = plan.subhero_price
        plan_name = plan.name

        # Redis Idempotency Check (5 minutes TTL)
        idempotency_key = f"vtu_idempotency:{request.user.id}:{plan_id}:{normalized_phone}"
        if cache.get(idempotency_key):
            messages.error(request, "Duplicate order detected. Please wait 5 minutes before retrying.")
            return render(request, self.template_name, context)

        # 6. Execute atomic wallet debit and dispatch task
        reference = generate_reference("VTU")
        try:
            with transaction.atomic():
                # Lock wallet row
                locked_wallet = Wallet.objects.select_for_update().get(id=wallet.id)
                
                if locked_wallet.is_frozen:
                    raise WalletFrozenError("Your wallet is frozen. Contact support.")
                    
                if locked_wallet.balance < amount:
                    raise InsufficientBalanceError("Insufficient balance")

                # Debit wallet
                balance_before = locked_wallet.balance
                locked_wallet.balance -= amount
                locked_wallet.save(update_fields=["balance"])

                # Create transaction ledger entry
                txn = WalletTransaction.objects.create(
                    wallet=locked_wallet,
                    txn_type=WalletTransaction.TxnType.VTU,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=locked_wallet.balance,
                    reference=reference,
                    status=WalletTransaction.Status.SUCCESS,
                    description=f"{network.upper()} {plan_name} Data purchase for {phone_number}",
                    ip_address=get_client_ip(request)
                )

                # Create Order record
                order = VTUOrder.objects.create(
                    user=request.user,
                    network=network,
                    recipient=phone_number,
                    plan_id=plan_id,
                    plan_name=plan_name,
                    amount=amount,
                    reference=reference,
                    status=VTUOrder.Status.PROCESSING
                )

            # Set Redis idempotency lock
            cache.set(idempotency_key, order.id, 300)

            # Dispatch background Celery task
            process_vtu_order.delay(order.id)

            # Render receipt immediately
            receipt_context = {
                "wallet": locked_wallet,
                "txn": txn,
                "network": network,
                "phone_number": phone_number,
                "plan_name": plan_name,
                "amount": amount,
            }
            return render(request, "vtu/receipt.html", receipt_context)

        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{amount:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
            return render(request, self.template_name, context)
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
            return render(request, self.template_name, context)
        except Exception as e:
            logger.exception("VTU data purchase failed")
            messages.error(request, f"Transaction failed: {str(e)}")
            return render(request, self.template_name, context)


class VtuPlansAjaxView(LoginRequiredMixin, View):
    """
    Returns dynamically styled plan cards matching the selected mobile network tab.
    HTMX-native endpoint returning HTML.
    """
    template_name = "vtu/partials/_plan_cards.html"

    def get(self, request, *args, **kwargs):
        network = request.GET.get("network", "").lower()
        plans = VTUPlan.objects.filter(network=network, is_active=True).order_by("subhero_price")
        return render(request, self.template_name, {"plans": plans})
