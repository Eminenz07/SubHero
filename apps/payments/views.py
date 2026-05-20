"""
Payments — Webhook Views
==========================
PRD Section 8.2: Providus Bank funding webhook.
- Verifies HMAC-SHA256 signature
- Deduplicates via Redis (48hr TTL)
- Credits wallet atomically
- Always returns 200 OK (even for duplicates — PRD requirement)
"""

import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.core.utils import get_client_ip
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import credit_wallet
from .models import WebhookLog
from .services import verify_webhook_signature

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class ProvidusWebhookView(View):
    """
    PRD Section 8.2: Receives POST from Providus on every inbound transfer.
    Flow:
    1. Log the webhook
    2. Verify HMAC signature
    3. Check for duplicate reference in Redis (48hr TTL)
    4. Look up wallet by virtual account number
    5. Credit wallet atomically
    6. Return 200 OK always
    """

    DUPLICATE_TTL = 48 * 60 * 60  # 48 hours (PRD)

    def post(self, request):
        source_ip = get_client_ip(request)
        raw_body = request.body

        # Hash the raw payload for audit
        payload_hash = hashlib.sha256(raw_body).hexdigest()

        # Parse JSON payload
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.warning("Webhook: invalid JSON from ip=%s", source_ip)
            return JsonResponse({"requestSuccessful": True, "responseMessage": "accepted"})

        reference = payload.get("settlementId", payload.get("sessionId", ""))
        amount_str = payload.get("transactionAmount", payload.get("settledAmount", "0"))
        account_number = payload.get("accountNumber", "")

        # Create webhook log entry
        webhook_log = WebhookLog.objects.create(
            provider=WebhookLog.Provider.PROVIDUS,
            reference=reference or "unknown",
            amount=Decimal(str(amount_str)) if amount_str else None,
            account_number=account_number,
            payload_hash=payload_hash,
            source_ip=source_ip,
            status=WebhookLog.Status.RECEIVED,
        )

        # Step 1: Verify HMAC signature (PRD Section 8.2)
        received_signature = request.headers.get("X-Auth-Signature", "")
        if not verify_webhook_signature(raw_body, received_signature):
            webhook_log.signature_valid = False
            webhook_log.status = WebhookLog.Status.REJECTED
            webhook_log.error_message = "Invalid HMAC signature"
            webhook_log.save(update_fields=["signature_valid", "status", "error_message"])

            logger.warning(
                "Webhook signature invalid: ref=%s, ip=%s",
                reference, source_ip,
            )
            # Still return 200 to avoid retry storms
            return JsonResponse({"requestSuccessful": True, "responseMessage": "accepted"})

        webhook_log.signature_valid = True
        webhook_log.save(update_fields=["signature_valid"])

        # Step 2: Duplicate detection via Redis (PRD: 48hr TTL)
        dedup_key = f"webhook_ref:{reference}"
        if cache.get(dedup_key):
            webhook_log.status = WebhookLog.Status.DUPLICATE
            webhook_log.save(update_fields=["status"])

            logger.info("Webhook duplicate: ref=%s, ip=%s", reference, source_ip)
            return JsonResponse({"requestSuccessful": True, "responseMessage": "accepted"})

        # Step 3: Look up wallet by virtual account number
        try:
            wallet = Wallet.objects.get(virtual_account_number=account_number)
        except Wallet.DoesNotExist:
            webhook_log.status = WebhookLog.Status.FAILED
            webhook_log.error_message = f"No wallet for account {account_number}"
            webhook_log.save(update_fields=["status", "error_message"])

            logger.error(
                "Webhook: wallet not found for account=%s, ref=%s",
                account_number, reference,
            )
            return JsonResponse({"requestSuccessful": True, "responseMessage": "accepted"})

        # Step 4: Parse and validate amount
        try:
            amount = Decimal(str(amount_str))
            if amount <= 0:
                raise InvalidOperation("Amount must be positive")
        except (InvalidOperation, ValueError) as e:
            webhook_log.status = WebhookLog.Status.FAILED
            webhook_log.error_message = f"Invalid amount: {amount_str}"
            webhook_log.save(update_fields=["status", "error_message"])

            logger.error("Webhook: invalid amount=%s, ref=%s", amount_str, reference)
            return JsonResponse({"requestSuccessful": True, "responseMessage": "accepted"})

        # Step 5: Credit wallet atomically
        try:
            txn = credit_wallet(
                wallet_id=wallet.id,
                amount=amount,
                txn_type=WalletTransaction.TxnType.FUND,
                reference=reference,
                description=f"Bank transfer via Providus - {reference}",
                metadata={
                    "provider": "providus",
                    "raw_reference": reference,
                    "account_number": account_number,
                    "source_ip": source_ip,
                },
                ip_address=source_ip,
            )

            # Mark reference as processed in Redis (48hr dedup window)
            cache.set(dedup_key, True, self.DUPLICATE_TTL)

            webhook_log.status = WebhookLog.Status.PROCESSED
            webhook_log.save(update_fields=["status"])

            logger.info(
                "Webhook processed: ref=%s, wallet=%s, amount=%s, balance=%s",
                reference, wallet.id, amount, wallet.balance,
            )

        except Exception as e:
            webhook_log.status = WebhookLog.Status.FAILED
            webhook_log.error_message = str(e)
            webhook_log.save(update_fields=["status", "error_message"])

            logger.error(
                "Webhook processing error: ref=%s, error=%s",
                reference, str(e),
            )

        return JsonResponse({"requestSuccessful": True, "responseMessage": "accepted"})
