import logging
from decimal import Decimal
from uuid import UUID
from django.db import transaction
from django.contrib.auth import get_user_model
from celery import shared_task

from apps.wallet.models import Wallet, WalletTransaction
from apps.notifications.tasks import send_transaction_sms

logger = logging.getLogger(__name__)

@shared_task
def execute_p2p_transfer(sender_id, recipient_id, amount_str, note=""):
    """
    Background Celery task to execute P2P transfers atomically.
    PRD Section 6.2.3: Atomic internal ledger transfer with safety locks.
    """
    User = get_user_model()
    amount = Decimal(str(amount_str))

    try:
        with transaction.atomic():
            # Row lock sender wallet
            sender_wallet = Wallet.objects.select_for_update().get(user_id=sender_id)
            # Row lock recipient wallet
            recipient_wallet = Wallet.objects.select_for_update().get(user_id=recipient_id)

            if sender_wallet.balance < amount:
                logger.warning(
                    "P2P Async Fail: Sender %s has insufficient balance (₦%s) for ₦%s",
                    sender_id, sender_wallet.balance, amount
                )
                return False

            balance_before_sender = sender_wallet.balance
            balance_before_recv = recipient_wallet.balance

            # Execute balances move
            sender_wallet.balance -= amount
            recipient_wallet.balance += amount

            sender_wallet.save(update_fields=["balance"])
            recipient_wallet.save(update_fields=["balance"])

            # Generate reference
            import uuid
            ref = f"P2P-{uuid.uuid4().hex[:12].upper()}"

            note_clean = (note or "").strip()
            note_suffix = f" - {note_clean}" if note_clean else ""

            # Create Sender Transaction record
            WalletTransaction.objects.create(
                wallet=sender_wallet,
                txn_type=WalletTransaction.TxnType.P2P_SEND,
                amount=amount,
                balance_before=balance_before_sender,
                balance_after=sender_wallet.balance,
                reference=ref,
                status=WalletTransaction.Status.SUCCESS,
                description=f"Transfer to {recipient_wallet.user.full_name} ({recipient_wallet.user.phone_number}){note_suffix}",
                metadata={"recipient_id": str(recipient_id), "note": note_clean}
            )

            # Create Recipient Transaction record
            WalletTransaction.objects.create(
                wallet=recipient_wallet,
                txn_type=WalletTransaction.TxnType.P2P_RECEIVE,
                amount=amount,
                balance_before=balance_before_recv,
                balance_after=recipient_wallet.balance,
                reference=f"RECV-{ref}",
                status=WalletTransaction.Status.SUCCESS,
                description=f"Transfer from {sender_wallet.user.full_name} ({sender_wallet.user.phone_number}){note_suffix}",
                metadata={"sender_id": str(sender_id), "note": note_clean}
            )

            # Add in-app Notifications inside transaction
            try:
                from apps.notifications.models import Notification
                note_str = f" Note: {note_clean}." if note_clean else ""
                Notification.add(
                    user=sender_wallet.user,
                    title="Transfer Sent",
                    description=f"You successfully sent ₦{amount:,.2f} to {recipient_wallet.user.full_name}.{note_str}",
                    level="financial"
                )
                Notification.add(
                    user=recipient_wallet.user,
                    title="Transfer Received",
                    description=f"You received ₦{amount:,.2f} from {sender_wallet.user.full_name}.{note_str}",
                    level="financial"
                )
            except Exception as e:
                logger.error("P2P Notifications creation failed: %s", str(e))

            logger.info("P2P Async Transfer Success: %s sent ₦%s to %s", sender_id, amount, recipient_id)

    except Exception as err:
        logger.exception("P2P Async Transfer Execution Exception: %s", str(err))
        return False

    # Dispatch SMS outside the atomic block to avoid rollback on carrier failure
    try:
        send_transaction_sms.delay(
            sender_wallet.user.phone_number,
            f"SubHero: You sent ₦{amount:,.0f} to {recipient_wallet.user.full_name}. Balance: ₦{sender_wallet.balance:,.2f}"
        )
        send_transaction_sms.delay(
            recipient_wallet.user.phone_number,
            f"SubHero: ₦{amount:,.0f} received from {sender_wallet.user.full_name}."
        )
    except Exception as sms_err:
        logger.error("SMS notification dispatch failed: %s", str(sms_err))

    return True
