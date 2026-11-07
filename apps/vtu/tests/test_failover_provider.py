"""Tests for the failover provider chain.

These use fake providers, so they run without network access and without a
funded merchant account.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.vtu.providers.base import PurchaseResult, PurchaseStatus, VTUProvider
from apps.vtu.providers.errors import (
    ProviderDeclinedError,
    ProviderNotFoundError,
    ProviderTransientError,
    ProviderValidationError,
)
from apps.vtu.providers.failover import FailoverProvider


class FakeProvider(VTUProvider):
    """A provider that returns canned answers."""

    def __init__(self, name="fake", result=None, error=None, transaction=None, max_amount=None):
        self.name = name
        self._result = result
        self._error = error
        self._transaction = transaction or {"status": "UNKNOWN"}
        self.max_airtime_amount = max_amount
        self.calls = []

    def _behave(self, method, *args):
        self.calls.append((method, args))
        if self._error is not None:
            raise self._error
        return self._result

    def get_balance(self):
        if self._error is not None:
            raise self._error
        self.calls.append(("get_balance", ()))
        return Decimal("100")

    def get_wallets(self):
        return [{"wallettype": "main", "balance": Decimal("100"), "currency": "NGN"}]

    def list_data_plans(self):
        return []

    def list_cable_plans(self):
        return []

    def list_airtime_products(self):
        return []

    def list_electricity_products(self):
        return []

    def list_exam_products(self):
        return []

    def resolve_airtime_product(self, network):
        return network

    def resolve_cable_product(self, provider):
        return provider

    def resolve_electricity_biller(self, biller_code):
        return biller_code

    def buy_data(self, plan_id, phone, reference):
        return self._behave("buy_data", plan_id, phone, reference)

    def buy_airtime(self, product, phone, amount, reference):
        return self._behave("buy_airtime", product, phone, amount, reference)

    def validate_cable(self, smartcard, provider):
        return "CUSTOMER"

    def buy_cable(self, plan_id, smartcard, customer_name, reference):
        return self._behave("buy_cable", plan_id, smartcard, customer_name, reference)

    def validate_meter(self, meter_number, biller_code, amount, meter_type):
        return "CUSTOMER"

    def buy_electricity(self, meter_number, biller_code, meter_type, amount, customer_name, address, reference):
        return self._behave("buy_electricity")

    def buy_exam_pin(self, exam_name, quantity, reference, exam_number=""):
        return self._behave("buy_exam_pin")

    def get_transaction(self, transaction_ref):
        return self._transaction


def success(ref="REF-1"):
    return PurchaseResult(True, PurchaseStatus.SUCCESS, ref, "ok", Decimal("100"))


class FailoverProviderTests(TestCase):
    def setUp(self):
        from apps.vtu.models import VTUPlan

        self.plan = VTUPlan.objects.create(
            plan_id="plan-1",
            provider_product="mtn_sme",
            network="mtn",
            plan_type="SME",
            name="10GB - 30days",
            provider_price=Decimal("2284.56"),
            subhero_price=Decimal("2400"),
            provider_plan_ids={"primary": "plan-1", "backup": "plan-1"},
        )

    def test_first_provider_serves_the_order(self):
        primary = FakeProvider("primary", result=success("A"))
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        result = chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertEqual(result.provider_ref, "A")
        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(backup.calls, [])

    def test_declined_primary_fails_over_to_the_backup(self):
        primary = FakeProvider("primary", error=ProviderDeclinedError("no funds"))
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        result = chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertEqual(result.provider_ref, "B")

    def test_validation_failure_fails_over_to_the_backup(self):
        primary = FakeProvider("primary", error=ProviderValidationError("bad plan"))
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        result = chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertEqual(result.provider_ref, "B")

    def test_all_providers_failing_raises_declined(self):
        primary = FakeProvider("primary", error=ProviderDeclinedError("no funds"))
        backup = FakeProvider("backup", error=ProviderValidationError("bad plan"))
        chain = FailoverProvider([primary, backup])

        with self.assertRaises(ProviderDeclinedError) as ctx:
            chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertIn("primary", str(ctx.exception))
        self.assertIn("backup", str(ctx.exception))

    def test_transient_failure_without_a_known_outcome_does_not_fail_over(self):
        primary = FakeProvider(
            "primary",
            error=ProviderTransientError("timeout"),
            transaction={"status": "UNKNOWN"},
        )
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        with self.assertRaises(ProviderTransientError):
            chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertEqual(backup.calls, [])

    def test_transient_failure_that_already_succeeded_returns_the_success(self):
        primary = FakeProvider(
            "primary",
            error=ProviderTransientError("timeout"),
            transaction={"status": "SUCCESS", "transaction_id": "TX-1"},
        )
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        result = chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertTrue(result.success)
        self.assertEqual(result.provider_ref, "TX-1")
        self.assertEqual(backup.calls, [])

    def test_transient_failure_that_already_failed_fails_over(self):
        primary = FakeProvider(
            "primary",
            error=ProviderTransientError("timeout"),
            transaction={"status": "FAILED"},
        )
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        result = chain.buy_data("plan-1", "08012345678", "REF-1")

        self.assertEqual(result.provider_ref, "B")

    def test_airtime_uses_each_providers_own_product_name(self):
        primary = FakeProvider("primary", result=success("A"))
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        chain.buy_airtime("mtn", "08012345678", Decimal("500"), "REF-1")

        self.assertEqual(primary.calls[0][1][0], "mtn")
        self.assertEqual(backup.calls, [])

    def test_airtime_falls_over_when_the_first_provider_lacks_the_network(self):
        class NoMtnProvider(FakeProvider):
            def resolve_airtime_product(self, network):
                if network == "mtn":
                    raise ProviderNotFoundError("no mtn airtime")
                return network

        primary = NoMtnProvider("primary", result=success("A"))
        backup = FakeProvider("backup", result=success("B"))
        chain = FailoverProvider([primary, backup])

        result = chain.buy_airtime("mtn", "08012345678", Decimal("500"), "REF-1")

        self.assertEqual(result.provider_ref, "B")
        self.assertEqual(primary.calls, [])
        self.assertEqual(backup.calls[0][1][0], "mtn")

    def test_max_airtime_amount_is_the_cap_of_the_first_provider(self):
        chain = FailoverProvider([
            FakeProvider("primary", max_amount=None),
            FakeProvider("backup", max_amount=Decimal("1000")),
        ])
        self.assertIsNone(chain.max_airtime_amount)

    def test_max_airtime_amount_is_none_when_no_provider_has_a_cap(self):
        chain = FailoverProvider([FakeProvider("primary", max_amount=None)])
        self.assertIsNone(chain.max_airtime_amount)

    def test_a_capped_provider_splits_the_amount(self):
        chain = FailoverProvider([
            FakeProvider("primary", max_amount=Decimal("1000"), result=success()),
        ])

        chain.buy_airtime("mtn", "08012345678", Decimal("2500"), "REF-1")

        chunks = [call[1][2] for call in chain.providers[0].calls]
        self.assertEqual(chunks, [Decimal("1000"), Decimal("1000"), Decimal("500")])

    def test_a_provider_without_a_cap_takes_the_whole_amount(self):
        chain = FailoverProvider([
            FakeProvider("primary", max_amount=None, result=success()),
        ])

        chain.buy_airtime("mtn", "08012345678", Decimal("2500"), "REF-1")

        chunks = [call[1][2] for call in chain.providers[0].calls]
        self.assertEqual(chunks, [Decimal("2500")])

    def test_a_partial_delivery_is_reported(self):
        from apps.vtu.providers.errors import ProviderPartialDeliveryError

        class PartialProvider(FakeProvider):
            def buy_airtime(self, product, phone, amount, reference):
                self.calls.append(("buy_airtime", (product, phone, amount, reference)))
                if len(self.calls) == 1:
                    return success("A")
                raise ProviderDeclinedError("out of credit")

        chain = FailoverProvider([PartialProvider("primary", max_amount=Decimal("1000"))])

        with self.assertRaises(ProviderPartialDeliveryError) as ctx:
            chain.buy_airtime("mtn", "08012345678", Decimal("2000"), "REF-1")

        self.assertEqual(ctx.exception.delivered_amount, Decimal("1000"))

    def test_balance_sums_every_provider(self):
        chain = FailoverProvider([FakeProvider("primary"), FakeProvider("backup")])
        self.assertEqual(chain.get_balance(), Decimal("200"))

    def test_balance_ignores_a_failing_provider(self):
        primary = FakeProvider("primary")
        backup = FakeProvider("backup", error=ProviderTransientError("down"))
        chain = FailoverProvider([primary, backup])
        self.assertEqual(chain.get_balance(), Decimal("100"))


class ProviderChainFactoryTests(SimpleTestCase):
    @patch("apps.vtu.providers.settings")
    def test_single_provider_is_returned_directly(self, settings):
        settings.VTU_PROVIDER_ORDER = "gsubz"
        settings.VTU_PROVIDER = "gsubz"
        settings.GSUBZ_API_KEY = "ap_test"

        from apps.vtu.providers import get_provider

        provider = get_provider()
        self.assertEqual(provider.name, "gsubz")

    @patch("apps.vtu.providers.settings")
    def test_multiple_providers_build_a_failover_chain(self, settings):
        settings.VTU_PROVIDER_ORDER = "gsubz,dancity"
        settings.VTU_PROVIDER = "gsubz"
        settings.GSUBZ_API_KEY = "ap_test"
        settings.DANCITY_API_KEY = "dcy_test"

        from apps.vtu.providers import get_provider
        from apps.vtu.providers.failover import FailoverProvider

        provider = get_provider()
        self.assertIsInstance(provider, FailoverProvider)
        self.assertEqual([p.name for p in provider.providers], ["gsubz", "dancity"])

    @patch("apps.vtu.providers.settings")
    def test_provider_label_lists_the_chain(self, settings):
        settings.VTU_PROVIDER_ORDER = "gsubz,dancity"
        settings.VTU_PROVIDER = "gsubz"

        from apps.vtu.providers import provider_label

        self.assertEqual(provider_label(), "Gsubz + Dancity")


class PlanMatchingTests(SimpleTestCase):
    def test_sizes_are_normalized_before_matching(self):
        from apps.vtu.providers.base import normalize_size

        self.assertEqual(normalize_size("10GB"), "10GB")
        self.assertEqual(normalize_size("10 GB"), "10GB")
        self.assertEqual(normalize_size("1.5GB"), "1.5GB")
        self.assertEqual(normalize_size("2.0GB"), "2GB")

    def test_validity_is_normalized_before_matching(self):
        from apps.vtu.providers.base import normalize_validity

        self.assertEqual(normalize_validity("30"), "30")
        self.assertEqual(normalize_validity("30days"), "30")
        self.assertEqual(normalize_validity("30 days"), "30")

    def test_plan_key_ignores_the_difference_between_catalogues(self):
        from apps.vtu.providers.base import plan_match_key

        gsubz = plan_match_key("mtn", "SME", "10GB", "30")
        dancity = plan_match_key("mtn", "SME", "10 GB", "30days")
        self.assertEqual(gsubz, dancity)

    def test_different_bundles_do_not_match(self):
        from apps.vtu.providers.base import plan_match_key

        self.assertNotEqual(
            plan_match_key("mtn", "SME", "10GB", "30"),
            plan_match_key("mtn", "SME", "5GB", "30"),
        )


class CrossProviderPlanLookupTests(TestCase):
    def test_provider_plan_ids_map_each_provider_to_its_own_plan_id(self):
        from apps.vtu.models import VTUPlan

        plan = VTUPlan.objects.create(
            plan_id="mtn_sme:260",
            provider_product="mtn_sme",
            network="mtn",
            plan_type="SME",
            name="10GB - 30days",
            provider_price=Decimal("2284.56"),
            subhero_price=Decimal("2400"),
            provider_plan_ids={"gsubz": "mtn_sme:260", "dancity": "abc123"},
        )

        chain = FailoverProvider([
            FakeProvider("gsubz", error=ProviderDeclinedError("out of stock")),
            FakeProvider("dancity", result=success()),
        ])

        chain.buy_data(plan.plan_id, "08012345678", "REF-1")

        gsubz_call = chain.providers[0].calls[0][1][0]
        dancity_call = chain.providers[1].calls[0][1][0]
        self.assertEqual(gsubz_call, "mtn_sme:260")
        self.assertEqual(dancity_call, "abc123")
