from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.wallet.models import Wallet


class AdminDashboardWalletBalanceTests(TestCase):
    def test_dashboard_includes_total_customer_wallet_balance(self):
        User = get_user_model()

        admin = User.objects.create_user(
            phone_number="+2348000000001",
            email="admin@example.com",
            password="StrongPass123",
            full_name="Admin User",
            is_staff=True,
        )
        customer_a = User.objects.create_user(
            phone_number="+2348000000002",
            email="customer1@example.com",
            password="StrongPass123",
            full_name="Customer One",
        )
        customer_b = User.objects.create_user(
            phone_number="+2348000000003",
            email="customer2@example.com",
            password="StrongPass123",
            full_name="Customer Two",
        )
        staff_wallet_user = User.objects.create_user(
            phone_number="+2348000000004",
            email="staffwallet@example.com",
            password="StrongPass123",
            full_name="Staff Wallet User",
            is_staff=True,
        )

        for user, balance in [
            (admin, Decimal("1000.00")),
            (customer_a, Decimal("250.50")),
            (customer_b, Decimal("150.25")),
            (staff_wallet_user, Decimal("500.00")),
        ]:
            wallet, _ = Wallet.objects.get_or_create(user=user)
            wallet.balance = balance
            wallet.save(update_fields=["balance"])

        admin.set_pin("1234")
        self.client.force_login(admin)
        response = self.client.get(reverse("admin_panel:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_user_balance"], Decimal("400.75"))
        self.assertContains(response, "Customer wallet balances")
