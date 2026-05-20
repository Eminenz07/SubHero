"""
VTU — Views
===========
"""

from decimal import Decimal
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.shortcuts import render, redirect
from django.views import View

from apps.core.mixins import PinRequiredMixin
from apps.core.utils import get_client_ip, generate_reference, normalize_phone
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import debit_wallet, InsufficientBalanceError, WalletFrozenError

logger = logging.getLogger(__name__)

# Data packages definition
DATA_PLANS = {
    "1gb": {"name": "1GB", "price": Decimal("350.00"), "validity": "30 Days"},
    "2gb": {"name": "2GB", "price": Decimal("650.00"), "validity": "30 Days"},
    "5gb": {"name": "5GB", "price": Decimal("1500.00"), "validity": "30 Days"},
    "10gb": {"name": "10GB", "price": Decimal("2800.00"), "validity": "30 Days"},
    "20gb": {"name": "20GB", "price": Decimal("5000.00"), "validity": "30 Days"},
    "50gb": {"name": "50GB", "price": Decimal("10500.00"), "validity": "30 Days"},
}

class BuyDataView(LoginRequiredMixin, PinRequiredMixin, View):
    """Buy Mobile Data Package View."""

    def get(self, request, *args, **kwargs):
        # Fetch user's wallet
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        context = {
            "wallet": wallet,
            "plans": DATA_PLANS,
        }
        return render(request, "vtu/data.html", context)

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        
        # 1. Parse inputs
        network = request.POST.get("network", "").lower()
        phone_number = request.POST.get("phone_number", "").strip()
        plan_id = request.POST.get("plan_id", "")
        pin = request.POST.get("pin", "")

        context = {
            "wallet": wallet,
            "plans": DATA_PLANS,
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
            return render(request, "vtu/data.html", context)

        # 3. Basic validations
        if not network or not phone_number or not plan_id or not pin:
            messages.error(request, "All fields (including Transaction PIN) are required.")
            return render(request, "vtu/data.html", context)

        if network not in ["mtn", "airtel", "glo", "9mobile"]:
            messages.error(request, "Invalid network selected.")
            return render(request, "vtu/data.html", context)

        normalized_phone = normalize_phone(phone_number)
        if not normalized_phone.startswith("+234") or len(normalized_phone) != 14:
            messages.error(request, "Please enter a valid 11-digit Nigerian phone number.")
            return render(request, "vtu/data.html", context)

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
            return render(request, "vtu/data.html", context)

        # Reset PIN attempts on successful entry
        cache.delete(pin_attempts_key)

        # 5. Calculate price
        plan = DATA_PLANS.get(plan_id)
        if not plan:
            messages.error(request, "Invalid data plan selected.")
            return render(request, "vtu/data.html", context)

        amount = plan["price"]
        plan_name = plan["name"]

        # 6. Execute atomic wallet debit
        reference = generate_reference("VTU")
        try:
            txn = debit_wallet(
                wallet_id=wallet.id,
                amount=amount,
                txn_type=WalletTransaction.TxnType.VTU,
                reference=reference,
                description=f"{network.upper()} {plan_name} Data purchase for {phone_number}",
                metadata={
                    "network": network,
                    "phone_number": phone_number,
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                },
                ip_address=get_client_ip(request)
            )
            # Render success receipt
            receipt_context = {
                "wallet": wallet,
                "txn": txn,
                "network": network,
                "phone_number": phone_number,
                "plan_name": plan_name,
                "amount": amount,
            }
            return render(request, "vtu/receipt.html", receipt_context)

        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{amount:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
            return render(request, "vtu/data.html", context)
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen by administrator. Please contact support.")
            return render(request, "vtu/data.html", context)
        except Exception as e:
            logger.exception("VTU data purchase failed")
            messages.error(request, f"Transaction failed: {str(e)}")
            return render(request, "vtu/data.html", context)
