from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
from apps.core.utils import send_email_otp, verify_otp

User = get_user_model()


class OTPVerificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.filter(phone_number="+2348011223344").delete()
        User.objects.filter(email="testuser@example.com").delete()
        self.user = User.objects.create_user(
            phone_number="+2348011223344",
            email="TestUser@Example.Com",
            password="TestPassword123!",
            full_name="Test User",
            is_verified=False,
        )

    def tearDown(self):
        User.objects.filter(phone_number="+2348011223344").delete()
        User.objects.filter(email="testuser@example.com").delete()

    def test_verify_otp_with_cache(self):
        otp = send_email_otp(self.user)
        self.assertTrue(verify_otp("testuser@example.com", otp))
        # Verify single-use consumption
        self.assertFalse(verify_otp("testuser@example.com", otp))

    def test_verify_otp_with_session_fallback(self):
        session = {}
        otp = send_email_otp(self.user, session=session)
        # Clear cache to simulate cache wipe or different worker
        cache.delete(f"otp:{self.user.email.lower()}")
        self.assertIsNone(cache.get(f"otp:{self.user.email.lower()}"))
        # Verify using session fallback
        self.assertTrue(verify_otp(self.user.email, otp, session=session))
        # Session hash should now be cleared
        self.assertNotIn("otp_hash", session)

    def test_verify_view_and_double_submit_resilience(self):
        session = self.client.session
        session["otp_user_id"] = str(self.user.id)
        session["otp_phone"] = self.user.phone_number
        session["otp_email"] = self.user.email.lower()
        session["otp_purpose"] = "registration"
        otp = send_email_otp(self.user, purpose="registration", session=session)
        session.save()

        # First submit
        res1 = self.client.post("/auth/verify/", {"otp_code": otp})
        self.assertEqual(res1.status_code, 302)
        self.assertEqual(res1.url, "/auth/set-pin/")

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)

        # Second submit (simulating double click or rapid multi-submit)
        res2 = self.client.post("/auth/verify/", {"otp_code": otp})
        self.assertEqual(res2.status_code, 302)
        # Should not crash with "Invalid or expired code" error
        self.assertIn(res2.url, ["/auth/set-pin/", "/dashboard/"])
