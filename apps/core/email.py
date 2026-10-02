import logging
import threading
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_app_email(
    subject: str,
    recipient_email: str,
    html_content: str,
    text_content: str = "",
    from_email: str = None,
    reply_to: str = None,
) -> bool:
    """
    Direct SMTP email dispatcher for SubHero.
    Sends rich responsive HTML emails with plain-text fallback directly via SMTP.
    """
    if not recipient_email or "@" not in recipient_email:
        logger.warning("send_app_email aborted: invalid recipient email '%s'", recipient_email)
        return False

    # Determine sender email address
    default_sender = getattr(settings, "DEFAULT_FROM_EMAIL", "SubHero <noreply@subhero.com.ng>")
    sender = from_email or default_sender

    # Determine reply-to email address
    support_email = reply_to or getattr(settings, "SUPPORT_EMAIL", "support@subhero.com.ng")
    reply_to_list = [support_email] if support_email else None

    # Generate plain-text alternative if not explicitly supplied
    if not text_content:
        if html_content:
            text_content = strip_tags(html_content).strip()
        else:
            text_content = "Please view this email in an HTML-compatible email client."

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=sender,
            to=[recipient_email],
            reply_to=reply_to_list,
        )

        if html_content:
            msg.attach_alternative(html_content, "text/html")

        msg.send(fail_silently=False)
        safe_subj = subject.encode("ascii", "replace").decode("ascii")
        logger.info("Direct SMTP email delivered successfully to %s: %s", recipient_email, safe_subj)
        return True

    except Exception as exc:
        logger.error("SMTP delivery failure to %s (subject: %s): %s", recipient_email, subject, exc, exc_info=True)
        return False


def send_async_app_email(
    subject: str,
    recipient_email: str,
    html_content: str,
    text_content: str = "",
    from_email: str = None,
    reply_to: str = None,
) -> threading.Thread:
    """
    Non-blocking async dispatcher for send_app_email.
    Spawns a background thread so the HTTP request completes instantly without
    waiting for SMTP TLS handshake / socket latency.
    """
    thread = threading.Thread(
        target=send_app_email,
        kwargs={
            "subject": subject,
            "recipient_email": recipient_email,
            "html_content": html_content,
            "text_content": text_content,
            "from_email": from_email,
            "reply_to": reply_to,
        },
        daemon=True,
    )
    thread.start()
    return thread
