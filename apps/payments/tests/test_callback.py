"""
Tests for payment_callback — redirect to session return_to after a
successful card payment, else dashboard.
"""
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.test import TestCase
from django.urls import reverse

from django.contrib.auth import get_user_model


class PaymentCallbackReturnToTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            phone_number="08012345678",
            email="callback_tester@example.com",
            password="testpass123",
        )
        self.user.set_pin("1234")
        self.client.force_login(self.user)
        self.callback_url = reverse("payments:payment_callback")

    def _set_session_return_to(self, return_to):
        session = SessionStore()
        session["return_to"] = return_to
        session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

    def _mock_successful_verification(self, mock_verify):
        mock_verify.return_value = {
            "status": 200,
            "data": {
                "transaction_status": "success",
                "amount": 100000,  # 100000 kobo = ₦1000
                "metadata": {"user_id": str(self.user.id)},
            },
        }

    @patch("apps.payments.views.credit_wallet")
    @patch("apps.payments.services.verify_transaction")
    def test_redirects_to_return_to_after_success(self, mock_verify, mock_credit):
        self._mock_successful_verification(mock_verify)
        self._set_session_return_to("/smm/?platform=instagram&tier=premium")

        response = self.client.get(self.callback_url, {"transaction_ref": "SH-FUND-ABC123"})
        self.assertRedirects(response, "/smm/?platform=instagram&tier=premium", fetch_redirect_response=False)
        self.assertNotIn("return_to", self.client.session)

    @patch("apps.payments.views.credit_wallet")
    @patch("apps.payments.services.verify_transaction")
    def test_redirects_to_dashboard_when_no_return_to(self, mock_verify, mock_credit):
        self._mock_successful_verification(mock_verify)
        response = self.client.get(self.callback_url, {"transaction_ref": "SH-FUND-ABC123"})
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)

    @patch("apps.payments.views.credit_wallet")
    @patch("apps.payments.services.verify_transaction")
    def test_invalid_return_to_redirects_to_dashboard(self, mock_verify, mock_credit):
        self._mock_successful_verification(mock_verify)
        self._set_session_return_to("https://evil.com")

        response = self.client.get(self.callback_url, {"transaction_ref": "SH-FUND-ABC123"})
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
        self.assertNotIn("return_to", self.client.session)

    @patch("apps.payments.views.credit_wallet")
    @patch("apps.payments.services.verify_transaction")
    def test_protocol_relative_return_to_redirects_to_dashboard(self, mock_verify, mock_credit):
        self._mock_successful_verification(mock_verify)
        self._set_session_return_to("//evil.com")

        response = self.client.get(self.callback_url, {"transaction_ref": "SH-FUND-ABC123"})
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)

    @patch("apps.payments.views.credit_wallet")
    @patch("apps.payments.services.verify_transaction")
    def test_javascript_return_to_redirects_to_dashboard(self, mock_verify, mock_credit):
        self._mock_successful_verification(mock_verify)
        self._set_session_return_to("javascript:alert(1)")

        response = self.client.get(self.callback_url, {"transaction_ref": "SH-FUND-ABC123"})
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
