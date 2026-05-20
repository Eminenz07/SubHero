"""
Wallet — Service Layer
=======================
PRD Section 6.2: Atomic wallet operations.
Every credit/debit uses SELECT FOR UPDATE (PostgreSQL row-level locking).
Every operation writes a WalletTransaction row with balance_before + balance_after.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.utils import generate_reference
from .models import Wallet, WalletTransaction

logger = logging.getLogger(__name__)


# =============================================================
# Custom Exceptions
# =============================================================
class InsufficientBalanceError(Exception):
    """Raised when wallet balance is less than the requested debit amount."""
    pass


class WalletFrozenError(Exception):
    """Raised when the wallet is frozen by admin for fraud review."""
    pass


class DailyLimitExceededError(Exception):
    """Raised when a daily limit (funding or P2P) is exceeded."""
    pass


class RecipientNotFoundError(Exception):
    """Raised when P2P recipient phone number is not registered."""
    pass


class SelfTransferError(Exception):
    """Raised when user tries to transfer to themselves."""
    pass


# =============================================================
# Wallet Creation
# =============================================================
def create_wallet(user):
    """
    Create a wallet for a user and provision a virtual account.
    Called after OTP verification during registration.
    PRD Section 6.1.1: Wallet + virtual account auto-created on registration.
    """
    from apps.payments.services import get_providus_client

    # Idempotent: don't create if already exists
    wallet, created = Wallet.objects.get_or_create(user=user)
    if not created:
        logger.info("Wallet already exists for user=%s", user.id)
        return wallet

    # Provision virtual account
    try:
        client = get_providus_client()
        account_info = client.create_virtual_account(
            account_name=f"SUBHERO - {user.full_name}",
            user_reference=str(user.id),
        )
        wallet.virtual_account_number = account_info["account_number"]
        wallet.virtual_account_bank = account_info["bank_name"]
        wallet.save(update_fields=["virtual_account_number", "virtual_account_bank"])

        logger.info(
            "Wallet created: user=%s, account=%s",
            user.id,
            wallet.virtual_account_number,
        )
    except Exception as e:
        logger.error(
            "Virtual account provisioning failed: user=%s, error=%s",
            user.id,
            str(e),
        )
        # Wallet exists but without virtual account — can be retried later

    return wallet


# =============================================================
# Credit / Debit Operations
# =============================================================
@transaction.atomic
def credit_wallet(wallet_id, amount, txn_type, reference, description="",
                  metadata=None, ip_address=None):
    """
    Atomically credit a wallet.
    PRD Section 6.2.2: SELECT FOR UPDATE on wallet row.
    """
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("Credit amount must be positive")

    # Lock the wallet row
    wallet = Wallet.objects.select_for_update().get(id=wallet_id)

    if wallet.is_frozen:
        raise WalletFrozenError(f"Wallet {wallet_id} is frozen")

    balance_before = wallet.balance
    wallet.balance += amount
    wallet.save(update_fields=["balance"])

    txn = WalletTransaction.objects.create(
        wallet=wallet,
        txn_type=txn_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
        reference=reference,
        status=WalletTransaction.Status.SUCCESS,
        description=description,
        metadata=metadata or {},
        ip_address=ip_address,
    )

    logger.info(
        "Wallet credited: wallet=%s, amount=%s, type=%s, ref=%s, balance=%s",
        wallet_id, amount, txn_type, reference, wallet.balance,
    )

    return txn


@transaction.atomic
def debit_wallet(wallet_id, amount, txn_type, reference, description="",
                 metadata=None, ip_address=None):
    """
    Atomically debit a wallet.
    PRD Section 6.2.2: Negative balance is impossible — checks atomically.
    """
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("Debit amount must be positive")

    # Lock the wallet row
    wallet = Wallet.objects.select_for_update().get(id=wallet_id)

    if wallet.is_frozen:
        raise WalletFrozenError(f"Wallet {wallet_id} is frozen")

    if wallet.balance < amount:
        raise InsufficientBalanceError(
            f"Balance ₦{wallet.balance} insufficient for ₦{amount} debit"
        )

    balance_before = wallet.balance
    wallet.balance -= amount
    wallet.save(update_fields=["balance"])

    txn = WalletTransaction.objects.create(
        wallet=wallet,
        txn_type=txn_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
        reference=reference,
        status=WalletTransaction.Status.SUCCESS,
        description=description,
        metadata=metadata or {},
        ip_address=ip_address,
    )

    logger.info(
        "Wallet debited: wallet=%s, amount=%s, type=%s, ref=%s, balance=%s",
        wallet_id, amount, txn_type, reference, wallet.balance,
    )

    return txn


# =============================================================
# P2P Transfer
# =============================================================
def get_daily_p2p_total(wallet):
    """Sum today's successful P2P_SEND transactions for limit enforcement."""
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        WalletTransaction.objects.filter(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.P2P_SEND,
            status=WalletTransaction.Status.SUCCESS,
            created_at__gte=today_start,
        )
        .aggregate(total=Sum("amount"))
        .get("total")
    ) or Decimal("0")
    return total


