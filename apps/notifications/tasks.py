import logging
import requests
from django.conf import settings
from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=1)
def send_transaction_sms(self, phone_number, message):
    """
    PRD Section 10: Sends transactional SMS via Termii /sms/send API.
    Uses 'dnd' channel to bypass carrier-level blocking.
    Mocked if TERMII_MOCK=True in environment configuration.
    """
    logger.info("Sending SMS to %s: %s", phone_number, message)

    if settings.TERMII_MOCK:
        logger.info("TERMII_MOCK is enabled. SMS simulated successfully.")
        return {"status": "success", "mocked": True}

    formatted_phone = phone_number.strip().replace("+", "")
    if formatted_phone.startswith("0"):
        formatted_phone = "234" + formatted_phone[1:]

    url = f"{settings.TERMII_BASE_URL}/sms/send"
    payload = {
        "api_key": settings.TERMII_API_KEY,
        "to": formatted_phone,
        "from": settings.TERMII_SENDER_ID or "SubHero",
        "sms": message,
        "type": "plain",
        "channel": "generic"
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.info("Termii API response: %s", data)
        return data
    except Exception as exc:
        logger.error("Termii SMS delivery failure: %s. Retrying...", str(exc))
        try:
            self.retry(exc=exc, countdown=10)
        except Exception:
            logger.error("Termii SMS delivery failed after retries.")
            raise
