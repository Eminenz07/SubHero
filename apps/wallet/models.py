"""
Wallet — Models
================
PRD Section 5.2 & 5.3: Wallet and Transaction Ledger.
Phase 1: Models defined, views in Phase 2.
"""

import uuid

from django.conf import settings
from django.db import models


class Wallet(models.Model):
    """
    PRD Section 5.2 (Table 8): User wallet.
    Each user has exactly one wallet.
    Balance stored as DecimalField — float is BANNED (PRD constraint).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Naira balance — NEVER float",
    )
    virtual_account_number = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Assigned by Providus/Bloc",
    )
    virtual_account_bank = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Bank name for display",
    )
    is_frozen = models.BooleanField(
        default=False,
        help_text="Admin can freeze for fraud review",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wallet_wallet"
        verbose_name = "Wallet"
        verbose_name_plural = "Wallets"
        # DB-level CHECK constraint: balance >= 0 (PRD Section 7)
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=0),
                name="wallet_balance_non_negative",
            ),
        ]

    def __str__(self):
        return f"Wallet({self.user.phone_number}: ₦{self.balance})"


class WalletTransaction(models.Model):
    """
    PRD Section 5.3 (Table 9): Transaction Ledger.
    Every debit/credit writes a row with balance_before + balance_after.
    """

    class TxnType(models.TextChoices):
        FUND = "FUND", "Wallet Funding"
        VTU = "VTU", "VTU Purchase"
        SMM = "SMM", "SMM Order"
        P2P_SEND = "P2P_SEND", "P2P Transfer (Sent)"
        P2P_RECEIVE = "P2P_RECEIVE", "P2P Transfer (Received)"
        REFUND = "REFUND", "Refund"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        REVERSED = "REVERSED", "Reversed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    txn_type = models.CharField(
        max_length=15,
        choices=TxnType.choices,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Always positive — direction via txn_type",
    )
    balance_before = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Snapshot before transaction",
    )
    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Snapshot after transaction",
    )
    reference = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique txn reference — idempotency key",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Human-readable description",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider response, order ID, etc.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Request IP — for fraud review",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Indexed — used in filtering",
    )

    class Meta:
        db_table = "wallet_transaction"
        verbose_name = "Wallet Transaction"
        verbose_name_plural = "Wallet Transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.txn_type} ₦{self.amount} ({self.status}) - {self.reference}"
