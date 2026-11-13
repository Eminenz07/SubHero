"""
Tests for apps.core.utils.is_safe_return_to — open-redirect guard.
"""
from django.test import SimpleTestCase

from apps.core.utils import is_safe_return_to


class IsSafeReturnToTests(SimpleTestCase):
    HOST = "testserver"

    def test_relative_path_is_safe(self):
        self.assertTrue(is_safe_return_to("/smm/?platform=instagram&tier=premium", self.HOST))
        self.assertTrue(is_safe_return_to("/dashboard/", self.HOST))
        self.assertTrue(is_safe_return_to("/", self.HOST))

    def test_empty_or_none_url_is_unsafe(self):
        self.assertFalse(is_safe_return_to("", self.HOST))
        self.assertFalse(is_safe_return_to(None, self.HOST))

    def test_protocol_relative_url_is_unsafe(self):
        self.assertFalse(is_safe_return_to("//evil.com", self.HOST))
        self.assertFalse(is_safe_return_to("//evil.com/smm/", self.HOST))

    def test_absolute_url_different_host_is_unsafe(self):
        self.assertFalse(is_safe_return_to("https://evil.com", self.HOST))
        self.assertFalse(is_safe_return_to("https://evil.com/smm/", self.HOST))
        self.assertFalse(is_safe_return_to("http://evil.com", self.HOST))

    def test_javascript_scheme_is_unsafe(self):
        self.assertFalse(is_safe_return_to("javascript:alert(1)", self.HOST))
        self.assertFalse(is_safe_return_to("JaVaScRiPt:alert(1)", self.HOST))

    def test_data_scheme_is_unsafe(self):
        self.assertFalse(is_safe_return_to("data:text/html,<script>alert(1)</script>", self.HOST))
