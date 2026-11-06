"""Contract tests for the Dancity provider adapter.

Every upstream call is mocked, so these run without network access and without
an allowlisted IP.
"""

import json
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.vtu.providers.base import PurchaseStatus
from apps.vtu.providers.dancity import DancityProvider
from apps.vtu.providers.errors import (
    ProviderAuthError,
    ProviderDeclinedError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTransientError,
    ProviderValidationError,
)
from apps.vtu.tasks import _split_airtime_chunks


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
    return DancityProvider(api_key="dcy_live_test", base_url="https://api.dancity.test")


class DancityProviderPurchaseTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.provider = make_provider()

    def test_buy_data_returns_success_result(self):
        body = {
            "success": True,
            "message": "Data purchase processed",
            "data": {
                "_id": "65f0abc",
                "tranxId": "DNTY174825YP565I",
                "status": "SUCCESS",
                "amountPaid": 98.5,
            },
        }
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            result = self.provider.buy_data("plan-1", "08012345678", "REF-1")

        self.assertTrue(result.success)
        self.assertEqual(result.status, PurchaseStatus.SUCCESS)
        self.assertEqual(result.provider_ref, "DNTY174825YP565I")
        self.assertEqual(result.amount_paid, Decimal("98.5"))

        args, kwargs = request.call_args
        self.assertEqual(args[1], "https://api.dancity.test/api/v1/data/buy")
        self.assertEqual(kwargs["json"]["plan"], "plan-1")
        self.assertEqual(kwargs["json"]["customerRef"], "REF-1")
        self.assertEqual(kwargs["headers"]["channel"], "API")

    def test_failed_data_status_inside_successful_envelope_raises(self):
        body = {
            "success": True,
            "message": "Data purchase processed",
            "data": {
                "tranxId": "DNTY999",
                "status": "FAILED",
                "apiResponse": "Insufficient wallet balance",
            },
        }
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            with self.assertRaises(ProviderDeclinedError) as ctx:
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

        self.assertIn("Insufficient wallet balance", str(ctx.exception))

    def test_pending_status_is_not_treated_as_success(self):
        body = {
            "success": True,
            "data": {"tranxId": "DNTY100", "status": "PROCESSING"},
        }
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            result = self.provider.buy_data("plan-1", "08012345678", "REF-1")

        self.assertFalse(result.success)
        self.assertEqual(result.status, PurchaseStatus.PROCESSING)

    def test_unauthorized_response_raises_auth_error(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(401, {"message": "Invalid API key"})
            with self.assertRaises(ProviderAuthError):
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

    def test_rate_limit_raises_rate_limited_error(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(429, {"message": "Too many requests"})
            with self.assertRaises(ProviderRateLimitedError):
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

    def test_bad_request_raises_validation_error(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(400, {"message": "plan not found"})
            with self.assertRaises(ProviderValidationError):
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

    def test_bad_request_about_balance_raises_declined_error(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(400, {"message": "Insufficient balance"})
            with self.assertRaises(ProviderDeclinedError):
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

    def test_server_error_raises_transient_error(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(500, {"message": "boom"})
            with self.assertRaises(ProviderTransientError):
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

    def test_non_json_response_raises_transient_error(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(502, raw="<html>bad gateway</html>")
            with self.assertRaises(ProviderTransientError):
                self.provider.buy_data("plan-1", "08012345678", "REF-1")

    def test_missing_api_key_raises_auth_error_without_calling_out(self):
        provider = DancityProvider(api_key="", base_url="https://api.dancity.test")
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            with self.assertRaises(ProviderAuthError):
                provider.buy_data("plan-1", "08012345678", "REF-1")
        request.assert_not_called()


class DancityProviderValidationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.provider = make_provider()

    def test_validate_cable_returns_customer_name(self):
        body = {
            "success": True,
            "data": {"customerName": "ADEBAYO OLUWASEUN"},
        }
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            name = self.provider.validate_cable("7029123456", "DSTV")

        self.assertEqual(name, "ADEBAYO OLUWASEUN")
        _, kwargs = request.call_args
        self.assertEqual(kwargs["json"]["smartcardNumber"], "7029123456")
        self.assertEqual(kwargs["json"]["cablename"], "DSTV")

    def test_validate_cable_without_name_raises_validation_error(self):
        body = {"success": True, "data": {}}
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            with self.assertRaises(ProviderValidationError):
                self.provider.validate_cable("7029123456", "DSTV")

    def test_validate_meter_sends_biller_amount_and_meter_type(self):
        body = {"success": True, "data": {"customerName": "CHINEDU OBI"}}
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            name = self.provider.validate_meter("12345678901", "IKEDC", Decimal("5000"), "prepaid")

        self.assertEqual(name, "CHINEDU OBI")
        _, kwargs = request.call_args
        self.assertEqual(kwargs["json"]["billerCode"], "IKEDC")
        self.assertEqual(kwargs["json"]["amount"], 5000)
        self.assertEqual(kwargs["json"]["meterType"], "prepaid")

    def test_buy_electricity_sends_customer_name_and_address(self):
        body = {
            "success": True,
            "data": {"tranxId": "ELEC-1", "status": "SUCCESS", "token": "1234-5678-9012", "units": "12.5"},
        }
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, body)
            result = self.provider.buy_electricity(
                "12345678901", "IKEDC", "prepaid", Decimal("5000"),
                "CHINEDU OBI", "12 Allen Avenue, Ikeja, Lagos", "REF-9",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.extra["token"], "1234-5678-9012")
        _, kwargs = request.call_args
        self.assertEqual(kwargs["json"]["customerName"], "CHINEDU OBI")
        self.assertEqual(kwargs["json"]["address"], "12 Allen Avenue, Ikeja, Lagos")


class DancityProviderCatalogTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.provider = make_provider()

    def test_list_data_plans_maps_provider_product(self):
        plans = [
            {
                "planId": "abc123",
                "product": "MTN GIFTING",
                "plan": "1GB",
                "price": 200,
                "validity": "30",
            }
        ]
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, {"success": True, "data": plans})
            result = self.provider.list_data_plans()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].plan_id, "abc123")
        self.assertEqual(result[0].provider_product, "MTN GIFTING")
        self.assertEqual(result[0].price, Decimal("200"))

    def test_resolve_airtime_product_finds_network_product(self):
        products = [
            {"_id": "1", "name": "MTN Airtime"},
            {"_id": "2", "name": "Airtel Airtime"},
        ]
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, {"success": True, "data": products})
            product = self.provider.resolve_airtime_product("mtn")

        self.assertEqual(product, "MTN Airtime")

    def test_resolve_airtime_product_raises_when_missing(self):
        with patch("apps.vtu.providers.dancity.requests.request") as request:
            request.return_value = FakeResponse(200, {"success": True, "data": []})
            with self.assertRaises(ProviderNotFoundError):
                self.provider.resolve_airtime_product("mtn")


class AirtimeChunkingTests(SimpleTestCase):
    def test_amount_below_cap_is_a_single_chunk(self):
        chunks = _split_airtime_chunks(Decimal("500"), Decimal("1000"))
        self.assertEqual(chunks, [Decimal("500")])

    def test_amount_above_cap_is_split(self):
        chunks = _split_airtime_chunks(Decimal("2500"), Decimal("1000"))
        self.assertEqual(chunks, [Decimal("1000"), Decimal("1000"), Decimal("500")])

    def test_no_cap_keeps_single_chunk(self):
        chunks = _split_airtime_chunks(Decimal("50000"), None)
        self.assertEqual(chunks, [Decimal("50000")])

    def test_provider_advertises_its_cap(self):
        self.assertEqual(make_provider().max_airtime_amount, Decimal("1000"))


class DancityWebhookSignatureTests(SimpleTestCase):
    def test_valid_signature_is_accepted(self):
        from apps.vtu.webhooks import verify_signature

        secret = "whsec_test"
        raw = json.dumps({"event": "transaction.success"}).encode()
        import hashlib
        import hmac

        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(raw, signature, secret))

    def test_tampered_body_is_rejected(self):
        from apps.vtu.webhooks import verify_signature

        secret = "whsec_test"
        raw = json.dumps({"event": "transaction.success"}).encode()
        import hashlib
        import hmac

        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        self.assertFalse(verify_signature(raw + b" ", signature, secret))

    def test_missing_secret_is_rejected(self):
        from apps.vtu.webhooks import verify_signature

        self.assertFalse(verify_signature(b"{}", "abc", ""))
        self.assertFalse(verify_signature(b"{}", "", "secret"))
