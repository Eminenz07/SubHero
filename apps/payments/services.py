"""
Payments — Providus Bank Client
=================================
PRD Section 8: Virtual Account Assignment + Webhook Verification.
Includes real and mock clients, switchable via PROVIDUS_MOCK setting.
"""

import hashlib
import hmac
import logging
import random
import string

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ProvidusClient:
    """
    Real Providus Bank API client for virtual account provisioning.
    PRD Section 8.1: Creates permanent virtual accounts.
    """

    def __init__(self):
        self.api_key = settings.PROVIDUS_API_KEY
        self.secret_key = settings.PROVIDUS_SECRET_KEY
        self.base_url = settings.PROVIDUS_BASE_URL

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "X-Auth-Signature": self.api_key,
            "Client-Id": self.secret_key,
        }

    def create_virtual_account(self, account_name, user_reference):
        """
        Create a dedicated virtual account for a user.
        PRD Section 8.1: Permanent account, same for lifetime.
        """
        payload = {
            "account_name": account_name,
            "bvn": "",  # Not required for SubHero MVP
        }

        try:
            response = requests.post(
                f"{self.base_url}/PiPCreateReservedAccountNumber",
                json=payload,
                headers=self._headers(),
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "Providus virtual account created: name=%s, account=%s",
                    account_name,
                    data.get("account_number"),
                )
                return {
                    "account_number": data.get("account_number", ""),
                    "bank_name": "Providus Bank",
                }
            else:
                logger.error(
                    "Providus create account failed: status=%s, response=%s",
                    response.status_code,
                    response.text,
                )
                raise Exception(f"Providus API error: {response.status_code}")

        except requests.RequestException as e:
            logger.error("Providus API connection error: %s", str(e))
            raise


class MockProvidusClient:
    """
    Mock Providus client for development.
    Generates fake but realistic-looking account numbers.
    """

    def create_virtual_account(self, account_name, user_reference):
        """Generate a fake Providus virtual account number."""
        # Generate a 10-digit number starting with 9900 (Providus prefix)
        suffix = "".join(random.choices(string.digits, k=6))
        account_number = f"9900{suffix}"

        logger.info(
            "MOCK Providus virtual account created: name=%s, account=%s",
            account_name,
            account_number,
        )
        print(f"\n{'='*50}")
        print(f"  MOCK Virtual Account Created")
        print(f"  Name: {account_name}")
        print(f"  Account: {account_number}")
        print(f"  Bank: Providus Bank (Mock)")
        print(f"{'='*50}\n")

        return {
            "account_number": account_number,
            "bank_name": "Providus Bank",
        }


def get_providus_client():
    """
    Factory: returns real or mock Providus client based on settings.
    Similar pattern to TERMII_MOCK.
    """
    if settings.PROVIDUS_MOCK:
        return MockProvidusClient()
    return ProvidusClient()


def verify_webhook_signature(payload_body, received_signature):
    """
    Verify HMAC-SHA256 signature on incoming Providus webhook.
    PRD Section 8.2: HMAC-SHA256 using shared secret.
    Returns True if signature is valid.
    """
    secret = settings.PROVIDUS_WEBHOOK_SECRET.encode("utf-8")
    expected_signature = hmac.new(
        secret,
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, received_signature)
