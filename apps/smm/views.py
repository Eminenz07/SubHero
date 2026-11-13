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
from apps.wallet.services import InsufficientBalanceError, WalletFrozenError, credit_wallet
from apps.smm.models import SMMService, SMMOrder
from apps.smm.tasks import process_smm_order, refund_smm_order
from apps.smm.platforms import get_active_platforms, PLATFORMS_META, get_platform_meta
from apps.smm.tier_info import TIER_INFO, TIER_FOOTER, ACK_DROP_TEXT, parse_service_facts

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
            # Catalogue empty (no tier-classified services): kick off a sync in the
            # background, at most once per 10 minutes, instead of blocking the request.
            if cache.add("smm_catalogue_sync_lock", 1, 600):
                import threading
                from apps.smm.tasks import sync_smm_catalogue

                def _bg_sync():
                    try:
                        sync_smm_catalogue()
                    except Exception:
                        logger.exception("Background SMM catalogue sync failed")

                threading.Thread(target=_bg_sync, daemon=True).start()

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
            "tier_info": TIER_INFO,
            "tier_info_js": {"tiers": TIER_INFO, "footer": TIER_FOOTER},
            "tier_footer": TIER_FOOTER,
            "ack_drop_text": ACK_DROP_TEXT,
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

        if service.tier == "basic" and request.POST.get("ack_drop") != "1":
            messages.error(request, "Please confirm you understand some engagement may drop over time before ordering a Quick Boost.")
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
            # Add deposit fee so the net credited amount covers the shortfall.
            # Squad deducts ₦20 below ₦1,000 and ₦50 at ₦1,000 and above.
            deposit_fee = Decimal("20.00") if topup_suggestion < Decimal("1000.00") else Decimal("50.00")
            topup_suggestion += deposit_fee
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
            context["form_data"] = {"platform": platform, "service_id": service_id, "service_name": service_name, "url": url, "quantity": quantity_str, "ack_drop": request.POST.get("ack_drop", "")}
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
                "tier_meta": TIER_INFO.get(service.tier),
            }
            return render(request, "smm/receipt.html", receipt_context)

        except InsufficientBalanceError:
            shortfall = amount - wallet.balance
            round_to = Decimal("500")
            topup_suggestion = ((shortfall / round_to).to_integral_value(rounding="ROUND_CEILING")) * round_to
            # Add deposit fee so the net credited amount covers the shortfall.
            deposit_fee = Decimal("20.00") if topup_suggestion < Decimal("1000.00") else Decimal("50.00")
            topup_suggestion += deposit_fee
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
    Returns <option> elements listing subcategories available for a platform.

    tier is optional: when omitted (category-before-tier flow) all subcategories
    for the platform are returned; when provided, only that tier's subcategories.
    """
    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower().strip()
        tier = request.GET.get("tier", "").lower().strip()

        qs = SMMService.objects.filter(
            category=platform, is_active=True
        ).exclude(subcategory="")
        if tier:
            qs = qs.filter(tier=tier)
        subcategories = qs.values_list("subcategory", flat=True).distinct().order_by("subcategory")

        html = '<option value="" disabled selected>-- Select Category --</option>'
        for sub in subcategories:
            html += f'<option value="{sub}">{sub}</option>'
        return HttpResponse(html)


class SmmServicesListAjaxView(LoginRequiredMixin, View):
    """
    Returns flat list of services for a given platform+tier (+optional subcategory + search).
    Called when user selects a tier, changes the category dropdown, or types in the search bar.
    """
    template_name = "smm/partials/_service_list.html"

    def get(self, request, *args, **kwargs):
        platform = request.GET.get("platform", "").lower().strip()
        tier = request.GET.get("tier", "").lower().strip()
        subcategory = request.GET.get("subcategory", "").strip()
        search = request.GET.get("search", "").strip()

        services = SMMService.objects.filter(
            category=platform, tier=tier, is_active=True
        )
        if subcategory:
            services = services.filter(subcategory=subcategory)
        if search:
            services = services.filter(name__icontains=search)
        services = services.order_by("subhero_price_per_1k")

        for s in services:
            s.unit_price = s.subhero_price_per_1k / Decimal("1000.00")
            s.facts = parse_service_facts(s)

        return render(request, self.template_name, {
            "services": services,
            "platform": platform,
            "tier": tier,
            "search": search,
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
            "tier_meta": TIER_INFO.get(order.service.tier),
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


class SmmOrderCancelView(LoginRequiredMixin, PinRequiredMixin, View):
    """
    POST /smm/orders/<uuid:order_id>/cancel/

    User-initiated cancellation of a pending/processing SMM order.
    - PENDING: full local refund (order not yet sent to gateway)
    - PROCESSING: ask Ogaviral to cancel; refund based on gateway response
    Idempotent — safe to retry.
    """
    def post(self, request, order_id, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from apps.smm.tasks import cancel_smm_order_with_provider
        from apps.admin_panel.models import AdminLog

        order = get_object_or_404(SMMOrder, id=order_id, user=request.user)

        if order.status == SMMOrder.Status.CANCELLED:
            return JsonResponse({
                "success": True,
                "status": order.status,
                "message": "Order already cancelled",
            })

        if order.status not in [SMMOrder.Status.PENDING, SMMOrder.Status.PROCESSING]:
            return JsonResponse({
                "success": False,
                "error": f"Cannot cancel order in {order.get_status_display()} state",
            }, status=400)

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(user=request.user)
            order = SMMOrder.objects.select_for_update().get(id=order.id)

            if order.status == SMMOrder.Status.CANCELLED:
                return JsonResponse({
                    "success": True,
                    "status": order.status,
                    "message": "Order already cancelled",
                })

            if order.status not in [SMMOrder.Status.PENDING, SMMOrder.Status.PROCESSING]:
                return JsonResponse({
                    "success": False,
                    "error": f"Cannot cancel order in {order.get_status_display()} state",
                }, status=400)

            txn = WalletTransaction.objects.filter(
                reference=order.reference, txn_type=WalletTransaction.TxnType.SMM
            ).first()

            refund_amount = Decimal("0.00")
            gateway_rejected = False

            if order.status == SMMOrder.Status.PENDING:
                # Not yet sent to gateway — full local refund
                refund_amount = order.amount
                order.cancelled_by = "user"
                order.cancellation_reason = "User cancelled before gateway submission"
                order.status = SMMOrder.Status.CANCELLED
            else:
                # PROCESSING — sent to gateway; ask Ogaviral to cancel
                provider_cancel_result = cancel_smm_order_with_provider(order.provider_order_id)
                order.provider_cancel_requested = True

                if provider_cancel_result["cancelled"]:
                    remains = int(provider_cancel_result.get("remains", 0) or 0)
                    if remains > 0 and order.quantity > 0:
                        # Partial delivery — refund undelivered portion
                        refund_amount = (Decimal(remains) / Decimal(order.quantity)) * order.amount
                        order.status = SMMOrder.Status.PARTIAL
                        order.cancelled_by = "user"
                        order.cancellation_reason = (
                            f"User cancelled; partial delivery ({remains} of {order.quantity} undelivered)"
                        )
                    else:
                        refund_amount = order.amount
                        order.status = SMMOrder.Status.CANCELLED
                        order.cancelled_by = "user"
                        order.cancellation_reason = "User cancelled; gateway confirmed cancel"
                else:
                    # Gateway rejected cancel — order is being delivered
                    gateway_rejected = True
                    order.cancelled_by = ""
                    order.cancellation_reason = (
                        f"Cancel rejected by gateway: {provider_cancel_result.get('error', 'unknown')}"
                    )
                    # status stays PROCESSING

            order.save(update_fields=["status", "cancelled_by", "cancellation_reason", "provider_cancel_requested"])

            if txn:
                txn.status = WalletTransaction.Status.FAILED
                txn.save(update_fields=["status"])

            if refund_amount > 0 and not gateway_rejected:
                credit_wallet(
                    wallet_id=wallet.id,
                    amount=refund_amount,
                    txn_type=WalletTransaction.TxnType.REFUND,
                    reference=f"CANCEL-{order.reference}",
                    description=f"SMM Order Cancelled: {order.service.name} ({order.reference})",
                    metadata={"order_id": str(order.id), "original_reference": order.reference},
                    ip_address=get_client_ip(request),
                )

            try:
                AdminLog.objects.create(
                    admin_user=request.user,
                    action="SMM_ORDER_CANCEL",
                    target_type="SMMOrder",
                    target_id=str(order.id),
                    detail=(
                        f"User cancelled SMM order {order.reference} "
                        f"(status={order.status}, refund=₦{refund_amount:,.2f})"
                    ),
                    ip_address=get_client_ip(request),
                )
            except Exception:
                logger.exception("Failed to write AdminLog for SMM order cancellation")

        if gateway_rejected:
            return HttpResponse(
                "Order is already being delivered and cannot be cancelled.",
                status=400,
                content_type="text/plain",
            )

        # Re-fetch fresh context for receipt re-render (wallet balance updated)
        wallet_refresh, _ = Wallet.objects.get_or_create(user=request.user)
        txn_refresh = WalletTransaction.objects.filter(reference=order.reference).first()
        context = {
            "wallet": wallet_refresh,
            "txn": txn_refresh,
            "order": order,
            "platform": order.service.category,
            "service_name": order.service.name,
            "url": order.target_url,
            "quantity": order.quantity,
            "amount": order.amount,
            "tier_meta": TIER_INFO.get(order.service.tier),
        }
        return render(request, "smm/partials/_receipt_content.html", context)
