"""
Tests for FundWalletView.get — amount prefill clamping, invalid input,
and return_to session handling.
"""
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse

from django.contrib.auth import get_user_model
from apps.wallet.models import Wallet


class FundWalletViewPrefillTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            phone_number="08012345678",
            email="fund_tester@example.com",
            password="testpass123",
        )
        self.user.set_pin("1234")
        self.client.force_login(self.user)
        # Wallet auto-created by accounts.signals post_save on User
        self.wallet = Wallet.objects.get(user=self.user)

    def test_valid_amount_prefilled(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "750"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["prefill_amount"], 750)
        self.assertContains(response, 'value="750"')

    def test_amount_rounded_up_to_whole_naira(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "750.50"})
        self.assertEqual(response.context["prefill_amount"], 751)

    def test_amount_below_min_is_clamped_to_min(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "10"})
        self.assertEqual(response.context["prefill_amount"], 100)  # FUND_MIN_AMOUNT

    def test_amount_above_max_is_clamped_to_max(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "999999999"})
        self.assertEqual(response.context["prefill_amount"], 500000)  # FUND_MAX_AMOUNT

    def test_non_numeric_amount_ignored(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "abc"})
        self.assertIsNone(response.context["prefill_amount"])

    def test_negative_amount_ignored(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "-500"})
        self.assertIsNone(response.context["prefill_amount"])

    def test_zero_amount_ignored(self):
        response = self.client.get(reverse("wallet:fund"), {"amount": "0"})
        self.assertIsNone(response.context["prefill_amount"])

    def test_no_amount_param_no_prefill(self):
        response = self.client.get(reverse("wallet:fund"))
        self.assertIsNone(response.context["prefill_amount"])

    @override_settings(FUND_MIN_AMOUNT=100, FUND_MAX_AMOUNT=500000)
    def test_valid_return_to_stored_in_session(self):
        response = self.client.get(
            reverse("wallet:fund"),
            {"amount": "1000", "return_to": "/smm/?platform=instagram&tier=premium"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["return_to"], "/smm/?platform=instagram&tier=premium")

    def test_return_to_cleared_when_absent(self):
        self.client.session["return_to"] = "/some/path/"
        self.client.session.save()
        self.client.get(reverse("wallet:fund"), {"amount": "1000"})
        self.assertNotIn("return_to", self.client.session)

    def test_absolute_return_to_rejected_and_cleared(self):
        self.client.session["return_to"] = "/some/path/"
        self.client.session.save()
        self.client.get(
            reverse("wallet:fund"),
            {"amount": "1000", "return_to": "https://evil.com"},
        )
        self.assertNotIn("return_to", self.client.session)

    def test_protocol_relative_return_to_rejected(self):
        self.client.get(
            reverse("wallet:fund"),
            {"amount": "1000", "return_to": "//evil.com"},
        )
        self.assertNotIn("return_to", self.client.session)

    def test_javascript_return_to_rejected(self):
        self.client.get(
            reverse("wallet:fund"),
            {"amount": "1000", "return_to": "javascript:alert(1)"},
        )
        self.assertNotIn("return_to", self.client.session)
