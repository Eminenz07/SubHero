import json
import logging
from django.conf import settings
from pywebpush import webpush, WebPushException
from .models import PushSubscription, Notification

logger = logging.getLogger(__name__)


def send_push_notification(user, title, body, action_url="/dashboard/", icon="/static/img/icon-192.png", level="info"):
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

    vapid_private_key = settings.VAPID_PRIVATE_KEY
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
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
                ttl=86400,  # 24 hours delivery TTL
            )
            sent_count += 1
            logger.info(f"Successfully sent Web Push to user {user.phone_number} on endpoint {sub.endpoint[:30]}...")
        except WebPushException as ex:
            logger.warning(f"WebPushException for {user.phone_number}: {ex}")
            # If endpoint is 404 or 410 (unregistered/expired), mark for deletion
            if ex.response is not None and ex.response.status_code in [404, 410]:
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
