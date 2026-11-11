from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.smm.tier_info import NOT_SPECIFIED, TIER_INFO, parse_service_facts


def svc(desc="", mn=100, mx=10000):
    return SimpleNamespace(description=desc, provider_min=mn, provider_max=mx)


class ParseServiceFactsTests(SimpleTestCase):
    def test_empty_description_is_not_specified(self):
        f = parse_service_facts(svc(""))
        self.assertEqual(f["refill"], NOT_SPECIFIED)
        self.assertEqual(f["start_time"], NOT_SPECIFIED)
        self.assertEqual(f["speed"], NOT_SPECIFIED)
        self.assertEqual(f["min"], "100")
        self.assertEqual(f["max"], "10,000")

    def test_refill_days(self):
        self.assertEqual(parse_service_facts(svc("Refill: 30 days"))["refill"], "30 days")
        self.assertEqual(parse_service_facts(svc("30 Days Refill"))["refill"], "30 days")

    def test_no_refill(self):
        self.assertEqual(parse_service_facts(svc("No Refill"))["refill"], "No refill")

    def test_start_time(self):
        self.assertEqual(parse_service_facts(svc("Start Time: 0-1 hours"))["start_time"], "0–1 hours")
        self.assertEqual(parse_service_facts(svc("Start: Instant"))["start_time"], "Instant")

    def test_speed(self):
        self.assertEqual(parse_service_facts(svc("Speed: 10K/day"))["speed"], "10K/day")

    def test_no_raw_text_or_supplier_leak(self):
        f = parse_service_facts(svc("Supplier ACME Ltd http://acme.example 100% guaranteed"))
        blob = " ".join(f.values()).lower()
        for bad in ("acme", "http", "guarantee", "100%"):
            self.assertNotIn(bad, blob)


class TierCopyTests(SimpleTestCase):
    def test_no_overclaiming_words(self):
        text = " ".join(str(v) for t in TIER_INFO.values() for v in t.values()).lower()
        for bad in ("guarantee", "100%", "non-drop", "real people"):
            self.assertNotIn(bad, text)
