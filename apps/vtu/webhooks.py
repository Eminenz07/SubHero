"""
Dancity webhook receiver.

Dancity POSTs transaction events to this endpoint. Requests are authenticated
with an HMAC-SHA256 signature over the raw request body, sent in the
``X-Dancity-Signature`` header.
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "HTTP_X_DANCITY_SIGNATURE"


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Timing-safe comparison of the HMAC-SHA256 signature over the raw body."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
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
