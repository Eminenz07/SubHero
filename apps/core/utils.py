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
    Format: SH{timestamp_hex}{random_chars}  (no hyphens — provider rejects them)
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
    Handles Cloudflare CF-Connecting-IP, X-Real-IP, and X-Forwarded-For.
    """
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()

    x_real_ip = request.META.get("HTTP_X_REAL_IP")
    if x_real_ip:
        return x_real_ip.strip()

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def _mark_session_modified(session):
    if session is not None and hasattr(session, "modified"):
        session.modified = True


def _hash_otp(otp, phone):
    """Hash an OTP with the phone number or email as salt using SHA-256."""
    clean_otp = str(otp).strip()
    clean_id = str(phone).strip().lower() if "@" in str(phone) else str(phone).strip()
    return hashlib.sha256(f"{clean_otp}:{clean_id}".encode()).hexdigest()


def send_otp(phone_number, session=None, otp=None):
    """
    Send a 6-digit OTP via Termii SMS.
    In mock mode (dev), logs OTP to console instead.
    Returns True on success, False on failure.
    """
    if not otp:
        otp = "".join(random.choices(string.digits, k=settings.OTP_LENGTH))
    clean_phone = phone_number.strip()

    # Store hashed OTP in cache with TTL
    cache_key = f"otp:{clean_phone}"
    attempts_key = f"otp_attempts:{clean_phone}"
    hashed = _hash_otp(otp, clean_phone)
    cache.set(cache_key, hashed, settings.OTP_EXPIRY_SECONDS)
    cache.set(attempts_key, 0, settings.OTP_EXPIRY_SECONDS)

    if session is not None:
        import time
        session["otp_hash"] = hashed
        session["otp_expires_at"] = time.time() + settings.OTP_EXPIRY_SECONDS
        session["otp_identifier"] = clean_phone
        session["otp_attempts"] = 0
        _mark_session_modified(session)

    if settings.TERMII_MOCK:
        logger.info(
            "MOCK OTP for %s: %s (expires in %ds)",
            clean_phone,
            otp,
            settings.OTP_EXPIRY_SECONDS,
        )
        print(f"\n{'='*50}")
        print(f"  MOCK OTP for {clean_phone}: {otp}")
        print(f"  Expires in {settings.OTP_EXPIRY_SECONDS // 60} minutes")
        print(f"{'='*50}\n")
        return True

    # Standardize phone number for Termii (e.g. +2349073601282 or 09073601282 -> 2349073601282)
    formatted_phone = clean_phone.replace("+", "")
    if formatted_phone.startswith("0"):
        formatted_phone = "234" + formatted_phone[1:]

    # Real Termii API call
    try:
        url = f"{settings.TERMII_BASE_URL}/sms/send?api_key={settings.TERMII_API_KEY}"
        payload = {
            "to": formatted_phone,
            "from": settings.TERMII_SENDER_ID or "SubHero",
            "sms": f"Your SubHero verification code is: {otp}. Valid for {settings.OTP_EXPIRY_SECONDS // 60} minutes.",
            "type": "plain",
            "channel": "generic",
            "api_key": settings.TERMII_API_KEY,
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("OTP sent to %s via Termii", clean_phone)
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


def verify_otp(identifier, code, session=None):
    """
    Verify an OTP code against the hashed value in cache or session.
    Accepts phone number or email address as identifier.
    Returns True if valid, False otherwise.
    Single-use — consumed immediately on verification (PRD Section 7.1).
    """
    import time

    clean_id = str(identifier).strip().lower() if "@" in str(identifier) else str(identifier).strip()
    clean_code = str(code).strip()
    cache_key = f"otp:{clean_id}"
    attempts_key = f"otp_attempts:{clean_id}"

    stored_hash = cache.get(cache_key)
    target_hash = _hash_otp(clean_code, clean_id)

    # 1. Primary verification against cache (Redis / LocMem)
    if stored_hash is not None:
        attempts = cache.get(attempts_key, 0)
        if attempts >= settings.OTP_MAX_ATTEMPTS:
            cache.delete(cache_key)
            cache.delete(attempts_key)
            if session is not None:
                session.pop("otp_hash", None)
                session.pop("otp_expires_at", None)
                session.pop("otp_identifier", None)
                _mark_session_modified(session)
            return False

        if stored_hash == target_hash:
            # Single-use: delete immediately
            cache.delete(cache_key)
            cache.delete(attempts_key)
            if session is not None:
                session.pop("otp_hash", None)
                session.pop("otp_expires_at", None)
                session.pop("otp_identifier", None)
                _mark_session_modified(session)
            return True
        else:
            cache.set(attempts_key, attempts + 1, settings.OTP_EXPIRY_SECONDS)
            return False

    # 2. Resilient session fallback (handles multi-worker Gunicorn LocMemCache or Redis dropouts)
    if session is not None:
        sess_hash = session.get("otp_hash")
        sess_expires = session.get("otp_expires_at", 0)
        sess_id = session.get("otp_identifier", "")
        sess_attempts = session.get("otp_attempts", 0)

        # Check if session has matching OTP and is not expired
        if sess_hash and time.time() <= sess_expires:
            # Check attempt limit
            if sess_attempts >= settings.OTP_MAX_ATTEMPTS:
                session.pop("otp_hash", None)
                session.pop("otp_expires_at", None)
                session.pop("otp_identifier", None)
                _mark_session_modified(session)
                return False

            clean_sess_id = str(sess_id).strip().lower() if "@" in str(sess_id) else str(sess_id).strip()
            # Allow match if target hash matches session hash, or if hashed with sess_id
            if sess_hash == target_hash or sess_hash == _hash_otp(clean_code, clean_sess_id):
                session.pop("otp_hash", None)
                session.pop("otp_expires_at", None)
                session.pop("otp_identifier", None)
                session.pop("otp_attempts", None)
                _mark_session_modified(session)
                # Clean up any cache keys if present
                cache.delete(cache_key)
                cache.delete(attempts_key)
                return True
            else:
                session["otp_attempts"] = sess_attempts + 1
                _mark_session_modified(session)
                return False

    return False


def send_email_otp(user, purpose="registration", session=None):
    """
    Generate and dispatch a 6-digit OTP code to user's email address.
    Stores hashed OTP in cache and optional session fallback.
    Dispatches styled HTML email asynchronously via direct SMTP.
    Returns the generated OTP code.
    """
    import time
    from django.template.loader import render_to_string
    from apps.core.email import send_async_app_email

    otp = "".join(random.choices(string.digits, k=settings.OTP_LENGTH))
    identifier = user.email.strip().lower()
    hashed = _hash_otp(otp, identifier)

    # Store hashed OTP in cache with TTL
    cache_key = f"otp:{identifier}"
    attempts_key = f"otp_attempts:{identifier}"
    cache.set(cache_key, hashed, settings.OTP_EXPIRY_SECONDS)
    cache.set(attempts_key, 0, settings.OTP_EXPIRY_SECONDS)

    # Store in session fallback if session provided
    if session is not None:
        session["otp_hash"] = hashed
        session["otp_expires_at"] = time.time() + settings.OTP_EXPIRY_SECONDS
        session["otp_identifier"] = identifier
        session["otp_attempts"] = 0
        _mark_session_modified(session)

    if purpose == "registration":
        template_name = "emails/registration_otp.html"
        subject = "SubHero Email Verification"
    else:
        template_name = "emails/password_reset_otp.html"
        subject = "Reset Your SubHero Password"

    context = {
        "user_name": user.full_name or "there",
        "otp_code": otp,
    }

    try:
        html_content = render_to_string(template_name, context)
    except Exception as e:
        logger.error("Failed to render %s: %s", template_name, e)
        html_content = f"<p>Your SubHero verification code is: <strong>{otp}</strong>. Valid for 10 minutes.</p>"

    text_content = f"Your SubHero verification code is {otp}. It will expire in {settings.OTP_EXPIRY_SECONDS // 60} minutes."

    send_async_app_email(
        subject=subject,
        recipient_email=user.email,
        html_content=html_content,
        text_content=text_content,
    )

    if settings.DEBUG or getattr(settings, "TERMII_MOCK", False):
        logger.info(
            "EMAIL OTP [%s] for %s: %s (expires in %ds)",
            purpose,
            user.email,
            otp,
            settings.OTP_EXPIRY_SECONDS,
        )
        print(f"\n{'='*50}")
        print(f"  EMAIL OTP [{purpose.upper()}] for {user.email}: {otp}")
        print(f"  Expires in {settings.OTP_EXPIRY_SECONDS // 60} minutes")
        print(f"{'='*50}\n")

    return otp


def mask_email(email):
    """
    Mask email for display.
    Examples:
        eminenceadeoluwa@gmail.com -> em****a@gmail.com
        user@domain.com -> u****r@domain.com
        me@domain.com -> m*@domain.com
    """
    if not email or "@" not in email:
        return email or ""
    user_part, domain = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + "*"
    elif len(user_part) <= 4:
        masked_user = user_part[0] + "**" + user_part[-1]
    else:
        masked_user = user_part[:2] + "****" + user_part[-1]
    return f"{masked_user}@{domain}"



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
