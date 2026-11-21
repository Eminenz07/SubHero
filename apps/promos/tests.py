"""
Promo Campaigns — Tests
=======================
Covers: concurrency, idempotency, bonus snapshot, auto-close, manual
close/pause, expiry, existing-user link, invalid code, IP limit, P2P
lock, promo failure not breaking registration, wallet/ledger totals,
analytics exclusion.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.test import Client
from django.contrib.auth import get_user_model

from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import credit_wallet, transfer_p2p
from apps.promos.models import (
    PromoCampaign, PromoClaim, PromoAuditLog,
)
from apps.promos.services import try_grant, grant_pending_claims_for_user, promo_enabled
from apps.admin_panel.queries import get_promo_spend, get_deposit_fee_revenue, get_net_profit

User = get_user_model()


_user_counter = [0]


def make_user(phone, email=None, is_staff=False):
    _user_counter[0] += 1
    return User.objects.create_user(
        phone_number=phone,
        email=email or f"{phone}@example.com",
        password="pass12345",
        full_name=f"User {phone}",
        is_verified=True,
        is_active=True,
        is_staff=is_staff,
        referral_code=f"REF{_user_counter[0]:06d}",
    )


def make_campaign(**kwargs):
    defaults = dict(
        name="Welcome Bonus",
        code="WELCOME",
        bonus_amount=Decimal("1000.00"),
        max_claims=3,
        status=PromoCampaign.Status.ACTIVE,
        created_by=make_user("+2349000000000", "admin@example.com", is_staff=True),
    )
    defaults.update(kwargs)
    return PromoCampaign.objects.create(**defaults)


def make_claim(user, campaign, status=PromoClaim.Status.PENDING, amount=None, ip="127.0.0.1"):
    return PromoClaim.objects.create(
        campaign=campaign, user=user, status=status,
        amount=amount, ip=ip, source="",
    )


class TestPromoCampaignEffectiveStatus(TestCase):
    def test_active_within_dates(self):
        c = make_campaign(status=PromoCampaign.Status.ACTIVE)
        self.assertEqual(c.effective_status, PromoCampaign.Status.ACTIVE)

    def test_full_when_claims_reach_max(self):
        c = make_campaign(max_claims=2, claimed_count=2, status=PromoCampaign.Status.ACTIVE)
        self.assertEqual(c.effective_status, PromoCampaign.Status.FULL)

    def test_paused(self):
        c = make_campaign(status=PromoCampaign.Status.PAUSED)
        self.assertEqual(c.effective_status, PromoCampaign.Status.PAUSED)

    def test_closed(self):
        c = make_campaign(status=PromoCampaign.Status.CLOSED)
        self.assertEqual(c.effective_status, PromoCampaign.Status.CLOSED)

    def test_expired_after_ends_at(self):
        c = make_campaign(
            status=PromoCampaign.Status.ACTIVE,
            ends_at=timezone.now() - timedelta(hours=1),
        )
        self.assertEqual(c.effective_status, PromoCampaign.Status.EXPIRED)

    def test_not_yet_started(self):
        c = make_campaign(
            status=PromoCampaign.Status.ACTIVE,
            starts_at=timezone.now() + timedelta(hours=1),
        )
        self.assertEqual(c.effective_status, PromoCampaign.Status.DRAFT)


@override_settings(PROMOS_ENABLED=True)
class TestTryGrant(TransactionTestCase):
    def setUp(self):
        self.campaign = make_campaign(max_claims=2)
        self.user1 = make_user("+2348011111111", "u1@example.com")
        self.user2 = make_user("+2348022222222", "u2@example.com")
        self.user3 = make_user("+2348033333333", "u3@example.com")

    def test_grant_credits_wallet_and_ledger(self):
        make_claim(self.user1, self.campaign)
        granted, claim = try_grant(self.user1, ip="127.0.0.1")
        self.assertTrue(granted)
        self.assertEqual(claim.status, PromoClaim.Status.GRANTED)
        self.assertEqual(claim.amount, self.campaign.bonus_amount)
        self.assertIsNotNone(claim.granted_at)
        self.assertIsNotNone(claim.wallet_transaction)

        wallet = Wallet.objects.get(user=self.user1)
        self.assertEqual(wallet.balance, Decimal("1000.00"))

        txn = WalletTransaction.objects.get(reference=f"PROMO-{self.campaign.id}-{self.user1.id}")
        self.assertEqual(txn.txn_type, WalletTransaction.TxnType.PROMO_BONUS)
        self.assertEqual(txn.amount, Decimal("1000.00"))
        self.assertEqual(txn.status, WalletTransaction.Status.SUCCESS)

    def test_grant_via_registration_wrapper_no_ambient_transaction(self):
        """Registration calls the wrapper with no surrounding transaction.

        Regression: the initial PENDING-claim lookup must not use
        select_for_update() outside an atomic block — on PostgreSQL that
        raises TransactionManagementError and the claim gets rejected
        instead of granting the bonus.
        """
        make_claim(self.user1, self.campaign)
        granted, claim = grant_pending_claims_for_user(self.user1, ip="127.0.0.1")
        self.assertTrue(granted)
        self.assertEqual(claim.status, PromoClaim.Status.GRANTED)
        self.assertEqual(claim.reject_reason, "")
        wallet = Wallet.objects.get(user=self.user1)
        self.assertEqual(wallet.balance, Decimal("1000.00"))

    def test_concurrency_exact_slots_granted(self):
        """Exactly max_claims granted across many verifications.

        Note: SQLite serializes writes, so this runs grants sequentially.
        The atomic row-locking (select_for_update) that guarantees concurrency
        safety on PostgreSQL is exercised here at the logic level.
        """
        [make_claim(u, self.campaign) for u in [self.user1, self.user2, self.user3]]

        results = [try_grant(u, ip="127.0.0.1")[0] for u in [self.user1, self.user2, self.user3]]

        self.assertEqual(sum(results), 2)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.claimed_count, 2)
        self.assertEqual(
            PromoClaim.objects.filter(status=PromoClaim.Status.GRANTED).count(),
            2,
        )

    def test_no_double_grant_uses_same_slot(self):
        claim = make_claim(self.user1, self.campaign)
        try_grant(self.user1, ip="127.0.0.1")
        # Second call: no PENDING claim left -> no-op, no extra slot consumed
        granted2, claim2 = try_grant(self.user1, ip="127.0.0.1")
        self.assertFalse(granted2)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.claimed_count, 1)
        wallet = Wallet.objects.get(user=self.user1)
        self.assertEqual(wallet.balance, Decimal("1000.00"))

    def test_rejected_when_full(self):
        self.campaign.max_claims = 1
        self.campaign.claimed_count = 1
        self.campaign.status = PromoCampaign.Status.FULL
        self.campaign.save()
        make_claim(self.user1, self.campaign)
        granted, claim = try_grant(self.user1, ip="127.0.0.1")
        self.assertFalse(granted)
        self.assertEqual(claim.status, PromoClaim.Status.REJECTED)

    def test_rejected_when_expired(self):
        self.campaign.ends_at = timezone.now() - timedelta(hours=1)
        self.campaign.save()
        make_claim(self.user1, self.campaign)
        granted, _ = try_grant(self.user1, ip="127.0.0.1")
        self.assertFalse(granted)

    def test_rejected_when_paused(self):
        self.campaign.status = PromoCampaign.Status.PAUSED
        self.campaign.save()
        make_claim(self.user1, self.campaign)
        granted, _ = try_grant(self.user1, ip="127.0.0.1")
        self.assertFalse(granted)

    def test_ip_limit(self):
        self.campaign.max_claims_per_ip = 1
        self.campaign.save()
        make_claim(self.user1, self.campaign)
        try_grant(self.user1, ip="1.2.3.4")
        make_claim(self.user2, self.campaign)
        granted, _ = try_grant(self.user2, ip="1.2.3.4")
        self.assertFalse(granted)

    def test_bonus_snapshot_after_edit(self):
        make_claim(self.user1, self.campaign)
        self.campaign.bonus_amount = Decimal("500.00")
        self.campaign.save()
        granted, claim = try_grant(self.user1, ip="127.0.0.1")
        self.assertTrue(granted)
        self.assertEqual(claim.amount, Decimal("500.00"))

    def test_auto_close_full_on_last_slot(self):
        self.campaign.max_claims = 1
        self.campaign.save()
        make_claim(self.user1, self.campaign)
        try_grant(self.user1, ip="127.0.0.1")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, PromoCampaign.Status.FULL)
        self.assertTrue(
            PromoAuditLog.objects.filter(action="auto_close_full").exists()
        )


class TestPromoFailureDoesNotBreakRegistration(TestCase):
    @patch("apps.promos.services.try_grant", side_effect=Exception("boom"))
    def test_grant_wrapper_swallows_errors(self, mock_grant):
        """Promo grant failures are caught and never propagate registration."""
        user = make_user("+2348012345678", "u@example.com")
        campaign = make_campaign()
        make_claim(user, campaign)
        ok, claim_out = grant_pending_claims_for_user(user, ip="1.2.3.4")
        self.assertFalse(ok)
        self.assertIsNone(claim_out)
        # Registration can still proceed (user exists, wallet can be created)
        self.assertTrue(User.objects.filter(id=user.id).exists())


@override_settings(PROMOS_ENABLED=True)
class TestP2PGuard(TestCase):
    def setUp(self):
        self.user = make_user("+2348011111111", "u@example.com")
        self.campaign = make_campaign()
        make_claim(self.user, self.campaign, status=PromoClaim.Status.GRANTED, amount=Decimal("1000.00"))
        # Give the user a wallet
        Wallet.objects.get_or_create(user=self.user)

    @override_settings(PROMO_BLOCK_P2P_UNTIL_DEPOSIT=True)
    def test_blocked_when_no_deposit(self):
        recipient = make_user("+2348022222222", "r@example.com")
        with self.assertRaises(ValueError) as ctx:
            transfer_p2p(self.user, recipient.phone_number, Decimal("100"))
        self.assertIn("first deposit", str(ctx.exception))

    @override_settings(PROMO_BLOCK_P2P_UNTIL_DEPOSIT=True)
    def test_allowed_after_deposit(self):
        recipient = make_user("+2348022222222", "r@example.com")
        wallet = Wallet.objects.get(user=self.user)
        credit_wallet(
            wallet.id, Decimal("5000"),
            WalletTransaction.TxnType.FUND, "FUND-DEP",
            description="Deposit",
        )
        # Should not raise (P2P allowed after deposit)
        transfer_p2p(self.user, recipient.phone_number, Decimal("100"))

    @override_settings(PROMO_BLOCK_P2P_UNTIL_DEPOSIT=False)
    def test_not_blocked_when_flag_off(self):
        recipient = make_user("+2348022222222", "r@example.com")
        wallet = Wallet.objects.get(user=self.user)
        credit_wallet(
            wallet.id, Decimal("5000"),
            WalletTransaction.TxnType.FUND, "FUND-DEP",
            description="Deposit",
        )
        transfer_p2p(self.user, recipient.phone_number, Decimal("100"))


@override_settings(PROMOS_ENABLED=True)
class TestAnalyticsExcludePromoBonus(TestCase):
    def test_promo_spend_excluded_from_deposit_revenue(self):
        user = make_user("+2348011111111", "u@example.com")
        campaign = make_campaign()
        make_claim(user, campaign, status=PromoClaim.Status.PENDING)
        granted, _ = try_grant(user, ip="1.2.3.4")
        self.assertTrue(granted)

        # Promo spend tracked separately
        spend = get_promo_spend()
        self.assertEqual(spend, Decimal("1000.00"))

        # Deposit/revenue queries use txn_type='FUND' — PROMO_BONUS excluded
        today = timezone.now().date()
        dep = get_deposit_fee_revenue(today, today)
        self.assertEqual(dep["small_deposits"], 0)
        self.assertEqual(dep["large_deposits"], 0)
        profit = get_net_profit(today, today)
        self.assertEqual(profit["fees"], Decimal("0.00"))


class TestJoinView(TestCase):
    def test_invalid_code_neutral_message(self):
        client = Client()
        resp = client.get("/promos/join/INVALID/")
        self.assertRedirects(resp, reverse("accounts:register"))

    def test_expired_code_neutral_message(self):
        campaign = make_campaign(
            ends_at=timezone.now() - timedelta(hours=1),
            status=PromoCampaign.Status.ACTIVE,
        )
        client = Client()
        resp = client.get(f"/promos/join/{campaign.code}/")
        self.assertRedirects(resp, reverse("accounts:register"))

    def test_code_case_insensitive(self):
        campaign = make_campaign(code="Welcome25")
        client = Client()
        resp = client.get(f"/promos/join/welcome25/")
        self.assertEqual(resp.status_code, 200)
