"""
Payments — Webhook & Payment Views
==================================
Handles interactive card payments, bank callbacks, and live transactional webhooks.
Uses Squad (by GTBank) for funding logic.
"""

import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.wallet.models import Wallet
from apps.payments.services import (
    initialize_card_payment,
    verify_webhook_signature
)
from apps.payments.tasks import credit_wallet

logger = logging.getLogger(__name__)


@login_required
def fund_wallet_page(request):
    """
    PRD Section 6.2.1: Renders the Fund Wallet page.
    Supplies the Squad public key to the frontend context for Inline checkout.
    """
    wallet = get_object_or_404(Wallet, user=request.user)
    context = {
        "wallet": wallet,
        "squad_public_key": settings.SQUAD_PUBLIC_KEY,
        "min_amount": settings.FUND_MIN_AMOUNT,
        "max_amount": settings.FUND_MAX_AMOUNT,
        "daily_limit": settings.FUND_DAILY_LIMIT,
    }
    return render(request, "wallet/fund.html", context)


@method_decorator(login_required, name="dispatch")
class InitiateCardPaymentView(View):
    """
    AJAX endpoint called by the checkout UI to initialize a payment session on Squad
    and acquire a secure checkout URL.
    """
    def post(self, request, *args, **kwargs):
        amount_str = request.POST.get("amount", "").strip()
        if not amount_str:
            return JsonResponse({"error": "Amount is required."}, status=400)
            
        try:
            amount = Decimal(amount_str)
            if amount < settings.FUND_MIN_AMOUNT:
                return JsonResponse({"error": f"Minimum funding amount is ₦{settings.FUND_MIN_AMOUNT}."}, status=400)
            if amount > settings.FUND_MAX_AMOUNT:
                return JsonResponse({"error": f"Maximum single funding amount is ₦{settings.FUND_MAX_AMOUNT:,}."}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount format. Please enter a valid decimal number."}, status=400)

        # Call Squad API service
        result = initialize_card_payment(amount, request.user.email, request.user.id)
        
        if result.get("success"):
            return JsonResponse({
                "checkout_url": result["checkout_url"],
                "reference": result["reference"]
            })
        else:
            return JsonResponse({"error": result.get("message", "Could not initialize payment with gateway.")}, status=400)


@login_required
def payment_callback(request):
    """
    Redirect endpoint from Squad after a card checkout attempt.
    """
    reference = request.GET.get("transaction_ref", request.GET.get("reference", ""))
    context = {
        "reference": reference,
        "back_url": "/dashboard/"
    }
    return render(request, "wallet/payment_processing.html", context)


@method_decorator(csrf_exempt, name="dispatch")
class SquadWebhookView(View):
    """
    Highly secure payment listener that processes real-time transaction notifications from Squad.
    Deduplicates requests, validates digital signatures, and fires async crediting workflows.
    """
    DUPLICATE_TTL = 48 * 60 * 60  # 48 Hours idempotency window

    def post(self, request, *args, **kwargs):
        # 1. Signature retrieval & validation
        sig = request.headers.get("x-squad-encrypted-body", "")
        if not sig:
            logger.error("Squad Webhook error: Missing digital signature header 'x-squad-encrypted-body'.")
            return HttpResponse("Missing signature header", status=400)

        # 2. Digital HMAC payload signature check
        if not verify_webhook_signature(request.body, sig):
            logger.error("Squad Webhook error: Digital signature HMAC validation failed.")
            return HttpResponse("Signature verification failed", status=400)

        # 3. Parse JSON Body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            logger.error("Squad Webhook error: Received invalid non-JSON body.")
            return HttpResponse("Invalid JSON", status=400)

        event = data.get("Event", "")
        body = data.get("Body", {})
        
        logger.info("Squad Webhook received event: %s", event)

        # 4. Handle only completed payment events (card or bank transfer)
        if event not in ["charge_completed", "virtual_account_payment"]:
            logger.info("Squad Webhook: Ignoring unhandled event type: %s", event)
            return HttpResponse("Event ignored", status=200)

        # 5. Extract payment variables
        transaction_ref = body.get("transaction_ref") or body.get("reference")
        if not transaction_ref:
            logger.error("Squad Webhook error: Webhook body is missing transaction reference.")
            return HttpResponse("Missing transaction reference", status=400)

        amount_kobo = body.get("amount", 0)
        try:
            amount_naira = Decimal(str(amount_kobo)) / Decimal("100.00")
        except (InvalidOperation, ValueError):
            logger.error("Squad Webhook error: Invalid amount format in body: %s", amount_kobo)
            return HttpResponse("Invalid amount", status=400)

        user_id = body.get("meta", {}).get("user_id", "")
        virtual_account_number = body.get("virtual_account_number", "")

        # 6. Idempotency Check via Redis cache
        redis_key = f"squad_webhook:{transaction_ref}"
        if cache.get(redis_key):
            logger.warning("Squad Webhook duplicate detected: ref=%s (request ignored)", transaction_ref)
            return HttpResponse("Webhook reference already processed", status=200)

        # Cache reference immediately (48-hour timeout window)
        cache.set(redis_key, "1", timeout=self.DUPLICATE_TTL)

        # 7. Dispatch Celery background worker to safely credit the user's wallet
        credit_wallet.delay(
            transaction_ref=transaction_ref,
            amount_naira=str(amount_naira),
            user_id=str(user_id) if user_id else "",
            virtual_account_number=str(virtual_account_number) if virtual_account_number else "",
            raw_payload=data
        )

        # 8. Return 200 OK fast to avoid transaction retries from Squad
        return HttpResponse("Accepted", status=200)
