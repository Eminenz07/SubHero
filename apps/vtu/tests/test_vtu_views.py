"""Integration checks for the VTU purchase views.

These cover the launch-critical path: data and airtime buy normally, and the
services that are not switched on yet render the "Soon" notice instead of
calling the provider.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.vtu.models import VTUPlan, AirtimeOrder, VTUOrder
from apps.wallet.models import Wallet


@override_settings(SECURE_SSL_REDIRECT=False)
class VtuViewFlowTests(TestCase):
    def setUp(self):
        self.user = self._make_user()
        self.user.set_pin("1234")
        self.client.force_login(self.user)
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        wallet.balance = Decimal("100000")
        wallet.save(update_fields=["balance"])

    def _make_user(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(
            phone_number="08012345678",
            email="vtu_tester@example.com",
            password="testpass123",
        )

    def _seed_plan(self):
        return VTUPlan.objects.create(
            plan_id="dancity-plan-1",
            name="MTN GIFTING 1GB",
            network="mtn",
            provider_product="MTN GIFTING",
            plan_type="GIFTING",
            provider_price=Decimal("200"),
            subhero_price=Decimal("230"),
            validity="30",
            is_active=True,
        )

    @override_settings(VTU_MOCK=True)
    @patch("apps.vtu.tasks.send_transaction_sms")
    def test_buy_data_creates_successful_order(self, _sms):
        plan = self._seed_plan()
        response = self.client.post(
            reverse("vtu:buy_data"),
            {
                "plan_id": plan.plan_id,
                "phone_number": "08012345678",
                "network": "mtn",
                "pin": "1234",
            },
        )

        self.assertEqual(response.status_code, 200)
        order = VTUOrder.objects.get()
        self.assertEqual(order.status, VTUOrder.Status.SUCCESS)
        self.assertEqual(order.plan_id, plan.plan_id)
        self.assertEqual(order.api_cost, plan.provider_price)

    @override_settings(VTU_MOCK=True)
    @patch("apps.vtu.tasks.send_transaction_sms")
    def test_buy_airtime_creates_successful_order(self, _sms):
        response = self.client.post(
            reverse("vtu:buy_airtime"),
            {
                "network": "mtn",
                "phone_number": "08012345678",
                "amount": "500",
                "pin": "1234",
            },
        )

        self.assertEqual(response.status_code, 200)
        order = AirtimeOrder.objects.get()
        self.assertEqual(order.status, AirtimeOrder.Status.SUCCESS)
        self.assertEqual(order.amount, Decimal("500"))

    @override_settings(VTU_ENABLE_CABLE=False)
    def test_cable_is_gated_behind_soon_notice(self):
        response = self.client.get(reverse("vtu:buy_cable"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Soon", status_code=503)

    @override_settings(VTU_ENABLE_ELECTRICITY=False)
    def test_electricity_is_gated_behind_soon_notice(self):
        response = self.client.get(reverse("vtu:buy_electricity"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Soon", status_code=503)

    @override_settings(VTU_ENABLE_EXAM=False)
    def test_exam_is_gated_behind_soon_notice(self):
        response = self.client.get(reverse("vtu:buy_exam_pin"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Soon")
        self.assertNotContains(response, "Coming Soon")
