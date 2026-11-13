"""
Tests for SMM order cancellation (user-initiated cancel + refund).
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from django.contrib.auth import get_user_model
from apps.wallet.models import Wallet, WalletTransaction
from apps.smm.models import SMMOrder, SMMService


class SMMOrderCancelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            phone_number="08012345678",
            email="cancel_tester@example.com",
            password="testpass123",
        )
        self.user.set_pin("1234")
        self.client.force_login(self.user)

        self.service = SMMService.objects.create(
            provider_service_id="1001",
            name="Instagram Followers",
            category="instagram",
            subcategory="Instagram Followers",
            provider_min=100,
            provider_max=10000,
            provider_rate=Decimal("0.80"),
            subhero_price_per_1k=Decimal("800.00"),
            tier="premium",
            is_active=True,
        )

        self.wallet = Wallet.objects.get(user=self.user)
        self.wallet.balance = Decimal("4200.00")
        self.wallet.save(update_fields=["balance"])

        self.order = SMMOrder.objects.create(
            user=self.user,
            service=self.service,
            target_url="https://instagram.com/user",
            quantity=1000,
            amount=Decimal("800.00"),
            api_cost=Decimal("400.00"),
            reference="SMM-CANCEL-001",
            provider_order_id="GATEWAY-123",
            status=SMMOrder.Status.PENDING,
        )

        # Debit txn for the order
        self.txn = WalletTransaction.objects.create(
            wallet=self.wallet,
            txn_type=WalletTransaction.TxnType.SMM,
            amount=Decimal("800.00"),
            balance_before=Decimal("5000.00"),
            balance_after=Decimal("4200.00"),
            reference="SMM-CANCEL-001",
            status=WalletTransaction.Status.SUCCESS,
            description="SMM order placed",
        )

    def _cancel_url(self):
        return reverse("smm:order_cancel", kwargs={"order_id": self.order.id})

    def test_cancel_pending_order_full_refund(self):
        """PENDING order: full local refund, status -> CANCELLED."""
        balance_before = self.wallet.balance
        response = self.client.post(self._cancel_url())
        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SMMOrder.Status.CANCELLED)
        self.assertEqual(self.order.cancelled_by, "user")

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, balance_before + Decimal("800.00"))

        refund_txn = WalletTransaction.objects.filter(
            reference="CANCEL-SMM-CANCEL-001", txn_type=WalletTransaction.TxnType.REFUND
        ).first()
        self.assertIsNotNone(refund_txn)
        self.assertEqual(refund_txn.amount, Decimal("800.00"))
        self.assertEqual(refund_txn.status, WalletTransaction.Status.SUCCESS)

    def test_cancel_processing_order_with_provider_cancel(self):
        """PROCESSING order: provider cancel accepted -> full refund."""
        self.order.status = SMMOrder.Status.PROCESSING
        self.order.save(update_fields=["status"])

        with patch("apps.smm.tasks.cancel_smm_order_with_provider") as mock_cancel:
            mock_cancel.return_value = {"cancelled": True, "remains": 0, "start_count": 0}
            response = self.client.post(self._cancel_url())
            self.assertEqual(response.status_code, 200)
            mock_cancel.assert_called_once_with("GATEWAY-123")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SMMOrder.Status.CANCELLED)
        self.assertEqual(self.order.cancelled_by, "user")

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("5000.00"))  # full refund back

    def test_cancel_processing_order_partial_delivery_refund_undelivered(self):
        """PROCESSING order with remains: refund undelivered portion proportionally."""
        self.order.status = SMMOrder.Status.PROCESSING
        self.order.quantity = 1000
        self.order.remains = 400  # 400 undelivered
        self.order.save(update_fields=["status", "remains"])

        with patch("apps.smm.tasks.cancel_smm_order_with_provider") as mock_cancel:
            mock_cancel.return_value = {"cancelled": True, "remains": 400, "start_count": 600}
            response = self.client.post(self._cancel_url())
            self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SMMOrder.Status.PARTIAL)

        # 400/1000 * 800 = ₦320 refund; balance starts at 4200
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("4520.00"))

    def test_cancel_already_delivered_order_rejected(self):
        """SUCCESS order: cannot cancel."""
        self.order.status = SMMOrder.Status.SUCCESS
        self.order.save(update_fields=["status"])

        response = self.client.post(self._cancel_url())
        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SMMOrder.Status.SUCCESS)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("4200.00"))  # no refund

    def test_cancel_double_cancel_idempotent(self):
        """Cancelling an already-cancelled order returns success, no double refund."""
        self.order.status = SMMOrder.Status.CANCELLED
        self.order.save(update_fields=["status"])

        balance_before = self.wallet.balance
        response = self.client.post(self._cancel_url())
        self.assertEqual(response.status_code, 200)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, balance_before)  # no double refund

    def test_cancel_gateway_rejected_cannot_cancel(self):
        """Gateway rejects cancel -> order stays PROCESSING, no refund."""
        self.order.status = SMMOrder.Status.PROCESSING
        self.order.save(update_fields=["status"])

        with patch("apps.smm.tasks.cancel_smm_order_with_provider") as mock_cancel:
            mock_cancel.return_value = {
                "cancelled": False,
                "error": "Order already in delivery",
            }
            response = self.client.post(self._cancel_url())
            self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SMMOrder.Status.PROCESSING)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("4200.00"))  # no refund
