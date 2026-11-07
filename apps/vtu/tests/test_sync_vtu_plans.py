"""Tests for the multi-provider plan synchronisation."""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.vtu.models import VTUPlan
from apps.vtu.providers.base import DataPlan


class FakeSyncProvider:
    """A provider that returns a canned catalogue."""

    def __init__(self, name, plans):
        self.name = name
        self._plans = plans

    def list_data_plans(self):
        return self._plans


def gsubz_plan(value, display, price):
    return DataPlan(
        plan_id=f"mtn_sme:{value}",
        name=display,
        provider_product="mtn_sme",
        price=Decimal(price),
        validity=display.split("-")[-1].strip().replace("days", ""),
        size=display.split("-")[0].strip(),
    )


def dancity_plan(plan_id, size, validity, price):
    return DataPlan(
        plan_id=plan_id,
        name=f"MTN SME {size}",
        provider_product="MTN SME",
        price=Decimal(price),
        validity=validity,
        size=size,
    )


class SyncVtuPlansTests(TestCase):
    def _chain(self, gsubz_plans, dancity_plans):
        return [
            FakeSyncProvider("gsubz", gsubz_plans),
            FakeSyncProvider("dancity", dancity_plans),
        ]

    def test_plans_are_stored_with_the_primary_providers_id(self):
        chain = self._chain(
            [gsubz_plan("179", "500MB - 7days", "285.20")],
            [],
        )
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        plan = VTUPlan.objects.get()
        self.assertEqual(plan.plan_id, "mtn_sme:179")
        self.assertEqual(plan.network, "mtn")
        self.assertEqual(plan.plan_type, "SME")
        self.assertEqual(plan.provider_price, Decimal("285.20"))
        self.assertEqual(plan.validity, "7")
        self.assertTrue(plan.is_active)

    def test_matching_plans_from_the_fallback_provider_are_cross_mapped(self):
        chain = self._chain(
            [gsubz_plan("179", "500MB - 7days", "285.20")],
            [dancity_plan("abc123", "500MB", "7", "300")],
        )
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        plan = VTUPlan.objects.get()
        self.assertEqual(plan.provider_plan_ids, {"gsubz": "mtn_sme:179", "dancity": "abc123"})

    def test_a_different_bundle_is_not_cross_mapped(self):
        chain = self._chain(
            [gsubz_plan("179", "500MB - 7days", "285.20")],
            [dancity_plan("other", "5GB", "30", "1800")],
        )
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        plan = VTUPlan.objects.get()
        self.assertEqual(plan.provider_plan_ids, {"gsubz": "mtn_sme:179"})

    def test_only_the_primary_catalogue_is_sold(self):
        chain = self._chain(
            [gsubz_plan("179", "500MB - 7days", "285.20")],
            [dancity_plan("abc123", "500MB", "7", "300")],
        )
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        self.assertEqual(VTUPlan.objects.count(), 1)
        self.assertEqual(VTUPlan.objects.get().plan_id, "mtn_sme:179")

    def test_plans_that_left_the_catalogue_are_deactivated(self):
        stale = VTUPlan.objects.create(
            plan_id="old-plan",
            provider_product="MTN SME",
            network="mtn",
            plan_type="SME",
            name="Old plan",
            provider_price=Decimal("100"),
            subhero_price=Decimal("120"),
            validity="30",
            is_active=True,
        )

        chain = self._chain(
            [gsubz_plan("179", "500MB - 7days", "285.20")],
            [],
        )
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        stale.refresh_from_db()
        self.assertFalse(stale.is_active)

    def test_an_empty_primary_catalogue_keeps_the_existing_plans(self):
        existing = VTUPlan.objects.create(
            plan_id="old-plan",
            provider_product="MTN SME",
            network="mtn",
            plan_type="SME",
            name="Old plan",
            provider_price=Decimal("100"),
            subhero_price=Decimal("120"),
            validity="30",
            is_active=True,
        )

        chain = self._chain([], [])
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        existing.refresh_from_db()
        self.assertTrue(existing.is_active)

    def test_a_failing_fallback_provider_does_not_stop_the_sync(self):
        class BrokenProvider(FakeSyncProvider):
            def list_data_plans(self):
                raise RuntimeError("upstream is down")

        chain = [
            FakeSyncProvider("gsubz", [gsubz_plan("179", "500MB - 7days", "285.20")]),
            BrokenProvider("dancity", []),
        ]
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        plan = VTUPlan.objects.get()
        self.assertEqual(plan.plan_id, "mtn_sme:179")
        self.assertEqual(plan.provider_plan_ids, {"gsubz": "mtn_sme:179"})

    @override_settings(VTU_PROVIDER_ORDER="gsubz,dancity")
    def test_the_configured_chain_is_used(self):
        chain = self._chain(
            [gsubz_plan("179", "500MB - 7days", "285.20")],
            [],
        )
        with patch("apps.vtu.tasks._provider_chain", return_value=chain):
            from apps.vtu.tasks import sync_vtu_plans

            sync_vtu_plans()

        self.assertEqual(VTUPlan.objects.count(), 1)
