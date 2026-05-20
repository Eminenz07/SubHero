"""
SMM — Views
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
from apps.core.utils import get_client_ip, generate_reference
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import debit_wallet, InsufficientBalanceError, WalletFrozenError

logger = logging.getLogger(__name__)

# SMM Rate definition (cost per 1 unit)
SMM_RATES = {
    # platform -> service -> cost_per_unit
    "instagram": {
        "Instagram Followers": Decimal("0.80"),  # ₦800 per 1k
        "Instagram Likes": Decimal("0.20"),      # ₦200 per 1k
        "Instagram Views": Decimal("0.10"),      # ₦100 per 1k
        "Story Views": Decimal("0.15"),          # ₦150 per 1k
        "Post Comments": Decimal("12.00"),       # ₦1200 per 100
    },
    "tiktok": {
        "TikTok Followers": Decimal("1.20"),
        "TikTok Likes": Decimal("0.30"),
        "TikTok Views": Decimal("0.05"),
        "TikTok Shares": Decimal("0.15"),
    },
    "youtube": {
        "YouTube Subscribers": Decimal("15.00"),
        "YouTube Views": Decimal("0.80"),
        "YouTube Likes": Decimal("1.00"),
    },
    "twitter": {
        "Twitter Followers": Decimal("2.50"),
        "Twitter Likes": Decimal("0.50"),
        "Twitter Retweets": Decimal("0.80"),
    },
    "telegram": {
        "Telegram Members": Decimal("1.50"),
        "Telegram Post Views": Decimal("0.02"),
    },
    "spotify": {
        "Spotify Plays": Decimal("0.40"),
        "Spotify Followers": Decimal("0.60"),
    }
}

class SmmIndexView(LoginRequiredMixin, PinRequiredMixin, View):
    """SMM Social Media Booster Page View."""

    def get(self, request, *args, **kwargs):
        # Fetch user's wallet
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        context = {
            "wallet": wallet,
            "rates": SMM_RATES,
        }
        return render(request, "smm/index.html", context)

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        
        # 1. Parse inputs
        platform = request.POST.get("platform", "").lower()
        service_name = request.POST.get("service_name", "")
        url = request.POST.get("url", "").strip()
        quantity_str = request.POST.get("quantity", "")
        pin = request.POST.get("pin", "")

        context = {
            "wallet": wallet,
            "rates": SMM_RATES,
            "form_data": {
                "platform": platform,
                "service_name": service_name,
                "url": url,
                "quantity": quantity_str,
            }
        }

        # 2. Check PIN Lockout
        pin_attempts_key = f"pin_attempts:{request.user.id}"
        pin_lockout_key = f"pin_lockout:{request.user.id}"

        if cache.get(pin_lockout_key):
            messages.error(request, "PIN locked due to too many attempts. Try again in 30 minutes.")
            return render(request, "smm/index.html", context)

        # 3. Basic validations
        if not platform or not service_name or not url or not quantity_str or not pin:
            messages.error(request, "All fields (including Transaction PIN) are required.")
            return render(request, "smm/index.html", context)

        try:
            quantity = int(quantity_str)
            if quantity <= 0:
                raise ValueError()
        except ValueError:
            messages.error(request, "Please enter a valid positive quantity.")
            return render(request, "smm/index.html", context)

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
            return render(request, "smm/index.html", context)

        # Reset PIN attempts on successful entry
        cache.delete(pin_attempts_key)

        # 5. Calculate rate & cost
        platform_rates = SMM_RATES.get(platform)
        if not platform_rates:
            messages.error(request, "Invalid platform selected.")
            return render(request, "smm/index.html", context)

        rate = platform_rates.get(service_name)
        if not rate:
            # Fallback default rate if name not matches exactly
            rate = Decimal("0.50")

        amount = Decimal(str(quantity)) * rate

        # 6. Execute atomic wallet debit
        reference = generate_reference("SMM")
        try:
            txn = debit_wallet(
                wallet_id=wallet.id,
                amount=amount,
                txn_type=WalletTransaction.TxnType.SMM,
                reference=reference,
                description=f"{service_name} ×{quantity:,} for {url}",
                metadata={
                    "platform": platform,
                    "service_name": service_name,
                    "url": url,
                    "quantity": quantity,
                },
                ip_address=get_client_ip(request)
            )
            # Render success receipt
            receipt_context = {
                "wallet": wallet,
                "txn": txn,
                "platform": platform,
                "service_name": service_name,
                "url": url,
                "quantity": quantity,
                "amount": amount,
            }
            return render(request, "smm/receipt.html", receipt_context)

        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{amount:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
            return render(request, "smm/index.html", context)
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen by administrator. Please contact support.")
            return render(request, "smm/index.html", context)
        except Exception as e:
            logger.exception("SMM purchase failed")
            messages.error(request, f"Transaction failed: {str(e)}")
            return render(request, "smm/index.html", context)
