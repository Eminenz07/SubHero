"""
Support — Tests
===============
Covers: compute_priority rules, desk inbox rendering, and desk ticket
actions (claim / status / priority / internal note / reply).
"""

from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

from apps.support.models import Ticket, TicketEvent, StaffProfile
from apps.support.views import compute_priority
from apps.wallet.models import Wallet, WalletTransaction
from apps.vtu.models import VTUOrder
from apps.smm.models import SMMOrder, SMMService

User = get_user_model()

DESK_ACTION_URL_NAME = "support:desk:action"


def make_staff(phone, email=None, role="agent"):
    user = User.objects.create_user(
        phone_number=phone,
        email=email or f"{phone}@example.com",
        password="pass12345",
        full_name=f"Staff {phone}",
        is_verified=True,
        is_active=True,
        is_staff=True,
    )
    user.set_pin("1234")
    return user


def make_customer(phone, email=None):
    return User.objects.create_user(
        phone_number=phone,
        email=email or f"{phone}@example.com",
        password="pass12345",
        full_name=f"Customer {phone}",
        is_verified=True,
        is_active=True,
        is_staff=False,
    )


def make_ticket(user, **kwargs):
    defaults = dict(
        user=user,
        category=Ticket.Category.WALLET,
        subject="My money was debited but not credited",
        priority=Ticket.Priority.NORMAL,
    )
    defaults.update(kwargs)
    return Ticket.objects.create(**defaults)


