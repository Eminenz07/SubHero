"""Tests for the GSUBZ webhook endpoint."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.vtu.models import AirtimeOrder, VTUOrder
from apps.wallet.models import Wallet

SECRET = "gsubz_signing_secret"


def sign(body: bytes, timestamp: str, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()


@override_settings(GSUBZ_WEBHOOK_SECRET=SECRET, SECURE_SSL_REDIRECT=False)
class GsubzWebhookViewTests(TestCase):
    def setUp(self):
        self.url = reverse("vtu:gsubz_webhook")
        self.user = self._make_user()
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        wallet.balance = 1000
        wallet.save(update_fields=["balance"])

        # The endpoint hands the event to the queue; run it inline so the test
        # does not need a broker.
        from apps.vtu import tasks as vtu_tasks

        real_task = vtu_tasks.reconcile_gsubz_event
        queued = []

        class InlineTask:
            @staticmethod
            def delay(event, payload):
                queued.append((event, payload))
                return real_task(event, payload)

            @staticmethod
            def __call__(event, payload):
                return real_task(event, payload)

        self.queued = queued
        patcher = patch("apps.vtu.tasks.reconcile_gsubz_event", InlineTask)
        patcher.start()
        self.addCleanup(patcher.stop)

        sms_patcher = patch("apps.vtu.tasks.send_transaction_sms")
        sms_patcher.start()
        self.addCleanup(sms_patcher.stop)

    def _make_user(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(
            phone_number="08012345678",
            email="gsubz_webhook@example.com",
            password="testpass123",
        )

    def _post(self, payload, timestamp=None, secret=SECRET):
        raw = json.dumps(payload).encode()
        timestamp = timestamp or str(int(time.time()))
        return self.client.post(
            self.url,
            data=raw,
            content_type="application/json",
            HTTP_X_GSUBZ_SIGNATURE=sign(raw, timestamp, secret),
            HTTP_X_GSUBZ_TIMESTAMP=timestamp,
            HTTP_X_GSUBZ_EVENT=payload.get("event", ""),
        )

    def test_unsigned_request_is_rejected(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"event": "transaction.updated"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_signature_is_rejected(self):
        raw = json.dumps({"event": "transaction.updated"}).encode()
        response = self.client.post(
            self.url,
            data=raw,
            content_type="application/json",
            HTTP_X_GSUBZ_SIGNATURE="sha256=deadbeef",
            HTTP_X_GSUBZ_TIMESTAMP=str(int(time.time())),
        )
        self.assertEqual(response.status_code, 401)

    def test_a_valid_event_is_accepted(self):
        payload = {
            "event": "transaction.updated",
            "eventId": "evt_1",
            "data": {
                "change": {"type": "COMPLETED"},
                "transaction": {
                    "transactionID": 3878886201,
                    "requestID": "VTU-UNKNOWN",
                    "status": "successful",
                },
            },
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)

    def test_a_successful_event_marks_the_order_successful(self):
        order = VTUOrder.objects.create(
            user=self.user,
            plan_id="mtn_sme:179",
            plan_name="500MB - 7days",
            recipient="08012345678",
            network="mtn",
            amount=300,
            api_cost=285,
            reference="VTU-REF-1",
            status=VTUOrder.Status.PROCESSING,
        )
        payload = {
            "event": "transaction.updated",
            "eventId": "evt_2",
            "data": {
                "change": {"type": "COMPLETED"},
                "transaction": {
                    "transactionID": 3878886201,
                    "requestID": "VTU-REF-1",
                    "status": "successful",
                },
            },
        }
        response = self._post(payload)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, VTUOrder.Status.SUCCESS)
        self.assertEqual(order.provider_ref, "3878886201")

    def test_a_failed_event_refunds_the_order(self):
        order = AirtimeOrder.objects.create(
            user=self.user,
            network="mtn",
            recipient="08012345678",
            amount=500,
            api_cost=490,
            reference="AIR-REF-1",
            status=AirtimeOrder.Status.PROCESSING,
        )
        payload = {
            "event": "transaction.updated",
            "eventId": "evt_3",
            "data": {
                "change": {"type": "COMPLETED"},
                "transaction": {
                    "transactionID": 3768661863,
                    "requestID": "AIR-REF-1",
                    "status": "failed",
                    "description": "TRANSACTION_FAILED",
                },
            },
        }
        response = self._post(payload)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, AirtimeOrder.Status.FAILED)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, 1500)

    def test_a_refunded_event_refunds_an_already_successful_order(self):
        order = VTUOrder.objects.create(
            user=self.user,
            plan_id="mtn_sme:179",
            plan_name="500MB - 7days",
            recipient="08012345678",
            network="mtn",
            amount=300,
            api_cost=285,
            reference="VTU-REF-2",
            status=VTUOrder.Status.SUCCESS,
        )
        payload = {
            "event": "transaction.updated",
            "eventId": "evt_4",
            "data": {
                "change": {"type": "REFUNDED", "reason": "ADMIN", "refundNgn": 285},
                "transaction": {
                    "transactionID": 3878886201,
                    "requestID": "VTU-REF-2",
                    "status": "failed",
                    "description": "TRANSACTION_REVERSED",
                },
            },
        }
        response = self._post(payload)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, VTUOrder.Status.FAILED)

    def test_the_endpoint_ignores_other_events(self):
        payload = {
            "event": "webhook.test",
            "eventId": "evt_5",
            "data": {"change": {"type": "COMPLETED"}},
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)

    @override_settings(GSUBZ_WEBHOOK_SECRET="")
    def test_an_unconfigured_endpoint_refuses_the_event(self):
        payload = {"event": "transaction.updated", "data": {}}
        raw = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        response = self.client.post(
            self.url,
            data=raw,
            content_type="application/json",
            HTTP_X_GSUBZ_SIGNATURE=sign(raw, timestamp),
            HTTP_X_GSUBZ_TIMESTAMP=timestamp,
        )
        self.assertEqual(response.status_code, 503)
