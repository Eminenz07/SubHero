"""
Payments — Webhook & Payment Views
==================================
Handles interactive card payments, bank callbacks, and live transactional webhooks.
Uses Squad (by GTBank) for funding logic.
"""

import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.wallet.models import Wallet
from apps.payments.models import WebhookLog
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
    pending_ref = request.session.get("pending_squad_ref", "")
    
    # Auto-clear pending_ref if it was already credited in DB
    if pending_ref and WalletTransaction.objects.filter(reference=pending_ref, status=WalletTransaction.Status.SUCCESS).exists():
        request.session.pop("pending_squad_ref", None)
        pending_ref = ""

    context = {
        "wallet": wallet,
        "squad_public_key": settings.SQUAD_PUBLIC_KEY,
        "min_amount": settings.FUND_MIN_AMOUNT,
        "max_amount": settings.FUND_MAX_AMOUNT,
        "daily_limit": settings.FUND_DAILY_LIMIT,
        "pending_squad_ref": pending_ref,
    }
    return render(request, "wallet/fund.html", context)


class InitiateCardPaymentView(View):
    """
    AJAX endpoint called by the checkout UI to initialize a payment session on Squad
    and acquire a secure checkout URL.
    """
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Session expired. Please log in again to continue."}, status=401)
            
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

        # Call Squad API service with dynamic site_url
        scheme = "https" if (request.is_secure() or not settings.DEBUG) else "http"
        site_url = f"{scheme}://{request.get_host()}"
        result = initialize_card_payment(amount, request.user.email, request.user.id, site_url=site_url)
        
        if result.get("success"):
            request.session["pending_squad_ref"] = result["reference"]
            return JsonResponse({
                "checkout_url": result["checkout_url"],
                "reference": result["reference"]
            })
        else:
            return JsonResponse({"error": result.get("message", "Could not initialize payment with gateway.")}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class VerifyManualPaymentView(View):
    """
    Allows a user to manually verify a pending Squad transaction reference
    if they switched apps or refreshed their browser mid-payment.
    """
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Session expired. Please log in again to continue."}, status=401)

        action = request.POST.get("action", "").strip()
        if action == "dismiss":
            request.session.pop("pending_squad_ref", None)
            return JsonResponse({"success": True})

        reference = request.POST.get("reference", "").strip()
        if not reference:
            return JsonResponse({"error": "Transaction reference is required."}, status=400)

        if WalletTransaction.objects.filter(reference=reference, status=WalletTransaction.Status.SUCCESS).exists():
            request.session.pop("pending_squad_ref", None)
            return JsonResponse({
                "success": True,
                "already_credited": True,
                "message": "This transaction reference has already been verified and credited to your wallet balance."
            })

        from apps.payments.services import verify_transaction
        try:
            res = verify_transaction(reference)
            if res and res.get("status") == 200:
                data = res.get("data", {})
                status = data.get("transaction_status") or data.get("status", "")
                if str(status).lower() == "success":
                    amount_kobo = data.get("amount") or data.get("transaction_amount", 0)
                    amount_naira = Decimal(str(amount_kobo)) / Decimal("100.00")
                    metadata = data.get("metadata") or data.get("meta") or {}
                    user_id = metadata.get("user_id") or str(request.user.id)

                    credit_wallet(
                        transaction_ref=reference,
                        amount_naira=str(amount_naira),
                        user_id=user_id,
                        raw_payload=res
                    )
                    request.session.pop("pending_squad_ref", None)
                    return JsonResponse({
                        "success": True,
                        "message": f"Payment verified! Your wallet has been credited with ₦{amount_naira:,.2f}."
                    })
                else:
                    return JsonResponse({
                        "error": f"Transaction status: {str(status).upper() if status else 'PENDING'}. If you made the transfer, please wait 30 seconds and try verifying again."
                    }, status=400)
            else:
                return JsonResponse({"error": "Transaction reference not found on payment gateway."}, status=404)
        except Exception as e:
            logger.error("Manual payment verification error for ref=%s: %s", reference, str(e))
            return JsonResponse({"error": "Could not verify transaction at this time. Please try again."}, status=500)


def payment_callback(request):
    """
    Redirect endpoint from Squad after a card checkout attempt.
    Credits the wallet immediately and redirects the user to their Dashboard.
    """
    from django.contrib import messages
    from django.shortcuts import redirect

    reference = request.GET.get("transaction_ref", request.GET.get("reference", ""))
    
    # Attempt fallback verification directly from Squad API to credit user immediately
    if reference:
        from apps.payments.services import verify_transaction
        try:
            res = verify_transaction(reference)
            if res and res.get("status") == 200:
                data = res.get("data", {})
                status = data.get("transaction_status") or data.get("status", "")
                if str(status).lower() == "success":
                    amount_kobo = data.get("amount") or data.get("transaction_amount", 0)
                    amount_naira = Decimal(str(amount_kobo)) / Decimal("100.00")
                    metadata = data.get("metadata") or data.get("meta") or {}
                    user_id = metadata.get("user_id", "")
                    
                    if not user_id:
                        email = data.get("email") or data.get("customer_email", "")
                        if email:
                            try:
                                user = get_user_model().objects.get(email__iexact=email)
                                user_id = str(user.id)
                            except Exception as email_err:
                                logger.error("Email lookup failed on callback for email=%s: %s", email, str(email_err))
                    
                    # Restore session if dropped during payment redirect
                    if user_id and not request.user.is_authenticated:
                        try:
                            user_obj = get_user_model().objects.get(id=user_id)
                            from django.contrib.auth import login
                            login(request, user_obj, backend='django.contrib.auth.backends.ModelBackend')
                        except Exception as auth_err:
                            logger.error("Session restore failed on callback: %s", str(auth_err))

                    # Credit wallet immediately (task has internal db lock idempotency check)
                    credit_wallet(
                        transaction_ref=reference,
                        amount_naira=str(amount_naira),
                        user_id=user_id,
                        raw_payload=res
                    )
                    messages.success(request, f"Wallet successfully funded with ₦{amount_naira:,.2f}! ⚡")
                    return redirect("dashboard")
        except Exception as e:
            logger.error("Direct payment verification failed on callback for ref=%s: %s", reference, str(e))

    if request.user.is_authenticated:
        messages.info(request, "Payment completed! Your wallet balance has been updated.")
        return redirect("dashboard")
    return redirect("accounts:login")


@method_decorator(csrf_exempt, name="dispatch")
class SquadWebhookView(View):
    """
    Highly secure payment listener that processes real-time transaction notifications from Squad.
    Deduplicates requests, validates digital signatures, and fires async crediting workflows.
    """
    DUPLICATE_TTL = 48 * 60 * 60  # 48 Hours idempotency window

    # Squad sends these event types for successful payments
    HANDLED_EVENTS = [
        "charge_successful",     # Card / Bank Transfer / USSD checkout
        "charge_completed",      # Backward-compat alias (just in case)
        "virtual_account_payment",  # Direct bank transfer to virtual account
    ]

    def _log_webhook(self, reference, amount, sig_valid, status, error="", source_ip=None, payload_hash=""):
        """Create audit log entry for every incoming webhook."""
        try:
            WebhookLog.objects.create(
                provider="SQUAD",
                reference=reference or "UNKNOWN",
                amount=amount,
                signature_valid=sig_valid,
                status=status,
                error_message=error,
                source_ip=source_ip,
                payload_hash=payload_hash,
            )
        except Exception as log_err:
            logger.error("Failed to write WebhookLog: %s", str(log_err))

    def post(self, request, *args, **kwargs):
        source_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
        if source_ip and "," in source_ip:
            source_ip = source_ip.split(",")[0].strip()
        payload_hash = hashlib.sha256(request.body).hexdigest() if request.body else ""

        # 1. Signature retrieval & validation (handle both standard headers)
        sig = request.headers.get("x-squad-signature") or request.headers.get("x-squad-encrypted-body", "")
        if not sig:
            logger.error("Squad Webhook error: Missing digital signature header 'x-squad-encrypted-body'.")
            self._log_webhook("", None, False, WebhookLog.Status.REJECTED,
                              "Missing signature header", source_ip, payload_hash)
            return HttpResponse("Missing signature header", status=400)

        # 2. Digital HMAC payload signature check
        if not verify_webhook_signature(request.body, sig):
            logger.error("Squad Webhook error: Digital signature HMAC validation failed.")
            self._log_webhook("", None, False, WebhookLog.Status.REJECTED,
                              "HMAC signature mismatch", source_ip, payload_hash)
            return HttpResponse("Signature verification failed", status=400)

        # 3. Parse JSON Body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            logger.error("Squad Webhook error: Received invalid non-JSON body.")
            self._log_webhook("", None, True, WebhookLog.Status.FAILED,
                              "Invalid JSON body", source_ip, payload_hash)
            return HttpResponse("Invalid JSON", status=400)

        event = data.get("Event", "")
        body = data.get("Body", {})

        logger.info("Squad Webhook received event: '%s' | Full keys: %s", event, list(data.keys()))

        # 4. Handle only completed payment events
        if event not in self.HANDLED_EVENTS:
            logger.info("Squad Webhook: Ignoring unhandled event type: '%s'", event)
            self._log_webhook("", None, True, WebhookLog.Status.RECEIVED,
                              f"Unhandled event: {event}", source_ip, payload_hash)
            return HttpResponse("Event ignored", status=200)

        # 5. Extract payment variables
        transaction_ref = body.get("transaction_ref") or body.get("reference") or data.get("TransactionRef", "")
        if not transaction_ref:
            logger.error("Squad Webhook error: Webhook body is missing transaction reference.")
            self._log_webhook("", None, True, WebhookLog.Status.FAILED,
                              "Missing transaction reference", source_ip, payload_hash)
            return HttpResponse("Missing transaction reference", status=400)

        amount_kobo = body.get("amount", 0)
        try:
            amount_naira = Decimal(str(amount_kobo)) / Decimal("100.00")
        except (InvalidOperation, ValueError):
            logger.error("Squad Webhook error: Invalid amount format in body: %s", amount_kobo)
            self._log_webhook(transaction_ref, None, True, WebhookLog.Status.FAILED,
                              f"Invalid amount: {amount_kobo}", source_ip, payload_hash)
            return HttpResponse("Invalid amount", status=400)

        # BUG FIX: Squad returns metadata under "metadata" key, NOT "meta"
        metadata = body.get("metadata", {}) or body.get("meta", {}) or {}
        user_id = metadata.get("user_id", "")
        virtual_account_number = body.get("virtual_account_number", "")

        # Fallback: if no user_id from metadata, try to find user by email
        if not user_id:
            customer_email = body.get("email", "") or body.get("customer_email", "")
            if customer_email:
                User = get_user_model()
                try:
                    user = User.objects.get(email__iexact=customer_email)
                    user_id = str(user.id)
                    logger.info("Squad Webhook: Resolved user_id=%s from email=%s", user_id, customer_email)
                except User.DoesNotExist:
                    logger.warning("Squad Webhook: Could not find user by email=%s", customer_email)

        logger.info(
            "Squad Webhook processing: event=%s, ref=%s, amount=₦%s, user_id=%s, virtual_acct=%s",
            event, transaction_ref, amount_naira, user_id or "(none)", virtual_account_number or "(none)"
        )

        # 6. Idempotency Check via Redis cache
        redis_key = f"squad_webhook:{transaction_ref}"
        if cache.get(redis_key):
            logger.warning("Squad Webhook duplicate detected: ref=%s (request ignored)", transaction_ref)
            self._log_webhook(transaction_ref, amount_naira, True, WebhookLog.Status.DUPLICATE,
                              "", source_ip, payload_hash)
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

        # 8. Log successful webhook processing
        self._log_webhook(transaction_ref, amount_naira, True, WebhookLog.Status.PROCESSED,
                          "", source_ip, payload_hash)

        # 9. Return 200 OK fast to avoid transaction retries from Squad
        logger.info("Squad Webhook dispatched credit_wallet for ref=%s, amount=₦%s", transaction_ref, amount_naira)
        return HttpResponse("Accepted", status=200)
