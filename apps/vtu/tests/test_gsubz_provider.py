"""Contract tests for the GSUBZ provider adapter.

Every upstream call is mocked, so these run without network access.
"""

import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.vtu.providers.base import PurchaseStatus
from apps.vtu.providers.errors import (
    ProviderAuthError,
    ProviderDeclinedError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTransientError,
    ProviderValidationError,
)
from apps.vtu.providers.gsubz import GsubzProvider


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raw=None):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._raw is not None:
            raise ValueError("not json")
        return self._payload


def make_provider():
    return GsubzProvider(api_key="ap_test", base_url="https://api.gsubz.test")


class GsubzProviderPurchaseTests(SimpleTestCase):
    def setUp(self):
        self.provider = make_provider()

    def test_buy_data_returns_success_result(self):
        body = {
            "code": 200,
            "status": "successful",
            "transactionID": 3878886201,
            "amount": 2400,
            "amountPaid": 2284.56,
            "api_response": "You have successfully shared 10GB Data.",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            result = self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

        self.assertTrue(result.success)
        self.assertEqual(result.status, PurchaseStatus.SUCCESS)
        self.assertEqual(result.provider_ref, "3878886201")
        self.assertEqual(result.amount_paid, Decimal("2284.56"))

        args, kwargs = request.call_args
        self.assertEqual(args[1], "https://api.gsubz.test/api/pay/")
        self.assertEqual(kwargs["data"]["serviceID"], "mtn_sme")
        self.assertEqual(kwargs["data"]["plan"], "260")
        self.assertEqual(kwargs["data"]["amount"], "")
        self.assertEqual(kwargs["data"]["phone"], "08012345678")
        self.assertEqual(kwargs["data"]["requestID"], "REF-1")
        self.assertEqual(kwargs["data"]["api"], "ap_test")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ap_test")

    def test_http_200_with_failed_status_raises_declined(self):
        body = {
            "code": 200,
            "status": "failed",
            "description": "INSUFFICIENT_BALANCE",
            "api_response": "Your wallet balance is too low.",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            with self.assertRaises(ProviderDeclinedError) as ctx:
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

        self.assertIn("too low", str(ctx.exception))

    def test_invalid_api_key_raises_auth_error(self):
        body = {
            "code": 401,
            "status": "failed",
            "description": "INVALID_API_OR_NOT_FOUND",
            "api_response": "Invalid API key",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(401, body)
            with self.assertRaises(ProviderAuthError):
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_invalid_plan_raises_validation_error(self):
        body = {
            "code": 401,
            "status": "failed",
            "description": "INVALID_PLAN",
            "api_response": "Plan does not match the serviceID",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(401, body)
            with self.assertRaises(ProviderValidationError):
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_rate_limit_raises_rate_limited_error(self):
        body = {
            "code": 429,
            "status": "failed",
            "description": "TOO_MANY_REQUESTS",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(429, body)
            with self.assertRaises(ProviderRateLimitedError):
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_gateway_error_raises_transient_error(self):
        body = {
            "code": 502,
            "status": "failed",
            "description": "GATEWAY_ERROR",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(502, body)
            with self.assertRaises(ProviderTransientError):
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_service_disabled_raises_declined_error(self):
        body = {
            "code": 406,
            "status": "failed",
            "description": "SERVICE_DISABLED",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(406, body)
            with self.assertRaises(ProviderDeclinedError):
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_an_account_that_is_not_upgraded_raises_auth_error(self):
        body = {
            "code": "407",
            "description": "Chat Admin to get upgraded before using your API, Thank you!",
            "status": "TRANSACTION_FAILED",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            with self.assertRaises(ProviderAuthError) as ctx:
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

        self.assertIn("not enabled", str(ctx.exception))

    def test_timeout_raises_transient_error(self):
        import requests as requests_lib

        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.side_effect = requests_lib.exceptions.Timeout("timed out")
            with self.assertRaises(ProviderTransientError):
                self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_missing_api_key_raises_auth_error(self):
        provider = GsubzProvider(api_key="", base_url="https://api.gsubz.test")
        with self.assertRaises(ProviderAuthError):
            provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

    def test_malformed_plan_id_raises_validation_error(self):
        with self.assertRaises(ProviderValidationError):
            self.provider.buy_data("no-colon-here", "08012345678", "REF-1")

    def test_duplicate_request_id_returns_the_original_result(self):
        body = {
            "code": 406,
            "status": "successful",
            "description": "INVALID_ARGUMENTS_DUPLICATE_REQUEST_ID",
            "transactionID": 3878886201,
            "amountPaid": 2284.56,
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(406, body)
            result = self.provider.buy_data("mtn_sme:260", "08012345678", "REF-1")

        self.assertTrue(result.success)
        self.assertEqual(result.provider_ref, "3878886201")

    def test_buy_airtime_sends_amount(self):
        body = {
            "code": 200,
            "status": "successful",
            "transactionID": 3768661863,
            "amount": 800,
            "amountPaid": 768,
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            result = self.provider.buy_airtime("mtn", "08012345678", Decimal("800"), "REF-2")

        self.assertTrue(result.success)
        _, kwargs = request.call_args
        self.assertEqual(kwargs["data"]["serviceID"], "mtn")
        self.assertEqual(kwargs["data"]["amount"], "800")
        self.assertNotIn("plan", kwargs["data"])


class GsubzProviderCatalogTests(SimpleTestCase):
    def setUp(self):
        self.provider = make_provider()

    def test_list_data_plans_maps_service_and_display_name(self):
        body = {
            "service": "mtn_sme",
            "PlanName": "plan",
            "plans": [
                {"displayName": "10GB - 30days", "value": "260", "price": 2400, "api_price": 2284.56},
            ],
        }

        def side_effect(method, url, **kwargs):
            service = kwargs.get("params", {}).get("service")
            if service != "mtn_sme":
                return FakeResponse(404, {"description": "CONTENT_NOT_FOUND"})
            return FakeResponse(200, body)

        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.side_effect = side_effect
            result = self.provider.list_data_plans()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].plan_id, "mtn_sme:260")
        self.assertEqual(result[0].provider_product, "mtn_sme")
        self.assertEqual(result[0].size, "10GB")
        self.assertEqual(result[0].validity, "30")
        self.assertEqual(result[0].price, Decimal("2284.56"))

    def test_list_data_plans_skips_a_failing_service(self):
        def side_effect(method, url, **kwargs):
            if kwargs.get("params", {}).get("service") == "mtn_gifting":
                return FakeResponse(401, {"description": "INVALID_API_OR_NOT_FOUND"})
            return FakeResponse(200, {"plans": [{"displayName": "1GB", "value": "10", "api_price": 100}]})

        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.side_effect = side_effect
            result = self.provider.list_data_plans()

        self.assertTrue(result)
        self.assertFalse(any(plan.plan_id.startswith("mtn_gifting:") for plan in result))
        self.assertTrue(any(plan.plan_id == "mtn_sme:10" for plan in result))

    def test_resolve_airtime_product_maps_9mobile_to_etisalat(self):
        self.assertEqual(self.provider.resolve_airtime_product("9mobile"), "etisalat")
        self.assertEqual(self.provider.resolve_airtime_product("mtn"), "mtn")
        self.assertEqual(self.provider.resolve_airtime_product("glo"), "glo")

    def test_resolve_airtime_product_raises_for_unknown_network(self):
        with self.assertRaises(ProviderNotFoundError):
            self.provider.resolve_airtime_product("vodafone")

    def test_cable_and_electricity_are_not_enabled(self):
        with self.assertRaises(ProviderNotFoundError):
            self.provider.list_cable_plans()
        with self.assertRaises(ProviderNotFoundError):
            self.provider.list_electricity_products()
        with self.assertRaises(ProviderNotFoundError):
            self.provider.list_exam_products()


class GsubzProviderAccountTests(SimpleTestCase):
    def setUp(self):
        self.provider = make_provider()

    def test_get_balance_reads_the_wallet(self):
        body = {"balance": "747.5"}
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            balance = self.provider.get_balance()

        self.assertEqual(balance, Decimal("747.5"))
        args, kwargs = request.call_args
        self.assertEqual(args[1], "https://api.gsubz.test/api/balance/")
        self.assertEqual(kwargs["data"]["api"], "ap_test")

    def test_get_transaction_normalizes_successful_description(self):
        body = {
            "code": "200",
            "status": "success",
            "description": "TRANSACTION_SUCCESSFUL",
            "transaction_id": "3574357094",
            "amount": "1100",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            transaction = self.provider.get_transaction("REF-1")

        self.assertEqual(transaction["status"], "SUCCESS")
        self.assertEqual(transaction["transaction_id"], "3574357094")

    def test_get_transaction_normalizes_failed_description(self):
        body = {
            "code": "404",
            "status": "TRANSACTION_FAILED",
            "description": "CONTENT_NOT_FOUND_API_OR_NOT_FOUND",
        }
        with patch("apps.vtu.providers.gsubz.requests.request") as request:
            request.return_value = FakeResponse(404, body)
            transaction = self.provider.get_transaction("REF-1")

        self.assertEqual(transaction["status"], "FAILED")


class GsubzWebhookSignatureTests(SimpleTestCase):
    def setUp(self):
        from apps.vtu.webhooks import verify_gsubz_signature

        self.verify = verify_gsubz_signature
        self.secret = "gsubz_secret"
        self.raw = json.dumps({"event": "transaction.updated"}).encode()
        self.timestamp = str(int(time.time()))
        self.signature = "sha256=" + hmac.new(
            self.secret.encode(), f"{self.timestamp}.".encode() + self.raw, hashlib.sha256
        ).hexdigest()

    def test_valid_signature_is_accepted(self):
        self.assertTrue(self.verify(self.raw, self.signature, self.timestamp, self.secret))

    def test_tampered_body_is_rejected(self):
        self.assertFalse(self.verify(self.raw + b" ", self.signature, self.timestamp, self.secret))

    def test_missing_prefix_is_rejected(self):
        raw_signature = self.signature.replace("sha256=", "")
        self.assertFalse(self.verify(self.raw, raw_signature, self.timestamp, self.secret))

    def test_stale_timestamp_is_rejected(self):
        old = str(int(time.time()) - 3600)
        old_signature = "sha256=" + hmac.new(
            self.secret.encode(), f"{old}.".encode() + self.raw, hashlib.sha256
        ).hexdigest()
        self.assertFalse(self.verify(self.raw, old_signature, old, self.secret))

    def test_missing_secret_is_rejected(self):
        self.assertFalse(self.verify(self.raw, self.signature, self.timestamp, ""))
