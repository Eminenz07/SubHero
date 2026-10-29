"""
Meta Pixel Conversions API Service
===================================
Server-side event tracking for Meta Pixel to ensure events are captured
even when client-side pixel is blocked by ad blockers.

Uses Meta Conversions API:
https://developers.facebook.com/docs/marketing-api/conversions-api
"""

import hashlib
import json
import logging
import time
from decimal import Decimal
from typing import Optional, Dict, Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class MetaConversionsAPI:
    """
    Client for Meta Conversions API.
    Sends server-side events to Meta for attribution and optimization.
    """

    API_VERSION = "v19.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

    def __init__(self):
        self.pixel_id = getattr(settings, "META_PIXEL_ID", "")
        self.access_token = getattr(settings, "META_CONVERSIONS_API_TOKEN", "")
        self.test_event_code = getattr(settings, "META_TEST_EVENT_CODE", "")

        if not self.pixel_id or not self.access_token:
            logger.warning("Meta Conversions API not fully configured (META_PIXEL_ID and/or META_CONVERSIONS_API_TOKEN missing)")

    def _hash_pii(self, value: str) -> str:
        """Hash PII using SHA256 as required by Meta."""
        if not value:
            return ""
        return hashlib.sha256(value.lower().strip().encode()).hexdigest()

    def _build_user_data(self, user, request=None) -> Dict[str, Any]:
        """Build user_data object for Conversions API."""
        user_data = {
            "external_id": self._hash_pii(str(user.id)),
        }

        if user.email:
            user_data["em"] = [self._hash_pii(user.email)]

        if user.phone_number:
            user_data["ph"] = [self._hash_pii(user.phone_number)]

        # Hash full name if available
        if user.full_name:
            name_parts = user.full_name.strip().split()
            if name_parts:
                user_data["fn"] = [self._hash_pii(name_parts[0])]
                if len(name_parts) > 1:
                    user_data["ln"] = [self._hash_pii(" ".join(name_parts[1:]))]

        # Add IP address for better matching
        if request:
            cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
            x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            client_ip = cf_ip or (x_forwarded.split(",")[0].strip() if x_forwarded else request.META.get("REMOTE_ADDR"))
            if client_ip and client_ip != "Unknown":
                user_data["client_ip_address"] = client_ip

        return user_data

    def _build_custom_data(self, event_name: str, **kwargs) -> Dict[str, Any]:
        """Build custom_data object based on event type."""
        custom_data = {}

        if event_name == "Purchase":
            custom_data = {
                "value": float(kwargs.get("value", 0)),
                "currency": kwargs.get("currency", "NGN"),
                "order_id": kwargs.get("transaction_ref", ""),
            }
        elif event_name == "Lead":
            custom_data = {
                "content_name": "Giveaway Creation",
                "content_category": "Giveaway",
                "content_ids": [kwargs.get("giveaway_id", "")],
                "content_type": "giveaway",
            }
        elif event_name == "CompleteRegistration":
            custom_data = {
                "registration_method": kwargs.get("method", "email"),
            }
        elif event_name == "InitiateCheckout":
            custom_data = {
                "value": float(kwargs.get("value", 0)),
                "currency": kwargs.get("currency", "NGN"),
            }

        return custom_data

    def send_event(
        self,
        event_name: str,
        user,
        request=None,
        event_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Send an event to Meta Conversions API.
        
        Args:
            event_name: Standard Meta event name (Purchase, Lead, CompleteRegistration, etc.)
            user: Django User object
            request: Django request object (for IP address)
            event_id: Optional unique event ID for deduplication
            **kwargs: Event-specific parameters
            
        Returns:
            bool: True if event was sent successfully
        """
        if not self.pixel_id or not self.access_token:
            logger.debug("Meta Conversions API not configured, skipping event: %s", event_name)
            return False

        url = f"{self.BASE_URL}/{self.pixel_id}/events"
        
        # Generate event_id for deduplication if not provided
        if not event_id:
            event_id = hashlib.sha256(f"{event_name}{user.id}{time.time()}".encode()).hexdigest()[:16]

        # Build user data
        user_data = self._build_user_data(user, request)
        
        # Build custom data
        custom_data = self._build_custom_data(event_name, **kwargs)

        # Build event payload
        payload = {
            "data": [{
                "event_name": event_name,
                "event_time": int(time.time()),
                "event_id": event_id,
                "user_data": user_data,
                "custom_data": custom_data,
                "event_source_url": request.build_absolute_uri() if request else getattr(settings, "SITE_URL", ""),
                "action_source": "website",
            }]
        }

        if self.test_event_code:
            payload["test_event_code"] = self.test_event_code

        headers = {
            "Content-Type": "application/json",
        }

        params = {
            "access_token": self.access_token,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("events_received", 0) > 0:
                    logger.info("Meta Conversions API: Event '%s' sent successfully for user %s", event_name, user.id)
                    return True
                else:
                    logger.warning("Meta Conversions API: Event acknowledged but not received: %s", result)
                    return False
            else:
                logger.error("Meta Conversions API error: %s - %s", response.status_code, response.text)
                return False

        except requests.RequestException as e:
            logger.error("Meta Conversions API request failed: %s", str(e))
            return False
        except Exception as e:
            logger.exception("Unexpected error sending Meta Conversions API event: %s", str(e))
            return False


# Singleton instance
_meta_conversions_api = None


def get_meta_conversions_api() -> MetaConversionsAPI:
    """Get singleton instance of Meta Conversions API client."""
    global _meta_conversions_api
    if _meta_conversions_api is None:
        _meta_conversions_api = MetaConversionsAPI()
    return _meta_conversions_api


# Convenience functions for common events
def track_purchase(user, value: float, currency: str = "NGN", transaction_ref: str = "", request=None) -> bool:
    """Track Purchase event via Conversions API."""
    api = get_meta_conversions_api()
    return api.send_event("Purchase", user, request=request, value=value, currency=currency, transaction_ref=transaction_ref)


def track_lead(user, giveaway_id: str = "", giveaway_type: str = "", request=None) -> bool:
    """Track Lead event via Conversions API."""
    api = get_meta_conversions_api()
    return api.send_event("Lead", user, request=request, giveaway_id=giveaway_id, giveaway_type=giveaway_type)


def track_complete_registration(user, method: str = "email", request=None) -> bool:
    """Track CompleteRegistration event via Conversions API."""
    api = get_meta_conversions_api()
    return api.send_event("CompleteRegistration", user, request=request, method=method)


def track_initiate_checkout(user, value: float = 0, currency: str = "NGN", funding_method: str = "", request=None) -> bool:
    """Track InitiateCheckout event via Conversions API."""
    api = get_meta_conversions_api()
    return api.send_event("InitiateCheckout", user, request=request, value=value, currency=currency, funding_method=funding_method)