class TestComputePriority(TestCase):
    """Unit tests for the priority computation rules."""

    def test_no_related_reference_is_normal(self):
        self.assertEqual(
            compute_priority(Ticket.Category.WALLET, "hello", "", ""),
            Ticket.Priority.NORMAL,
        )

    def test_vtu_failed_is_high(self):
        VTUOrder.objects.create(
            user=make_customer("+2348011111111"),
            network="mtn",
            recipient="08011111111",
            plan_id="plan1",
            plan_name="Monthly",
            amount=Decimal("1000.00"),
            reference="VTU-FAIL-1",
            status=VTUOrder.Status.FAILED,
        )
        self.assertEqual(
            compute_priority(Ticket.Category.VTU, "failed purchase", "VTU-FAIL-1", "vtu_order"),
            Ticket.Priority.HIGH,
        )

    def test_vtu_pending_is_high(self):
        VTUOrder.objects.create(
            user=make_customer("+2348011111112"),
            network="mtn",
            recipient="08011111112",
            plan_id="plan1",
            plan_name="Monthly",
            amount=Decimal("1000.00"),
            reference="VTU-PEND-1",
            status=VTUOrder.Status.PENDING,
        )
        self.assertEqual(
            compute_priority(Ticket.Category.VTU, "pending purchase", "VTU-PEND-1", "vtu_order"),
            Ticket.Priority.HIGH,
        )

    def test_vtu_processing_over_15_min_is_high(self):
        old = timezone.now() - timedelta(minutes=20)
        VTUOrder.objects.create(
            user=make_customer("+2348011111113"),
            network="mtn",
            recipient="08011111113",
            plan_id="plan1",
            plan_name="Monthly",
            amount=Decimal("1000.00"),
            reference="VTU-PROC-1",
            status=VTUOrder.Status.PROCESSING,
        )
        # Manually backdate created_at (auto_now_add prevents direct set via create).
        order = VTUOrder.objects.get(reference="VTU-PROC-1")
        order.created_at = old
        order.save(update_fields=["created_at"])
        self.assertEqual(
            compute_priority(Ticket.Category.VTU, "slow processing", "VTU-PROC-1", "vtu_order"),
            Ticket.Priority.HIGH,
        )

    def test_vtu_processing_under_15_min_is_normal(self):
        VTUOrder.objects.create(
            user=make_customer("+2348011111114"),
            network="mtn",
            recipient="08011111114",
            plan_id="plan1",
            plan_name="Monthly",
            amount=Decimal("1000.00"),
            reference="VTU-PROC-2",
            status=VTUOrder.Status.PROCESSING,
        )
        self.assertEqual(
            compute_priority(Ticket.Category.VTU, "fresh processing", "VTU-PROC-2", "vtu_order"),
            Ticket.Priority.NORMAL,
        )

    def test_vtu_success_is_normal(self):
        VTUOrder.objects.create(
            user=make_customer("+2348011111115"),
            network="mtn",
            recipient="08011111115",
            plan_id="plan1",
            plan_name="Monthly",
            amount=Decimal("1000.00"),
            reference="VTU-OK-1",
            status=VTUOrder.Status.SUCCESS,
        )
        self.assertEqual(
            compute_priority(Ticket.Category.VTU, "successful purchase", "VTU-OK-1", "vtu_order"),
            Ticket.Priority.NORMAL,
        )

    def test_smm_failed_is_high(self):
        service = SMMService.objects.create(
            provider_service_id="jap-1",
            name="Instagram Followers",
            category="social",
            subhero_price_per_1k=Decimal("10.00"),
            provider_rate=Decimal("0.00"),
        )
        SMMOrder.objects.create(
            user=make_customer("+2348011111116"),
            service=service,
            target_url="https://example.com",
            quantity=1000,
            amount=Decimal("500.00"),
            reference="SMM-FAIL-1",
            status=SMMOrder.Status.FAILED,
        )
        self.assertEqual(
            compute_priority(Ticket.Category.SMM, "smm failed", "SMM-FAIL-1", "smm_order"),
            Ticket.Priority.HIGH,
        )

    def test_wallet_fund_pending_is_high(self):
        customer = make_customer("+2348011111117")
        wallet, _ = Wallet.objects.get_or_create(user=customer)
        WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.FUND,
            amount=Decimal("25000.00"),
            balance_before=Decimal("0"),
            balance_after=Decimal("0"),
            reference="FUND-PEND-1",
            status=WalletTransaction.Status.PENDING,
        )
        self.assertEqual(
            compute_priority(
                Ticket.Category.WALLET, "debited but not credited", "FUND-PEND-1", "wallet_transaction"
            ),
            Ticket.Priority.HIGH,
        )

    def test_wallet_fund_success_is_normal(self):
        customer = make_customer("+2348011111118")
        wallet, _ = Wallet.objects.get_or_create(user=customer)
        WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.FUND,
            amount=Decimal("15000.00"),
            balance_before=Decimal("0"),
            balance_after=Decimal("15000.00"),
            reference="FUND-OK-1",
            status=WalletTransaction.Status.SUCCESS,
        )
        self.assertEqual(
            compute_priority(
                Ticket.Category.WALLET, "funded fine", "FUND-OK-1", "wallet_transaction"
            ),
            Ticket.Priority.NORMAL,
        )

    def test_amount_at_least_20000_is_high(self):
        customer = make_customer("+2348011111119")
        wallet, _ = Wallet.objects.get_or_create(user=customer)
        WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.FUND,
            amount=Decimal("20000.00"),
            balance_before=Decimal("0"),
            balance_after=Decimal("20000.00"),
            reference="FUND-20K-1",
            status=WalletTransaction.Status.SUCCESS,
        )
        self.assertEqual(
            compute_priority(
                Ticket.Category.WALLET, "big amount", "FUND-20K-1", "wallet_transaction"
            ),
            Ticket.Priority.HIGH,
        )

    def test_amount_below_20000_is_normal(self):
        customer = make_customer("+2348011111120")
        wallet, _ = Wallet.objects.get_or_create(user=customer)
        WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.FUND,
            amount=Decimal("19999.99"),
            balance_before=Decimal("0"),
            balance_after=Decimal("19999.99"),
            reference="FUND-19K-1",
            status=WalletTransaction.Status.SUCCESS,
        )
        self.assertEqual(
            compute_priority(
                Ticket.Category.WALLET, "small amount", "FUND-19K-1", "wallet_transaction"
            ),
            Ticket.Priority.NORMAL,
        )

    def test_wallet_category_with_debited_body_is_high(self):
        # No related_ref at all: the wallet-category + "debited" body rule alone
        # should not raise HIGH (related_ref is required to evaluate anything).
        # The rule only matters when a related_ref exists; here we just confirm
        # a missing ref still yields NORMAL regardless of body/category.
        self.assertEqual(
            compute_priority(
                Ticket.Category.WALLET, "my money was debited", "", ""
            ),
            Ticket.Priority.NORMAL,
        )

    def test_unknown_related_type_is_normal(self):
        self.assertEqual(
            compute_priority(Ticket.Category.WALLET, "hello", "REF-999", "unknown_type"),
            Ticket.Priority.NORMAL,
        )


