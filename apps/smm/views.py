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
from apps.core.utils import get_client_ip, generate_reference
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import InsufficientBalanceError, WalletFrozenError
from apps.smm.models import SMMService, SMMOrder
from apps.smm.tasks import process_smm_order, refund_smm_order

logger = logging.getLogger(__name__)

# SSRF Protection: Allowed social media domains (PRD Section 7.2)
ALLOWED_SMM_DOMAINS = [
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "t.me",
    "open.spotify.com",
    "facebook.com",
    "fb.me",
    "fb.com",
    "reddit.com",
    "whatsapp.com",
    "wa.me",
    "linkedin.com",
    "discord.gg",
    "discord.com",
    "twitch.tv",
    "snapchat.com",
    "pinterest.com",
    "threads.net"
]

class SmmIndexView(LoginRequiredMixin, PinRequiredMixin, View):
    """SMM Social Media Booster Page View with background processing and SSRF protection."""
    template_name = "smm/index.html"

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)

        # Load active SMM services
        services = SMMService.objects.filter(is_active=True)
        if not services.exists():
            from apps.smm.tasks import sync_smm_catalogue
            sync_smm_catalogue()
            services = SMMService.objects.filter(is_active=True)

        rates_dict = {}
        platform_counts = {}
        for s in services:
            platform = s.category.lower()
            if platform not in rates_dict:
                rates_dict[platform] = {}
                platform_counts[platform] = 0
            
            if platform_counts[platform] < 15:
                # Unit rate is price per 1k divided by 1000
                rates_dict[platform][s.name] = s.subhero_price_per_1k / Decimal("1000.00")
                platform_counts[platform] += 1

        context = {
            "wallet": wallet,
            "rates": rates_dict,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)

        # 1. Parse inputs
        platform = request.POST.get("platform", "").lower()
        service_name = request.POST.get("service_name", "")
        url = request.POST.get("url", "").strip()
        quantity_str = request.POST.get("quantity", "")
        pin = request.POST.get("pin", "")

        # Reload services for context re-rendering in case of error
        services = SMMService.objects.filter(is_active=True)
        rates_dict = {}
        platform_counts = {}
        for s in services:
            plat = s.category.lower()
            if plat not in rates_dict:
                rates_dict[plat] = {}
                platform_counts[plat] = 0
            
            if platform_counts[plat] < 15:
                rates_dict[plat][s.name] = s.subhero_price_per_1k / Decimal("1000.00")
                platform_counts[plat] += 1

        context = {
            "wallet": wallet,
            "rates": rates_dict,
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
            lockout_mins = settings.PIN_LOCKOUT_SECONDS // 60
            messages.error(request, f"PIN locked due to too many attempts. Try again in {lockout_mins} minutes.")
            return render(request, self.template_name, context)

        # 3. Basic validations
        if not platform or not service_name or not url or not quantity_str or not pin:
            messages.error(request, "All fields (including Transaction PIN) are required.")
            return render(request, self.template_name, context)

        try:
            quantity = int(quantity_str)
            if quantity <= 0:
                raise ValueError()
        except ValueError:
            messages.error(request, "Please enter a valid positive quantity.")
            return render(request, self.template_name, context)

        # 4. Verify PIN
        if not request.user.check_pin(pin):
            attempts = cache.get(pin_attempts_key, 0) + 1
            cache.set(pin_attempts_key, attempts, 300)
            if attempts >= 3:
                cache.set(pin_lockout_key, True, settings.PIN_LOCKOUT_SECONDS)
                lockout_mins = settings.PIN_LOCKOUT_SECONDS // 60
                messages.error(request, f"Incorrect PIN. You have been locked out for {lockout_mins} minutes.")
            else:
                remaining = 3 - attempts
                messages.error(request, f"Incorrect transaction PIN. {remaining} attempts remaining.")
            return render(request, self.template_name, context)

        cache.delete(pin_attempts_key)

        # 5. SSRF Link Validation (PRD Section 7.2)
        valid_domain = False
        for domain in ALLOWED_SMM_DOMAINS:
            if domain in url.lower():
                valid_domain = True
                break
        
        if not valid_domain:
            messages.error(request, "SSRF Threat Detected: Target URL is not within whitelisted social media domains.")
            return render(request, self.template_name, context)

        # 6. Fetch Service strictly from database
        try:
            service = SMMService.objects.get(name=service_name, category__iexact=platform, is_active=True)
        except SMMService.DoesNotExist:
            messages.error(request, "Selected SMM service is invalid or currently inactive.")
            return render(request, self.template_name, context)

        # Verify min/max quantity limits
        if quantity < service.provider_min or quantity > service.provider_max:
            messages.error(request, f"Invalid quantity. Min allowed: {service.provider_min:,}, Max allowed: {service.provider_max:,}.")
            return render(request, self.template_name, context)

        # Compute price server-side
        unit_rate = service.subhero_price_per_1k / Decimal("1000.00")
        amount = Decimal(str(quantity)) * unit_rate

        from apps.admin_panel.models import SystemSetting
        try:
            smm_margin_pct = Decimal(SystemSetting.get("smm_profit_margin", "50.00"))
        except Exception:
            smm_margin_pct = Decimal("50.00")
        smm_margin = smm_margin_pct / Decimal("100")
        api_cost = (amount / (Decimal("1") + smm_margin)).quantize(Decimal("0.01"))

        # 7. Execute atomic wallet debit and dispatch process task
        reference = generate_reference("SMM")
        try:
            with transaction.atomic():
                locked_wallet = Wallet.objects.select_for_update().get(id=wallet.id)

                if locked_wallet.is_frozen:
                    raise WalletFrozenError("Your wallet is frozen. Contact support.")

                if locked_wallet.balance < amount:
                    raise InsufficientBalanceError("Insufficient balance")

                # Debit
                balance_before = locked_wallet.balance
                locked_wallet.balance -= amount
                locked_wallet.save(update_fields=["balance"])

                # Create transaction ledger
                txn = WalletTransaction.objects.create(
                    wallet=locked_wallet,
                    txn_type=WalletTransaction.TxnType.SMM,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=locked_wallet.balance,
                    reference=reference,
                    status=WalletTransaction.Status.PENDING,
                    description=f"Social Boost · {platform.capitalize()} {service_name} ×{quantity:,}",
                    ip_address=get_client_ip(request)
                )

                # Create Order
                order = SMMOrder.objects.create(
                    user=request.user,
                    service=service,
                    target_url=url,
                    quantity=quantity,
                    amount=amount,
                    api_cost=api_cost,
                    reference=reference,
                    status=SMMOrder.Status.PROCESSING
                )

            # Dispatch Celery background execution task
            process_smm_order.delay(order.id)

            # Render receipt
            receipt_context = {
                "wallet": locked_wallet,
                "txn": txn,
                "order": order,
                "platform": platform,
                "service_name": service_name,
                "url": url,
                "quantity": quantity,
                "amount": amount,
            }
            return render(request, "smm/receipt.html", receipt_context)

        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{amount:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
            return render(request, self.template_name, context)
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
            return render(request, self.template_name, context)
        except Exception:
            logger.exception("SMM purchase failed")
            # Emergency fallback: if the order was created and debited but task dispatch crashed, refund
            try:
                _order = locals().get('order')
                if _order and _order.pk and _order.status not in (SMMOrder.Status.SUCCESS, SMMOrder.Status.FAILED):
                    _order.status = SMMOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_smm_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency SMM refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
            return render(request, self.template_name, context)


class SmmCategoriesAjaxView(LoginRequiredMixin, View):
    """
    Returns unique active categories for the selected platform tab dynamically.
    HTMX-native endpoint returning HTML option elements.
    """
    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower()
        subcategories = SMMService.objects.filter(
            category=platform,
            is_active=True
        ).values_list("subcategory", flat=True).distinct().order_by("subcategory")

        from django.http import HttpResponse
        html = '<option value="" disabled selected>-- Select SMM Category --</option>'
        for sub in subcategories:
            if sub:
                html += f'<option value="{sub}">{sub}</option>'
        return HttpResponse(html)


class SmmServicesAjaxView(LoginRequiredMixin, View):
    """
    Returns dynamically styled service cards matching platform and category.
    HTMX-native endpoint returning partial HTML.
    """
    template_name = "smm/partials/_service_cards.html"

    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower()
        subcategory = request.GET.get("subcategory", "").strip()

        services = SMMService.objects.filter(
            category=platform,
            subcategory=subcategory,
            is_active=True
        ).order_by("subhero_price_per_1k")

        # Inject unit price into each service object for easy template consumption
        for s in services:
            s.unit_price = s.subhero_price_per_1k / Decimal("1000.00")

        return render(request, self.template_name, {"services": services})


class SmmReceiptStatusAjaxView(LoginRequiredMixin, View):
    """
    HTMX status polling endpoint for SMM receipts.
    """
    template_name = "smm/partials/_receipt_content.html"

    def get(self, request, order_id, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        order = get_object_or_404(SMMOrder, id=order_id, user=request.user)
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        txn = WalletTransaction.objects.filter(reference=order.reference).first()

        context = {
            "wallet": wallet,
            "txn": txn,
            "order": order,
            "platform": order.service.category,
            "service_name": order.service.name,
            "url": order.target_url,
            "quantity": order.quantity,
            "amount": order.amount,
        }
        return render(request, self.template_name, context)
