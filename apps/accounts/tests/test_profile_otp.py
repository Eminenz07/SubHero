from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import patch

User = get_user_model()


class TestProfilePasswordChangeOTP(TestCase):
    """Profile password change must be gated behind email OTP verification."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            phone_number="+2349073601300",
            email="otpuser@subhero.com.ng",
            password="OldPass123!",
            full_name="OTP User",
            is_verified=True,
            is_active=True,
        )
        self.client.force_login(self.user)

    @patch("apps.accounts.views.send_email_otp")
    def test_change_password_redirects_to_otp_verify(self, mock_send_otp):
        """Submitting change_password on profile redirects to OTP verification."""
        resp = self.client.post(reverse("accounts:profile"), {
            "action": "change_password",
            "current_password": "OldPass123!",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        mock_send_otp.assert_called_once()
        self.assertRedirects(resp, reverse("accounts:verify_profile_otp"))

    def test_change_password_wrong_current_password(self):
        resp = self.client.post(reverse("accounts:profile"), {
            "action": "change_password",
            "current_password": "WrongPass123!",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Current password is incorrect.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass123!"))

    def test_complete_profile_change_without_otp_blocked(self):
        """complete_profile_change without profile_otp_verified is blocked."""
        session = self.client.session
        session["profile_action"] = "password_change"
        session["profile_new_password"] = "NewPass123!"
        session["profile_otp_verified"] = False
        session.save()

        resp = self.client.post(reverse("accounts:complete_profile_change"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:verify_profile_otp"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass123!"))

    @patch("apps.accounts.views.send_email_otp")
    def test_change_password_flow_applies_after_otp(self, mock_send_otp):
        """Full flow: change_password -> verify OTP -> password applied."""
        self.client.post(reverse("accounts:profile"), {
            "action": "change_password",
            "current_password": "OldPass123!",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        })

        session = self.client.session
        session["profile_otp_verified"] = True
        session.save()

        resp = self.client.post(reverse("accounts:complete_profile_change"), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertRedirects(resp, reverse("accounts:profile"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass123!"))


class TestProfilePinChangeOTP(TestCase):
    """Profile PIN change must be gated behind email OTP verification."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            phone_number="+2349073601301",
            email="otpuser2@subhero.com.ng",
            password="Pass123!",
            full_name="OTP User 2",
            is_verified=True,
            is_active=True,
        )
        self.user.set_pin("1234")
        self.user.save()
        self.client.force_login(self.user)

    @patch("apps.accounts.views.send_email_otp")
    def test_change_pin_redirects_to_otp_verify(self, mock_send_otp):
        """Submitting change_pin on profile redirects to OTP verification."""
        resp = self.client.post(reverse("accounts:profile"), {
            "action": "change_pin",
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        mock_send_otp.assert_called_once()
        self.assertRedirects(resp, reverse("accounts:verify_profile_otp"))

    def test_change_pin_wrong_current_pin(self):
        resp = self.client.post(reverse("accounts:profile"), {
            "action": "change_pin",
            "current_pin": "0000",
            "new_pin": "5678",
            "confirm_pin": "5678",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Current transaction PIN is incorrect.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_pin("1234"))

    @patch("apps.accounts.views.send_email_otp")
    def test_change_pin_flow_applies_after_otp(self, mock_send_otp):
        """Full flow: change_pin -> verify OTP -> PIN applied."""
        self.client.post(reverse("accounts:profile"), {
            "action": "change_pin",
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "5678",
        })

        session = self.client.session
        session["profile_otp_verified"] = True
        session.save()

        resp = self.client.post(reverse("accounts:complete_profile_change"), follow=True)
        self.assertEqual(resp.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_pin("5678"))


class TestVerifyProfileOTPView(TestCase):
    """VerifyProfileOTPView requires a pending profile action in session."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            phone_number="+2349073601302",
            email="otpuser3@subhero.com.ng",
            password="Pass123!",
            full_name="OTP User 3",
            is_verified=True,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_no_pending_action_redirects(self):
        """GET verify_profile_otp with no pending action redirects to profile."""
        resp = self.client.get(reverse("accounts:verify_profile_otp"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:profile"))
