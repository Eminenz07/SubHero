"""
Provider webhook receivers.

Dancity POSTs transaction events to this endpoint. Requests are authenticated
with an HMAC-SHA256 signature over the raw request body, sent in the
``X-Dancity-Signature`` header.

GSUBZ POSTs transaction events to its own endpoint. The signature is
``sha256=`` followed by the HMAC-SHA256 of ``timestamp + "." + raw body``,
sent in the ``X-Gsubz-Signature`` header.
"""

import hashlib
import hmac
import json
import logging
import time

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "HTTP_X_DANCITY_SIGNATURE"
GSUBZ_SIGNATURE_HEADER = "HTTP_X_GSUBZ_SIGNATURE"
GSUBZ_TIMESTAMP_HEADER = "HTTP_X_GSUBZ_TIMESTAMP"
GSUBZ_EVENT_HEADER = "HTTP_X_GSUBZ_EVENT"
GSUBZ_MAX_TIMESTAMP_SKEW_SECONDS = 300


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Timing-safe comparison of the HMAC-SHA256 signature over the raw body."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_gsubz_signature(raw_body: bytes, signature: str, timestamp: str, secret: str) -> bool:
    """Timing-safe check of the GSUBZ signature over ``timestamp + "." + body``."""
    if not signature or not secret or not timestamp:
        return False

    try:
        sent_at = int(float(timestamp))
    except (TypeError, ValueError):
        return False

    if abs(int(time.time()) - sent_at) > GSUBZ_MAX_TIMESTAMP_SKEW_SECONDS:
        return False

    if not signature.startswith("sha256="):
        return False

    payload = f"{timestamp}.".encode() + raw_body
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@method_decorator(csrf_exempt, name="dispatch")
class DancityWebhookView(View):
    """Receives Dancity transaction events and reconciles matching orders."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        raw_body = request.body
        signature = request.META.get(SIGNATURE_HEADER, "")
        secret = getattr(settings, "DANCITY_WEBHOOK_SECRET", "")

        if not secret:
            logger.error("DANCITY_WEBHOOK_SECRET is not configured. Rejecting webhook.")
            return JsonResponse({"status": "error", "message": "Webhook not configured"}, status=503)

        if not verify_signature(raw_body, signature, secret):
            logger.warning("Rejected Dancity webhook with invalid signature.")
            return JsonResponse({"status": "error", "message": "Invalid signature"}, status=401)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Rejected Dancity webhook with unparsable body.")
            return JsonResponse({"status": "error", "message": "Invalid payload"}, status=400)

        event = payload.get("event", "")
        data = payload.get("data") or {}

        logger.info(
            "Dancity webhook received: event=%s reference=%s status=%s",
            event, data.get("reference"), data.get("status"),
        )

        try:
            from apps.vtu.tasks import reconcile_dancity_event

            reconcile_dancity_event(event, data)
        except Exception as exc:
            logger.exception("Dancity webhook reconciliation failed: %s", exc)
            return JsonResponse({"status": "error", "message": "Reconciliation failed"}, status=500)

        return JsonResponse({"status": "ok"})


@method_decorator(csrf_exempt, name="dispatch")
class GsubzWebhookView(View):
    """Receives GSUBZ transaction events and reconciles matching orders."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        raw_body = request.body
        signature = request.META.get(GSUBZ_SIGNATURE_HEADER, "")
        timestamp = request.META.get(GSUBZ_TIMESTAMP_HEADER, "")
        secret = getattr(settings, "GSUBZ_WEBHOOK_SECRET", "")

        if not secret:
            logger.error("GSUBZ_WEBHOOK_SECRET is not configured. Rejecting webhook.")
            return JsonResponse({"status": "error", "message": "Webhook not configured"}, status=503)

        if not verify_gsubz_signature(raw_body, signature, timestamp, secret):
            logger.warning("Rejected GSUBZ webhook with invalid signature.")
            return JsonResponse({"status": "error", "message": "Invalid signature"}, status=401)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Rejected GSUBZ webhook with unparsable body.")
            return JsonResponse({"status": "error", "message": "Invalid payload"}, status=400)

        event = payload.get("event") or request.META.get(GSUBZ_EVENT_HEADER, "")
        event_id = payload.get("eventId") or request.META.get("HTTP_X_GSUBZ_DELIVERY", "")
        transaction = (payload.get("data") or {}).get("transaction") or {}

        logger.info(
            "GSUBZ webhook received: event=%s id=%s reference=%s status=%s",
            event, event_id, transaction.get("requestID"), transaction.get("status"),
        )

        try:
            from apps.vtu.tasks import reconcile_gsubz_event

            # GSUBZ expects a 2xx within 10 seconds, so the slow work is
            # handed to the queue. If the queue is unreachable the event is
            # processed inline so it is never lost.
            try:
                reconcile_gsubz_event.delay(event, payload)
            except Exception as queue_exc:
                logger.warning(
                    "Could not queue the GSUBZ reconciliation, handling it inline: %s",
                    queue_exc,
                )
                reconcile_gsubz_event(event, payload)
        except Exception as exc:
            logger.exception("GSUBZ webhook reconciliation failed: %s", exc)
            return JsonResponse({"status": "error", "message": "Reconciliation failed"}, status=500)

        return JsonResponse({"status": "ok"})