"""
Core — Shared Utilities
========================
UUID generation, IP extraction, OTP helpers.
"""

import hashlib
import logging
import random
import string
import time
import uuid

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def generate_reference(prefix="SH"):
    """
    Generate a unique transaction reference.
    Format: SH{timestamp_hex}{random_chars}  (no hyphens — Sabuss rejects them)
    """
    ts = hex(int(time.time()))[2:]
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}{ts}{rand}"


def generate_uuid():
    """Generate a new UUID4."""
    return uuid.uuid4()


def get_client_ip(request):
    """
    Extract the real client IP from the request.
    Handles X-Forwarded-For from reverse proxy (Nginx).
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # Take the first IP (client's real IP)
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def _hash_otp(otp, phone):
    """Hash OTP for storage in Redis — never store plaintext (PRD Section 7.1)."""
    return hashlib.sha256(f"{otp}:{phone}".encode()).hexdigest()


def send_otp(phone_number):
    """
    Send a 6-digit OTP via Termii SMS.
    In mock mode (dev), logs OTP to console instead.
    Returns True on success, False on failure.
    """
    otp = "".join(random.choices(string.digits, k=settings.OTP_LENGTH))

    # Store hashed OTP in cache with TTL
    cache_key = f"otp:{phone_number}"
    attempts_key = f"otp_attempts:{phone_number}"
    cache.set(cache_key, _hash_otp(otp, phone_number), settings.OTP_EXPIRY_SECONDS)
    cache.set(attempts_key, 0, settings.OTP_EXPIRY_SECONDS)

    if settings.TERMII_MOCK:
        logger.info(
            "MOCK OTP for %s: %s (expires in %ds)",
            phone_number,
            otp,
            settings.OTP_EXPIRY_SECONDS,
        )
        print(f"\n{'='*50}")
        print(f"  MOCK OTP for {phone_number}: {otp}")
        print(f"  Expires in {settings.OTP_EXPIRY_SECONDS // 60} minutes")
        print(f"{'='*50}\n")
        return True

    # Standardize phone number for Termii (e.g. +2349073601282 or 09073601282 -> 2349073601282)
    formatted_phone = phone_number.strip().replace("+", "")
    if formatted_phone.startswith("0"):
        formatted_phone = "234" + formatted_phone[1:]

    # Real Termii API call
    try:
        payload = {
            "to": formatted_phone,
            "from": settings.TERMII_SENDER_ID or "SubHero",
            "sms": f"Your SubHero verification code is: {otp}. Valid for {settings.OTP_EXPIRY_SECONDS // 60} minutes.",
            "type": "plain",
            "channel": "generic",
            "api_key": settings.TERMII_API_KEY,
        }
        response = requests.post(
            f"{settings.TERMII_BASE_URL}/sms/send",
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            logger.info("OTP sent to %s via Termii", phone_number)
            return True
        else:
            logger.error(
                "Termii OTP send failed: %s %s",
                response.status_code,
                response.text,
            )
            return False
    except requests.RequestException as e:
        logger.error("Termii API error: %s", str(e))
        return False


def verify_otp(phone_number, code):
    """
    Verify an OTP code against the hashed value in cache.
    Returns True if valid, False otherwise.
    Single-use — consumed immediately on verification (PRD Section 7.1).
    """
    cache_key = f"otp:{phone_number}"
    attempts_key = f"otp_attempts:{phone_number}"

    stored_hash = cache.get(cache_key)
    if stored_hash is None:
        return False

    # Check attempt limit (max 3 attempts per PRD)
    attempts = cache.get(attempts_key, 0)
    if attempts >= settings.OTP_MAX_ATTEMPTS:
        cache.delete(cache_key)
        cache.delete(attempts_key)
        return False

    # Verify
    if stored_hash == _hash_otp(code, phone_number):
        # Single-use: delete immediately
        cache.delete(cache_key)
        cache.delete(attempts_key)
        return True
    else:
        # Increment attempt counter
        cache.set(attempts_key, attempts + 1, settings.OTP_EXPIRY_SECONDS)
        return False


def normalize_phone(phone_number):
    """
    Normalize Nigerian phone number to E.164 format (+234XXXXXXXXXX).
    Accepts: 08012345678, +2348012345678, 2348012345678
    """
    phone = phone_number.strip().replace(" ", "").replace("-", "")

    if phone.startswith("0") and len(phone) == 11:
        phone = "+234" + phone[1:]
    elif phone.startswith("234") and len(phone) == 13:
        phone = "+" + phone
    elif phone.startswith("+234") and len(phone) == 14:
        pass  # Already correct
    else:
        return phone  # Return as-is; validation will catch it

    return phone