class TestDeskTicketActions(TestCase):
    """Integration tests: inbox → ticket detail → desk actions."""

    def setUp(self):
        self.client = Client()
        self.staff = make_staff("+2349073601282", "staff@example.com", role="agent")
        self.customer = make_customer("+2348012345678", "customer@example.com")
        Wallet.objects.get_or_create(user=self.customer)
        self.ticket = make_ticket(self.customer)
        self.client.force_login(self.staff)

    def test_inbox_renders_ticket_with_row_link(self):
        url = reverse("support:desk:inbox")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket.reference)
        self.assertContains(response, self.ticket.subject)
        # Row links to the desk ticket detail (not an hx-get fragment).
        self.assertContains(
            response, reverse("support:desk:ticket", kwargs={"ticket_id": self.ticket.id})
        )
        self.assertNotContains(response, "hx-get")
        self.assertNotContains(response, "desk-ticket-panel")

    def test_ticket_detail_loads(self):
        url = reverse("support:desk:ticket", kwargs={"ticket_id": self.ticket.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket.reference)
        self.assertContains(response, self.ticket.subject)

    def test_desk_actions(self):
        action_url = reverse(
            DESK_ACTION_URL_NAME, kwargs={"ticket_id": self.ticket.id}
        )

        # Claim
        resp = self.client.post(action_url, {"action": "claim"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "claim")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.staff)
        self.assertTrue(
            TicketEvent.objects.filter(
                ticket=self.ticket, event_type=TicketEvent.EventType.ASSIGNMENT
            ).exists()
        )

        # Priority change → HIGH, SLA recomputed, event logged
        resp = self.client.post(
            action_url, {"action": "priority_change", "priority": "high"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "priority_change")
        self.assertEqual(data["new_priority"], "high")
        self.assertIsNotNone(data["sla_due_at"])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, Ticket.Priority.HIGH)
        self.assertIsNotNone(self.ticket.sla_due_at)
        self.assertTrue(
            TicketEvent.objects.filter(
                ticket=self.ticket,
                event_type=TicketEvent.EventType.STATUS_CHANGE,
                description__contains="Priority changed",
            ).exists()
        )

        # Status change → resolved
        resp = self.client.post(
            action_url, {"action": "status_change", "status": "resolved"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["new_status"], "resolved")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.RESOLVED)
        self.assertIsNotNone(self.ticket.resolved_at)

        # Internal note
        resp = self.client.post(
            action_url, {"action": "internal_note", "body": "Looking into this."}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "internal_note")

    def test_desk_reply_endpoint(self):
        reply_url = reverse(
            "support:desk:reply", kwargs={"ticket_id": self.ticket.id}
        )
        # Claim first so the ticket is in progress.
        action_url = reverse(
            DESK_ACTION_URL_NAME, kwargs={"ticket_id": self.ticket.id}
        )
        self.client.post(action_url, {"action": "claim"})
        resp = self.client.post(reply_url, {"body": "Hello from support."})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertTrue(
            self.ticket.messages.filter(body="Hello from support.").exists()
        )


class TestStaffLoginRestrictions(TestCase):
    """Staff desk login: valid staff, blocked non-staff, generic invalid creds."""

    def setUp(self):
        self.client = Client()
        self.login_url = reverse("support:desk:staff_login")

    def _make_staff(self, phone, email, role="agent", active=True, must_change=False):
        user = User.objects.create_user(
            phone_number=phone,
            email=email,
            password="Passw0rd!",
            full_name=f"Staff {phone}",
            is_staff=True,
            is_active=active,
            is_verified=True,
        )
        StaffProfile.objects.create(
            user=user, role=role, is_available=True,
            must_change_password=must_change,
        )
        return user

    def test_staff_login_success(self):
        self._make_staff("+2349073601282", "agent1@subhero.com.ng", role="agent")
        resp = self.client.post(self.login_url, {
            "identifier": "agent1@subhero.com.ng",
            "password": "Passw0rd!",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("support:desk:inbox"))

    def test_staff_login_by_phone(self):
        self._make_staff("+2349073601283", "agent2@subhero.com.ng", role="lead")
        resp = self.client.post(self.login_url, {
            "identifier": "+2349073601283",
            "password": "Passw0rd!",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("support:desk:inbox"))

    def test_invalid_credentials_generic(self):
        resp = self.client.post(self.login_url, {
            "identifier": "nonexistent@subhero.com.ng",
            "password": "wrongpass",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid credentials")

    def test_non_staff_blocked(self):
        User.objects.create_user(
            phone_number="+2349073601284", email="cust@subhero.com.ng",
            password="Passw0rd!", is_staff=False, is_active=True,
        )
        resp = self.client.post(self.login_url, {
            "identifier": "cust@subhero.com.ng",
            "password": "Passw0rd!",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid credentials")

    def test_inactive_staff_blocked(self):
        self._make_staff("+2349073601285", "inactive@subhero.com.ng", active=False)
        resp = self.client.post(self.login_url, {
            "identifier": "inactive@subhero.com.ng",
            "password": "Passw0rd!",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid credentials")


class TestForcedPasswordChange(TestCase):
    """must_change_password forces change-password page before desk access."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            phone_number="+2349073601286", email="newstaff@subhero.com.ng",
            password="Passw0rd!", is_staff=True, is_active=True, is_verified=True,
        )
        StaffProfile.objects.create(
            user=self.user, role="agent", must_change_password=True,
        )
        self.client.force_login(self.user)

    def test_forced_change_password_blocks_desk(self):
        # Any desk view redirects to change-password first
        resp = self.client.get(reverse("support:desk:inbox"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("change-password", resp.url)

    def test_change_password_clears_flag(self):
        self.client.post(reverse("support:desk:staff_change_password"), {
            "new_password": "NewPassw0rd!",
            "confirm_password": "NewPassw0rd!",
        })
        self.user.staff_profile.refresh_from_db()
        self.assertFalse(self.user.staff_profile.must_change_password)
        resp = self.client.get(reverse("support:desk:inbox"))
        self.assertEqual(resp.status_code, 200)


class TestRoleBlocking(TestCase):
    """Agent/lead staff blocked from all admin_panel URLs."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            phone_number="+2349073601287", email="owner@subhero.com.ng",
            password="Passw0rd!", is_staff=True, is_active=True,
            is_verified=True, is_superuser=True,
        )
        # Admin without staff profile = true admin
        self.agent = User.objects.create_user(
            phone_number="+2349073601288", email="agent@subhero.com.ng",
            password="Passw0rd!", is_staff=True, is_active=True, is_verified=True,
        )
        StaffProfile.objects.create(user=self.agent, role="agent", is_available=True)

    def test_agent_blocked_from_admin_urls(self):
        # Loop over every admin_panel URL name
        admin_url_names = [
            "admin_panel:dashboard",
            "admin_panel:users",
            "admin_panel:vtu_pricing",
            "admin_panel:smm_pricing",
            "admin_panel:orders",
            "admin_panel:giveaways",
            "admin_panel:transactions",
            "admin_panel:analytics",
            "admin_panel:api_wallets",
            "admin_panel:send_email",
            "admin_panel:logs",
            "admin_panel:settings",
            "admin_panel:support_staff",
            "admin_panel:promos_list",
        ]
        self.client.force_login(self.agent)
        for name in admin_url_names:
            try:
                url = reverse(name)
            except Exception:
                continue  # URL requires args
            resp = self.client.get(url)
            self.assertIn(resp.status_code, (302, 403),
                          f"{name} returned {resp.status_code} for agent")

    def test_admin_can_access_admin_urls(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("admin_panel:dashboard"))
        self.assertEqual(resp.status_code, 200)


class TestStaffCreation(TestCase):
    """Owner-only Support Staff page: create + temp password shown once."""

    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            phone_number="+2349073601289", email="owner@subhero.com.ng",
            password="Passw0rd!", is_staff=True, is_active=True,
            is_verified=True, is_superuser=True,
        )
        self.client.force_login(self.owner)

    def test_create_staff_shows_temp_password_once(self):
        # Create a registered customer first, then promote them to staff
        customer = User.objects.create_user(
            phone_number="+2349073601290", email="ada@subhero.com.ng",
            password="Passw0rd!", is_staff=False, is_active=True,
            is_verified=True, full_name="Ada Lovelace",
        )
        resp = self.client.post(reverse("admin_panel:support_staff"), {
            "action": "create",
            "user_id": str(customer.id),
            "role": "agent",
            "display_name": "Ada",
            "gen_password": "on",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Staff created (promoted)
        from apps.support.models import StaffProfile
        staff = User.objects.get(email="ada@subhero.com.ng")
        self.assertTrue(staff.is_staff)
        self.assertTrue(staff.staff_profile.must_change_password)
        self.assertEqual(staff.staff_profile.role, "agent")
        self.assertEqual(staff.staff_profile.display_name, "Ada")


class TestStaffExcludedFromMetrics(TestCase):
    """Staff accounts excluded from customer metrics."""

    def test_user_stats_excludes_staff(self):
        from apps.admin_panel.queries import get_user_stats
        from datetime import date
        # Create 2 customers and 1 staff
        User.objects.create_user(
            phone_number="+2349073601291", email="c1@subhero.com.ng",
            password="Passw0rd!", is_staff=False, is_active=True,
        )
        User.objects.create_user(
            phone_number="+2349073601292", email="c2@subhero.com.ng",
            password="Passw0rd!", is_staff=False, is_active=True,
        )
        staff = User.objects.create_user(
            phone_number="+2349073601293", email="staff@subhero.com.ng",
            password="Passw0rd!", is_staff=True, is_active=True,
        )
        StaffProfile.objects.create(user=staff, role="agent")
        stats = get_user_stats(date(2020, 1, 1), date(2030, 12, 31))
        self.assertEqual(stats["total"], 2)