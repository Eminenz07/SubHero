from decimal import Decimal
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.views import View

from apps.core.mixins import PinRequiredMixin
from apps.core.utils import get_client_ip, generate_reference
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import InsufficientBalanceError, WalletFrozenError
from apps.smm.models import SMMService, SMMOrder
from apps.smm.tasks import process_smm_order, refund_smm_order
from apps.smm.platforms import get_active_platforms, PLATFORMS_META, get_platform_meta

logger = logging.getLogger(__name__)

# SSRF Protection: Allowed social media domains (PRD Section 7.2)
ALLOWED_SMM_DOMAINS = [
    "instagram.com", "tiktok.com", "youtube.com", "twitter.com", "x.com",
    "t.me", "telegram.me", "telegram.dog", "telegram.org",
    "open.spotify.com", "facebook.com", "fb.me", "fb.com",
    "reddit.com", "whatsapp.com", "wa.me", "linkedin.com",
    "discord.gg", "discord.com", "twitch.tv", "snapchat.com",
    "pinterest.com", "threads.net", "audiomack.com", "music.apple.com",
    "kick.com", "boomplay.com", "mixcloud.com", "soundcloud.com",
    "twitch.tv", "store.steampowered.com"
]

TIERS = ["basic", "standard", "premium"]


class SmmIndexView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    SMM Social Media Booster Page — 3-tier card layout with dynamic platform icons.
    """
    template_name = "smm/index.html"

    def _get_context(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)

        # Get all active services that have been tier-classified by an admin
        all_services = SMMService.objects.filter(is_active=True, tier__isnull=False).exclude(tier="")

        if not all_services.exists():
            # Trigger sync if catalogue is empty (no tier-classified services)
            from apps.smm.tasks import sync_smm_catalogue
            sync_smm_catalogue()
            all_services = SMMService.objects.filter(is_active=True, tier__isnull=False).exclude(tier="")

        # Collect platform slugs that actually have classified services (dynamic, not hardcoded)
        active_platform_slugs = list(
            all_services.values_list("category", flat=True).distinct()
        )

        # Build ordered list of platform meta dicts
        platforms_meta = []
        seen = set()
        for slug in active_platform_slugs:
            if slug not in seen:
                platforms_meta.append(get_platform_meta(slug))
                seen.add(slug)
        platforms_meta.sort(key=lambda p: (p.get("order", 50), p.get("name", "")))

        return {
            "wallet": wallet,
            "platforms_meta": platforms_meta,
            "PLATFORMS_META_JSON": {slug: {
                "name": m["name"],
                "brand_color": m["brand_color"],
                "brand_bg": m["brand_bg"],
            } for slug, m in PLATFORMS_META.items()},
        }

    def get(self, request, *args, **kwargs):
        context = self._get_context(request)

        # Handle return-after-funding: pre-select platform/tier from query params
        prefill_platform = request.GET.get("platform", "")
        prefill_tier = request.GET.get("tier", "")
        context["prefill_platform"] = prefill_platform
        context["prefill_tier"] = prefill_tier

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        context = self._get_context(request)

        # 1. Parse inputs
        platform = request.POST.get("platform", "").lower().strip()
        service_id = request.POST.get("service_id", "").strip()
        service_name = request.POST.get("service_name", "")
        url = request.POST.get("url", "").strip()
        quantity_str = request.POST.get("quantity", "")
        pin = request.POST.get("pin", "")

        # 2. PIN Lockout check
        pin_attempts_key = f"pin_attempts:{request.user.id}"
        pin_lockout_key = f"pin_lockout:{request.user.id}"

        if cache.get(pin_lockout_key):
            lockout_mins = settings.PIN_LOCKOUT_SECONDS // 60
            messages.error(request, f"PIN locked due to too many attempts. Try again in {lockout_mins} minutes.")
            return render(request, self.template_name, context)

        # 3. Basic validations
        if not platform or not service_id or not url or not quantity_str or not pin:
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

        # 5. SSRF Link/Username Validation
        is_url = "://" in url or url.lower().startswith("www.") or ("." in url.split("/")[0])
        if is_url:
            valid_domain = any(domain in url.lower() for domain in ALLOWED_SMM_DOMAINS)
            if not valid_domain:
                messages.error(request, "Target URL is not a supported social media domain.")
                return render(request, self.template_name, context)

        # 6. Fetch Service strictly from DB (must be tier-classified)
        service = None
        try:
            service = SMMService.objects.get(id=service_id, is_active=True, tier__isnull=False)
        except (SMMService.DoesNotExist, ValueError):
            service = SMMService.objects.filter(
                name=service_name, category__iexact=platform,
                is_active=True, tier__isnull=False
            ).first()

        if not service:
            messages.error(request, "Selected SMM service is invalid, currently inactive, or not yet classified.")
            return render(request, self.template_name, context)

        if quantity < service.provider_min or quantity > service.provider_max:
            messages.error(request, f"Invalid quantity. Min: {service.provider_min:,} | Max: {service.provider_max:,}.")
            return render(request, self.template_name, context)

        unit_rate = service.subhero_price_per_1k / Decimal("1000.00")
        amount = Decimal(str(quantity)) * unit_rate

        from apps.admin_panel.models import SystemSetting
        try:
            smm_margin_pct = Decimal(SystemSetting.get("smm_profit_margin", "50.00"))
        except Exception:
            smm_margin_pct = Decimal("50.00")
        api_cost = (amount / (Decimal("1") + smm_margin_pct / 100)).quantize(Decimal("0.01"))

        # 7. Insufficient balance: return shortfall info for inline top-up nudge
        if wallet.balance < amount:
            shortfall = amount - wallet.balance
            # Round up to next ₦500 to cover current + next boost
            round_to = Decimal("500")
            topup_suggestion = ((shortfall / round_to).to_integral_value(rounding="ROUND_CEILING")) * round_to
            topup_suggestion = max(topup_suggestion, Decimal("500"))
            messages.error(
                request,
                f"INSUFFICIENT_BALANCE|{amount:.2f}|{wallet.balance:.2f}|{shortfall:.2f}|{topup_suggestion:.0f}|{platform}|{service.tier}"
            )
            return render(request, self.template_name, context)

        # 8. Idempotency / Duplicate check
        idempotency_key = f"smm_idem:{request.user.id}:{service.id}:{url}:{quantity}"
        if cache.get(idempotency_key) and request.POST.get("confirm_duplicate") != "1":
            messages.warning(request, "Duplicate Order Notice: An identical social boost order was placed less than a minute ago. Tap 'Confirm & Process Duplicate' below if you intend to place another order.")
            context["show_duplicate_confirm"] = True
            context["form_data"] = {"platform": platform, "service_id": service_id, "service_name": service_name, "url": url, "quantity": quantity_str}
            return render(request, self.template_name, context)

        # 9. Execute atomic wallet debit and dispatch task
        reference = generate_reference("SMM")
        try:
            with transaction.atomic():
                locked_wallet = Wallet.objects.select_for_update().get(id=wallet.id)
                if locked_wallet.is_frozen:
                    raise WalletFrozenError("Your wallet is frozen. Contact support.")
                if locked_wallet.balance < amount:
                    raise InsufficientBalanceError("Insufficient balance")

                balance_before = locked_wallet.balance
                locked_wallet.balance -= amount
                locked_wallet.save(update_fields=["balance"])

                txn = WalletTransaction.objects.create(
                    wallet=locked_wallet,
                    txn_type=WalletTransaction.TxnType.SMM,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=locked_wallet.balance,
                    reference=reference,
                    status=WalletTransaction.Status.PENDING,
                    description=f"Social Boost · {service.tier_title} · {platform.capitalize()} ×{quantity:,}",
                    ip_address=get_client_ip(request)
                )

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

            cache.set(idempotency_key, order.id, 60)
            process_smm_order.delay(order.id)

            receipt_context = {
                "wallet": locked_wallet,
                "txn": txn,
                "order": order,
                "platform": platform,
                "service_name": service.name,
                "service": service,
                "url": url,
                "quantity": quantity,
                "amount": amount,
            }
            return render(request, "smm/receipt.html", receipt_context)

        except InsufficientBalanceError:
            shortfall = amount - wallet.balance
            round_to = Decimal("500")
            topup_suggestion = ((shortfall / round_to).to_integral_value(rounding="ROUND_CEILING")) * round_to
            messages.error(
                request,
                f"INSUFFICIENT_BALANCE|{amount:.2f}|{wallet.balance:.2f}|{shortfall:.2f}|{topup_suggestion:.0f}|{platform}|{service.tier}"
            )
            return render(request, self.template_name, context)
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
            return render(request, self.template_name, context)
        except Exception:
            logger.exception("SMM purchase failed")
            try:
                _order = locals().get("order")
                if _order and _order.pk and _order.status not in (SMMOrder.Status.SUCCESS, SMMOrder.Status.FAILED):
                    _order.status = SMMOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_smm_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency SMM refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
            return render(request, self.template_name, context)


class SmmTierServicesAjaxView(LoginRequiredMixin, View):
    """
    Returns 3-tier service cards for a given platform.
    Called when user selects a platform icon button.
    Returns partial HTML with basic/standard/premium tier cards.
    """
    template_name = "smm/partials/_tier_cards.html"

    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower().strip()
        if not platform:
            return HttpResponse("")

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        platform_meta = get_platform_meta(platform)

        # Get all classified services for this platform
        services_qs = SMMService.objects.filter(
            category=platform, is_active=True, tier__isnull=False
        ).exclude(tier="").order_by("subhero_price_per_1k")

        # Organise into tier groups — pick the best representative per tier
        tier_groups = {}
        for svc in services_qs:
            if svc.tier not in tier_groups:
                tier_groups[svc.tier] = []
            tier_groups[svc.tier].append(svc)

        # For each tier, compute unit price
        for tier_key, svcs in tier_groups.items():
            for s in svcs:
                s.unit_price = s.subhero_price_per_1k / Decimal("1000.00")

        # Price anchoring: compare basic vs premium on a "30-day retention" basis
        basic_svcs = tier_groups.get("basic", [])
        premium_svcs = tier_groups.get("premium", [])
        price_anchor = None
        if basic_svcs and premium_svcs:
            b = basic_svcs[0]
            p = premium_svcs[0]
            # At 1000 units: how many basic repurchases needed to match premium's retention
            # Assumption: basic requires ~4 repurchases to sustain 30-day results premium gives once
            basic_true_cost = b.unit_price * 4 * 1000  # 4 repurchases for same 1000 units
            premium_one_cost = p.unit_price * 1000
            if basic_true_cost > 0:
                price_anchor = {
                    "basic_true_cost": basic_true_cost,
                    "premium_one_cost": premium_one_cost,
                    "basic_svc": b,
                    "premium_svc": p,
                    "savings": basic_true_cost - premium_one_cost,
                }

        context = {
            "platform": platform,
            "platform_meta": platform_meta,
            "tier_groups": {
                "basic": tier_groups.get("basic", []),
                "standard": tier_groups.get("standard", []),
                "premium": tier_groups.get("premium", []),
            },
            "wallet": wallet,
            "price_anchor": price_anchor,
            "tiers": TIERS,
        }
        return render(request, self.template_name, context)


class SmmTierCategoriesAjaxView(LoginRequiredMixin, View):
    """
    Returns <option> elements listing subcategories (Comments, Likes, Followers…)
    available for a given platform + tier combo.
    """
    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower().strip()
        tier = request.GET.get("tier", "").lower().strip()

        subcategories = SMMService.objects.filter(
            category=platform, tier=tier, is_active=True
        ).exclude(subcategory="").values_list("subcategory", flat=True).distinct().order_by("subcategory")

        html = '<option value="" disabled selected>-- Select Category --</option>'
        for sub in subcategories:
            html += f'<option value="{sub}">{sub}</option>'
        return HttpResponse(html)


class SmmServicesListAjaxView(LoginRequiredMixin, View):
    """
    Returns flat list of services for a given platform+tier (+optional subcategory).
    Called when user selects a tier or changes the category dropdown.
    """
    template_name = "smm/partials/_service_list.html"

    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower().strip()
        tier = request.GET.get("tier", "").lower().strip()
        subcategory = request.GET.get("subcategory", "").strip()

        services = SMMService.objects.filter(
            category=platform, tier=tier, is_active=True
        )
        if subcategory:
            services = services.filter(subcategory=subcategory)
        services = services.order_by("subhero_price_per_1k")

        for s in services:
            s.unit_price = s.subhero_price_per_1k / Decimal("1000.00")

        return render(request, self.template_name, {
            "services": services,
            "platform": platform,
            "tier": tier,
        })


# ─── Legacy / HTMX compatibility views ─────────────────────────────────────

class SmmCategoriesAjaxView(LoginRequiredMixin, View):
    """Returns unique active subcategories for the selected platform (legacy support)."""
    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower()
        subcategories = SMMService.objects.filter(
            category=platform, is_active=True
        ).values_list("subcategory", flat=True).distinct().order_by("subcategory")

        html = '<option value="" disabled selected>-- Select SMM Category --</option>'
        for sub in subcategories:
            if sub:
                html += f'<option value="{sub}">{sub}</option>'
        return HttpResponse(html)


class SmmServicesAjaxView(LoginRequiredMixin, View):
    """Returns service cards matching platform and category (legacy support)."""
    template_name = "smm/partials/_service_cards.html"

    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower()
        subcategory = request.GET.get("subcategory", "").strip()

        services = SMMService.objects.filter(
            category=platform, subcategory=subcategory, is_active=True
        ).order_by("subhero_price_per_1k")

        from apps.smm.tasks import fetch_smm_service_description
        for s in services:
            s.unit_price = s.subhero_price_per_1k / Decimal("1000.00")
            if not s.description:
                try:
                    desc = fetch_smm_service_description(s.provider_service_id)
                    if desc:
                        s.description = desc
                        s.save(update_fields=["description"])
                except Exception:
                    pass

        return render(request, self.template_name, {"services": services})


class SmmReceiptStatusAjaxView(LoginRequiredMixin, View):
    """HTMX status polling endpoint for SMM receipts."""
    template_name = "smm/partials/_receipt_content.html"

    def get(self, request, order_id, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from apps.smm.tasks import sync_single_smm_order

        order = get_object_or_404(SMMOrder, id=order_id, user=request.user)
        if order.status in [SMMOrder.Status.PROCESSING, SMMOrder.Status.PENDING]:
            order = sync_single_smm_order(order)

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


class SmmOrderProgressAjaxView(LoginRequiredMixin, View):
    """HTMX live progress polling endpoint for SMM orders."""
    template_name = "smm/partials/_order_progress.html"

    def get(self, request, order_id, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from apps.smm.tasks import sync_single_smm_order

        order = get_object_or_404(SMMOrder, id=order_id, user=request.user)
        if order.status in [SMMOrder.Status.PROCESSING, SMMOrder.Status.PENDING]:
            order = sync_single_smm_order(order)

        return render(request, self.template_name, {"order": order})
