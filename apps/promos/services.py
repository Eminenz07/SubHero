"""
Promo Campaigns — Services
==========================
Core grant/claim logic for signup bonuses. Everything here is atomic
and row-locked so a promo failure can never break registration.
"""

import logging

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum, F
from django.utils import timezone

from apps.wallet.models import WalletTransaction

from .models import PromoCampaign, PromoClaim, PromoAuditLog

logger = logging.getLogger(__name__)

PROMO_REF_PREFIX = "PROMO"


def promo_enabled():
    return bool(getattr(settings, "PROMOS_ENABLED", False))


def block_p2p_until_deposit():
    return bool(getattr(settings, "PROMO_BLOCK_P2P_UNTIL_DEPOSIT", False))


def _audit_log(actor, campaign, action, before=None, after=None):
    try:
        PromoAuditLog.objects.create(
            actor=actor,
            campaign=campaign,
            action=action,
            before=before or {},
            after=after or {},
        )
    except Exception as ex:
        logger.error("Promo audit log failed: %s", str(ex))


def try_grant(user, ip=None, source=None):
    """
    Grant a signup bonus to a newly-verified user.

    Called from VerifyOTPView inside try/except so a promo failure can
    NEVER break registration. Returns (granted: bool, claim: PromoClaim|None).

    Flow (step 4):
      - SELECT ... FOR UPDATE the campaign row
      - check effective status, dates, claimed_count < max_claims, IP limit,
        and no existing claim for this user
      - credit the wallet with F() expressions
      - create a WalletTransaction (type PROMO_BONUS, reference PROMO-<id>-<id>,
        idempotent)
      - mark the claim GRANTED with the amount snapshot
      - increment claimed_count; if claimed_count == max_claims set status FULL
      - everything rolls back on failure; no slot is used
    """
    if not promo_enabled():
        return False, None

    try:
        claim = (
            PromoClaim.objects.select_related("campaign")
            .filter(user=user, status=PromoClaim.Status.PENDING)
            .first()
        )
    except PromoClaim.DoesNotExist:
        claim = None

    if not claim:
        return False, None

    campaign = claim.campaign

    if not promo_enabled():
        _reject(claim, "promos_disabled", actor=None)
        return False, claim

    now = timezone.now()
    effective = campaign.effective_status

    if effective not in (PromoCampaign.Status.ACTIVE,):
        _reject(claim, f"campaign_{effective.lower()}", actor=None)
        return False, claim

    if campaign.starts_at and campaign.starts_at > now:
        _reject(claim, "campaign_not_started", actor=None)
        return False, claim

    if campaign.claimed_count >= campaign.max_claims:
        _reject(claim, "campaign_full", actor=None)
        return False, claim

    # IP limit (0 = unlimited)
    if campaign.max_claims_per_ip and campaign.max_claims_per_ip > 0:
        ip_claims = PromoClaim.objects.filter(
            campaign=campaign,
            status=PromoClaim.Status.GRANTED,
            ip=ip,
        ).count() if ip else 0
        if ip_claims >= campaign.max_claims_per_ip:
            _reject(claim, "ip_limit_reached", actor=None)
            return False, claim

    # Idempotency: reference ties campaign+user together
    reference = f"{PROMO_REF_PREFIX}-{campaign.id}-{user.id}"
    try:
        existing_txn = WalletTransaction.objects.filter(reference=reference).first()
    except Exception:
        existing_txn = None

    bonus = campaign.bonus_amount
    try:
        bonus = Decimal(str(bonus))
    except (InvalidOperation, TypeError, ValueError):
        bonus = Decimal("0.00")

    with transaction.atomic():
        # Re-lock campaign inside the transaction
        campaign = (
            PromoCampaign.objects.select_for_update()
            .filter(id=campaign.id)
            .first()
        )
        if not campaign:
            _reject(claim, "campaign_missing", actor=None)
            return False, claim

        effective = campaign.effective_status
        if effective not in (PromoCampaign.Status.ACTIVE,):
            _reject(claim, f"campaign_{effective.lower()}", actor=None)
            return False, claim

        if campaign.claimed_count >= campaign.max_claims:
            _reject(claim, "campaign_full", actor=None)
            return False, claim

        if campaign.starts_at and campaign.starts_at > now:
            _reject(claim, "campaign_not_started", actor=None)
            return False, claim

        if campaign.ends_at and campaign.ends_at <= now:
            _reject(claim, "campaign_expired", actor=None)
            return False, claim

        if campaign.max_claims_per_ip and campaign.max_claims_per_ip > 0:
            ip_claims = PromoClaim.objects.filter(
                campaign=campaign,
                status=PromoClaim.Status.GRANTED,
                ip=ip,
            ).count() if ip else 0
            if ip_claims >= campaign.max_claims_per_ip:
                _reject(claim, "ip_limit_reached", actor=None)
                return False, claim

        # Idempotent wallet credit — same reference never duplicates
        if existing_txn:
            claim.amount = bonus
            claim.status = PromoClaim.Status.GRANTED
            claim.granted_at = now
            claim.wallet_transaction = existing_txn
            claim.save(update_fields=["amount", "status", "granted_at", "wallet_transaction"])
            return True, claim

        from apps.wallet.models import Wallet
        wallet = Wallet.objects.select_for_update().get(user=user)

        balance_before = wallet.balance
        wallet.balance = F("balance") + bonus
        wallet.save(update_fields=["balance"])

        wallet.refresh_from_db(fields=["balance"])

        txn = WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.PROMO_BONUS,
            amount=bonus,
            balance_before=balance_before,
            balance_after=wallet.balance,
            reference=reference,
            status=WalletTransaction.Status.SUCCESS,
            description=f"Welcome bonus from promo {campaign.code}",
            metadata={"campaign_id": str(campaign.id), "promo_code": campaign.code},
            ip_address=ip,
        )

        claim.amount = bonus
        claim.status = PromoClaim.Status.GRANTED
        claim.granted_at = now
        claim.wallet_transaction = txn
        if ip:
            claim.ip = ip
        if source:
            claim.source = source
        claim.save(update_fields=[
            "amount", "status", "granted_at", "wallet_transaction", "ip", "source",
        ])

        campaign.claimed_count = F("claimed_count") + 1
        campaign.save(update_fields=["claimed_count"])
        campaign.refresh_from_db(fields=["claimed_count"])

        if campaign.claimed_count >= campaign.max_claims:
            campaign.status = PromoCampaign.Status.FULL
            campaign.save(update_fields=["status"])
            _audit_log(None, campaign, "auto_close_full", after={
                "claimed_count": campaign.claimed_count,
                "max_claims": campaign.max_claims,
                "status": campaign.status,
            })

        return True, claim


def _reject(claim, reason, actor=None):
    """Mark a claim rejected without touching the wallet or campaign counters."""
    claim.status = PromoClaim.Status.REJECTED
    claim.reject_reason = reason
    claim.save(update_fields=["status", "reject_reason"])
    try:
        _audit_log(actor, claim.campaign, "claim_rejected", after={
            "claim_id": str(claim.id),
            "reason": reason,
        })
    except Exception:
        pass


def grant_pending_claims_for_user(user, ip=None, source=None):
    """
    Idempotent wrapper used at registration / OTP grant time.
    Safe to call multiple times.
    """
    try:
        return try_grant(user, ip=ip, source=source)
    except Exception as ex:
        logger.error(
            "Promo grant failed for user=%s: %s",
            getattr(user, "id", None), str(ex),
        )
        # Mark claim for admin retry if it exists
        try:
            claim = PromoClaim.objects.filter(user=user, status=PromoClaim.Status.PENDING).first()
            if claim:
                _reject(claim, f"grant_error:{str(ex)[:120]}", actor=None)
        except Exception:
            pass
        return False, None