def get_daily_funding_total(wallet):
    """Sum today's successful FUND transactions for limit enforcement."""
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        WalletTransaction.objects.filter(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.FUND,
            status=WalletTransaction.Status.SUCCESS,
            created_at__gte=today_start,
        )
        .aggregate(total=Sum("amount"))
        .get("total")
    ) or Decimal("0")
    return total


@transaction.atomic
def transfer_p2p(sender_user, recipient_phone, amount, ip_address=None):
    """
    P2P user-to-user transfer.
    PRD Section 6.2.3:
    - Fee-free (internal ledger movement)
    - Atomic: both debit and credit in single DB transaction or neither
    - Min ₦50, Max ₦100,000, Daily limit ₦200,000
    - Self-transfer blocked
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    amount = Decimal(str(amount))

    # Validate limits
    if amount < settings.P2P_MIN_AMOUNT:
        raise ValueError(f"Minimum transfer amount is ₦{settings.P2P_MIN_AMOUNT}")
    if amount > settings.P2P_MAX_AMOUNT:
        raise ValueError(f"Maximum transfer amount is ₦{settings.P2P_MAX_AMOUNT:,}")

    # Look up recipient
    try:
        recipient = User.objects.get(phone_number=recipient_phone, is_active=True)
    except User.DoesNotExist:
        raise RecipientNotFoundError("Recipient not found. Check the phone number.")

    # Self-transfer guard (PRD Section 7.2)
    if sender_user.id == recipient.id:
        raise SelfTransferError("You cannot transfer to yourself.")

    # Get sender wallet (locked)
    sender_wallet = Wallet.objects.select_for_update().get(user=sender_user)

    if sender_wallet.is_frozen:
        raise WalletFrozenError("Your wallet is currently frozen. Contact support.")

    # Daily limit check
    daily_total = get_daily_p2p_total(sender_wallet)
    if daily_total + amount > settings.P2P_DAILY_LIMIT:
        remaining = settings.P2P_DAILY_LIMIT - daily_total
        raise DailyLimitExceededError(
            f"Daily P2P limit exceeded. Remaining today: ₦{remaining:,.2f}"
        )

    # Balance check
    if sender_wallet.balance < amount:
        raise InsufficientBalanceError(
            f"Insufficient balance. You have ₦{sender_wallet.balance:,.2f}"
        )

    # Get recipient wallet (locked)
    recipient_wallet = Wallet.objects.select_for_update().get(user=recipient)

    if recipient_wallet.is_frozen:
        raise WalletFrozenError("Recipient wallet is frozen.")

    # Generate references
    send_ref = generate_reference("P2P")
    recv_ref = generate_reference("P2P")

    # Debit sender
    sender_balance_before = sender_wallet.balance
    sender_wallet.balance -= amount
    sender_wallet.save(update_fields=["balance"])

    send_txn = WalletTransaction.objects.create(
        wallet=sender_wallet,
        txn_type=WalletTransaction.TxnType.P2P_SEND,
        amount=amount,
        balance_before=sender_balance_before,
        balance_after=sender_wallet.balance,
        reference=send_ref,
        status=WalletTransaction.Status.SUCCESS,
        description=f"Transfer to {recipient.full_name} ({recipient.phone_number})",
        metadata={"recipient_id": str(recipient.id)},
        ip_address=ip_address,
    )

    # Credit recipient
    recipient_balance_before = recipient_wallet.balance
    recipient_wallet.balance += amount
    recipient_wallet.save(update_fields=["balance"])

    recv_txn = WalletTransaction.objects.create(
        wallet=recipient_wallet,
        txn_type=WalletTransaction.TxnType.P2P_RECEIVE,
        amount=amount,
        balance_before=recipient_balance_before,
        balance_after=recipient_wallet.balance,
        reference=recv_ref,
        status=WalletTransaction.Status.SUCCESS,
        description=f"Transfer from {sender_user.full_name} ({sender_user.phone_number})",
        metadata={"sender_id": str(sender_user.id)},
        ip_address=ip_address,
    )

    logger.info(
        "P2P transfer: sender=%s → recipient=%s, amount=%s, send_ref=%s",
        sender_user.id, recipient.id, amount, send_ref,
    )

    return send_txn, recv_txn
