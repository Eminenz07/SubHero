import json
import logging
import urllib.request
import urllib.error
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_app_email(subject: str, recipient_email: str, html_content: str, text_content: str = "", from_email: str = None) -> bool:
    """
    Universal email dispatcher for SubHero.
    Uses Brevo HTTP API (Port 443 HTTPS) to bypass Render free tier SMTP blocks.
    Falls back to standard Django send_mail if Brevo API is unconfigured or fails.
    """
    brevo_api_key = getattr(settings, "BREVO_API_KEY", "") or ""
    default_sender = getattr(settings, "DEFAULT_FROM_EMAIL", "SubHero <noreply@subhero.com.ng>")
    
    sender_name = "SubHero"
    sender_email = "noreply@subhero.com.ng"
    
    if "<" in default_sender and ">" in default_sender:
        parts = default_sender.split("<")
        sender_name = parts[0].strip() or "SubHero"
        sender_email = parts[1].replace(">", "").strip()
    elif "@" in default_sender:
        sender_email = default_sender.strip()

    if from_email:
        if "<" in from_email and ">" in from_email:
            parts = from_email.split("<")
            sender_name = parts[0].strip() or sender_name
            sender_email = parts[1].replace(">", "").strip()
        elif "@" in from_email:
            sender_email = from_email.strip()

    if "localhost" in sender_email or "@" not in sender_email:
        sender_email = "noreply@subhero.com.ng"
        sender_name = "SubHero"

    # 1. Primary: Try Brevo REST API (HTTPS 443 - 100% works on Render free tier)
    if brevo_api_key and brevo_api_key.startswith("xkeysib-"):
        reply_to_email = getattr(settings, "SUPPORT_EMAIL", "support@subhero.com.ng")
        payload = {
            "sender": {
                "name": sender_name,
                "email": sender_email
            },
            "to": [
                {"email": recipient_email}
            ],
            "replyTo": {
                "name": "SubHero Support",
                "email": reply_to_email
            },
            "subject": subject,
            "htmlContent": html_content or text_content,
        }
        if text_content:
            payload["textContent"] = text_content

        try:
            req = urllib.request.Request(
                BREVO_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "api-key": brevo_api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in (200, 201, 202):
                    safe_subj = subject.encode("ascii", "replace").decode("ascii")
                    logger.info("Email sent via Brevo HTTP API to %s: %s", recipient_email, safe_subj)
                    return True
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            logger.error("Brevo API HTTPError (%s): %s", he.code, err_body)
        except Exception as e:
            logger.error("Brevo API error dispatching email to %s: %s", recipient_email, e)

    # 2. Fallback: Django SMTP send_mail
    try:
        send_mail(
            subject=subject,
            message=text_content or "Please view this email in an HTML-compatible client.",
            html_message=html_content,
            from_email=default_sender,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        safe_subj = subject.encode("ascii", "replace").decode("ascii")
        logger.info("Email sent via Django fallback to %s: %s", recipient_email, safe_subj)
        return True
    except Exception as e:
        logger.error("Failed to send email fallback to %s: %s", recipient_email, e)
        return False


import threading


def send_async_app_email(subject: str, recipient_email: str, html_content: str, text_content: str = "", from_email: str = None) -> threading.Thread:
    """
    Non-blocking async dispatcher for send_app_email.
    Runs inside a background thread so the HTTP web request cycle finishes immediately.
    """
    thread = threading.Thread(
        target=send_app_email,
        args=(subject, recipient_email, html_content, text_content, from_email),
        daemon=True,
    )
    thread.start()
    return thread

