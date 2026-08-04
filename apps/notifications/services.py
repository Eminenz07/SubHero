import json
import logging
from django.conf import settings
from pywebpush import webpush, WebPushException
from .models import PushSubscription, Notification

logger = logging.getLogger(__name__)


def get_vapid_object():
    """
    Parses VAPID_PRIVATE_KEY setting into a valid py_vapid Vapid object.
    Supports PEM strings, raw base64, or file paths.
    """
    from py_vapid import Vapid
    key_str = str(getattr(settings, "VAPID_PRIVATE_KEY", "")).strip()

    if "\\n" in key_str:
        key_str = key_str.replace("\\n", "\n")

    if "BEGIN PRIVATE KEY" in key_str:
        return Vapid.from_pem(key_str.encode("utf-8"))
    
    try:
        return Vapid.from_string(private_key=key_str)
    except Exception:
        return Vapid.from_file(key_str)


def send_push_notification(user, title, body, action_url="/dashboard/", icon="/static/img/sh-logo.png", level="info"):
    """
    Sends a Web Push notification to all active devices/subscriptions of a user.
    Also creates an in-app Notification record so the user sees it in their notification center.
    """
    # 1. Add to in-app Notification table
    try:
        Notification.add(user=user, title=title, description=body, level=level)
    except Exception as e:
        logger.error(f"Error logging in-app notification for {user.phone_number}: {e}")

    # 2. Fetch user's push subscriptions
    subscriptions = PushSubscription.objects.filter(user=user)
    if not subscriptions.exists():
        logger.info(f"No push subscriptions found for user {user.phone_number}")
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": icon,
        "url": action_url,
    })

    try:
        vapid_key_obj = get_vapid_object()
    except Exception as e:
        logger.error(f"Failed to load VAPID private key: {e}")
        return 0

    vapid_claims = {
        "sub": settings.VAPID_ADMIN_EMAIL,
    }

    sent_count = 0
    expired_ids = []

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {
                "p256dh": sub.p256dh,
                "auth": sub.auth,
            }
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid_key_obj,
                vapid_claims=vapid_claims,
                ttl=86400,  # 24 hours delivery TTL
            )
            sent_count += 1
            logger.info(f"Successfully sent Web Push to user {user.phone_number} on endpoint {sub.endpoint[:30]}...")
        except WebPushException as ex:
            logger.warning(f"WebPushException for {user.phone_number}: {ex}")
            # If endpoint is invalid, forbidden, unregistered or expired (400, 403, 404, 410), mark for deletion
            if ex.response is not None and ex.response.status_code in [400, 403, 404, 410]:
                expired_ids.append(sub.id)
        except Exception as ex:
            logger.error(f"Unexpected error sending push notification to {user.phone_number}: {ex}")

    # Clean up stale subscriptions
    if expired_ids:
        PushSubscription.objects.filter(id__in=expired_ids).delete()

    return sent_count


def broadcast_push_notification(title, body, action_url="/dashboard/"):
    """
    Sends a Web Push notification to ALL users with active subscriptions (e.g. Flash sales).
    """
    from apps.accounts.models import User
    users_with_subs = User.objects.filter(push_subscriptions__isnull=False).distinct()
    total_sent = 0
    for user in users_with_subs:
        total_sent += send_push_notification(user, title, body, action_url=action_url, level="info")
    return total_sent
