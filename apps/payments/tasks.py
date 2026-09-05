"""
Payments — Background Tasks
===========================
Defines Celery background tasks for wallet crediting (idempotency-safe)
and virtual account generation retries.
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.contrib.auth import get_user_model
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from apps.wallet.models import Wallet, WalletTransaction
from apps.notifications.tasks import send_transaction_sms

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def credit_wallet(self, transaction_ref, amount_naira,
                  user_id="", virtual_account_number="",
                  raw_payload=None):
    """
    Credits user's wallet atomically with dual-layer idempotency guard.
    Dispatched by the secure webhook endpoint.
    """
    amount = Decimal(str(amount_naira))
    wallet = None

    # STEP 1 — Find wallet
    if user_id:
        try:
            wallet = Wallet.objects.get(user_id=user_id)
        except Wallet.DoesNotExist:
            logger.error("Wallet credit error: No wallet found for user_id=%s", user_id)
            
    if not wallet and virtual_account_number:
        try:
            wallet = Wallet.objects.get(virtual_account_number=virtual_account_number)
        except Wallet.DoesNotExist:
            logger.error("Wallet credit error: No wallet found for virtual_account_number=%s", virtual_account_number)

    if not wallet:
        logger.critical(
            "CRITICAL: Failed to credit wallet. Wallet not found for ref=%s (user_id=%s, acct=%s)",
            transaction_ref, user_id, virtual_account_number
        )
        return

    # STEP 2 — Atomic transaction block
    try:
        with transaction.atomic():
            # Lock the wallet record
            wallet = Wallet.objects.select_for_update().get(id=wallet.id)

            # DB-level idempotency check (safety net if Redis fails)
            if WalletTransaction.objects.filter(reference=transaction_ref).exists():
                logger.warning("Duplicate transaction detected in DB: ref=%s (ignored)", transaction_ref)
                return

            # Calculate deposit fee
            deposit_fee = Decimal('20.00') if amount < Decimal('1000.00') else Decimal('50.00')
            net_amount = amount - deposit_fee

            balance_before = wallet.balance
            wallet.balance += net_amount
            wallet.save(update_fields=["balance"])

            # Create ledger entry
            WalletTransaction.objects.create(
                wallet=wallet,
                txn_type=WalletTransaction.TxnType.FUND,
                amount=net_amount,
                deposit_fee=deposit_fee,
                balance_before=balance_before,
                balance_after=wallet.balance,
                reference=transaction_ref,
                status=WalletTransaction.Status.SUCCESS,
                description="Wallet funded via Squad",
                metadata=raw_payload or {},
                ip_address=None  # Webhooks do not convey user client IP
            )

        # STEP 3 — Outside atomic block (Push, SMS & Logging)
        logger.info(
            "SUCCESS: Funded User %s with ₦%s (Fee: ₦%s). Ref=%s",
            wallet.user.phone_number, net_amount, deposit_fee, transaction_ref
        )

        try:
            from apps.notifications.services import send_push_notification
            send_push_notification(
                user=wallet.user,
                title=f"💰 Wallet Credited: ₦{net_amount:,.2f}",
                body=f"Received via Bank Transfer. New Balance: ₦{wallet.balance:,.2f}. Tap to view receipt.",
                action_url="/vtu/",
                level="financial"
            )
        except Exception as push_err:
            logger.error("Error sending push notification on wallet credit: %s", str(push_err))

        try:
            send_transaction_sms.delay(
                wallet.user.phone_number,
                f"SubHero: ₦{net_amount:,.2f} added to your wallet. "
                f"Balance: ₦{wallet.balance:,.2f}. "
                f"Ref: {transaction_ref[:12]}"
            )
            if wallet.user.email:
                from django.core.mail import send_mail
                from django.conf import settings
                subject = "Wallet Funding Successful 💰"
                email_message = (
                    f"Hello {wallet.user.full_name or 'SubHero User'},\n\n"
                    f"Your SubHero wallet has been credited successfully.\n\n"
                    f"Details:\n"
                    f"- Amount Credited: ₦{net_amount:,.2f}\n"
                    f"- Processing Fee: ₦{deposit_fee:,.2f}\n"
                    f"- New Wallet Balance: ₦{wallet.balance:,.2f}\n"
                    f"- Reference: {transaction_ref}\n\n"
                    f"Thank you for using SubHero!\n\n"
                    f"Best regards,\n"
                    f"The SubHero Team"
                )
                send_mail(
                    subject=subject,
                    message=email_message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@subhero.com.ng"),
                    recipient_list=[wallet.user.email],
                    fail_silently=True
                )
        except Exception as notify_err:
            logger.error("SMS/Email notification dispatch failed for credit ref=%s: %s", transaction_ref, str(notify_err))

    except Exception as exc:
        logger.error("Exception during atomic wallet credit for ref=%s: %s", transaction_ref, str(exc))
        try:
            self.retry(exc=exc, countdown=15)
        except MaxRetriesExceededError:
            logger.critical("CRITICAL: Max retries exceeded attempting to credit wallet for ref=%s", transaction_ref)


@shared_task(bind=True, max_retries=5)
def create_virtual_account_async(self, user_id):
    """
    Retries Squad virtual account provisioning asynchronously with exponential backoff.
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        wallet = Wallet.objects.get(user=user)
    except Exception as err:
        logger.error("create_virtual_account_async: User or Wallet does not exist: %s", str(err))
        return

    from apps.payments.services import create_virtual_account
    
    logger.info("Retrying virtual account generation for user=%s (attempt %s/5)", user_id, self.request.retries + 1)
    result = create_virtual_account(user)
    
    if result.get("success"):
        wallet.virtual_account_number = result["virtual_account_number"]
        wallet.virtual_account_bank = result["bank_name"]
        wallet.save(update_fields=["virtual_account_number", "virtual_account_bank"])
        logger.info("Successfully generated virtual account for user=%s on retry: %s", user_id, wallet.virtual_account_number)
    else:
        attempt = self.request.retries
        countdown = 60 * (2 ** attempt)
        logger.warning(
            "Squad virtual account creation failed for user=%s: %s. Retrying in %ss...",
            user_id, result.get("message"), countdown
        )
        try:
            self.retry(countdown=countdown)
        except MaxRetriesExceededError:
            logger.critical("CRITICAL: Failed to create virtual account for User=%s after 5 attempts.", user_id)
            # Log admin error / send email here if applicable
