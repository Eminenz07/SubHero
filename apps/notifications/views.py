import logging
import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from .models import Notification

logger = logging.getLogger(__name__)

class NotificationListView(LoginRequiredMixin, View):
    """
    Renders notifications list categorized into 'Today', 'Yesterday', and 'Earlier'.
    """
    template_name = "notifications/index.html"

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)
        
        now = timezone.localtime(timezone.now())
        today = now.date()
        yesterday = today - datetime.timedelta(days=1)
        
        categorized = {
            "today": [],
            "yesterday": [],
            "earlier": []
        }
        
        for n in notifications:
            created_date = timezone.localtime(n.created_at).date()
            if created_date == today:
                categorized["today"].append(n)
            elif created_date == yesterday:
                categorized["yesterday"].append(n)
            else:
                categorized["earlier"].append(n)
                
        has_notifications = notifications.exists()
        unread_count = notifications.filter(is_read=False).count()
        
        context = {
            "categorized": categorized,
            "has_notifications": has_notifications,
            "unread_count": unread_count,
        }
        return render(request, self.template_name, context)


class MarkAllReadView(LoginRequiredMixin, View):
    """
    Marks all notifications for the active user as read.
    Supports HTMX to update only the content or clear indicators.
    """
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        
        if request.headers.get("HX-Request"):
            # If HTMX request, we can render the empty or read-state list
            return HttpResponse(
                '<script>window.location.reload();</script>'
            )
        return redirect("notifications:list")


class MarkReadView(LoginRequiredMixin, View):
    """
    Marks a single notification as read.
    """
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, user=request.user)
        notification.is_read = True
        notification.save()
        
        if request.headers.get("HX-Request"):
            return HttpResponse("", status=200)
        return redirect("notifications:list")


class VapidKeyView(View):
    """Returns the public VAPID key for frontend WebPush registration."""
    def get(self, request):
        return JsonResponse({"public_key": settings.VAPID_PUBLIC_KEY})


class PushSubscribeView(LoginRequiredMixin, View):
    """Saves or updates a WebPush subscription endpoint for the user."""
    def post(self, request):
        try:
            data = json.loads(request.body.decode("utf-8"))
            endpoint = data.get("endpoint")
            keys = data.get("keys", {})
            p256dh = keys.get("p256dh")
            auth = keys.get("auth")
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]

            if not endpoint or not p256dh or not auth:
                return JsonResponse({"error": "Missing subscription keys"}, status=400)

            sub, created = PushSubscription.objects.update_or_create(
                endpoint=endpoint,
                defaults={
                    "user": request.user,
                    "p256dh": p256dh,
                    "auth": auth,
                    "user_agent": user_agent,
                }
            )

            # Send a quick welcome push
            send_push_notification(
                user=request.user,
                title="🔔 Push Notifications Active!",
                body="You will now receive real-time alerts for deposits, SMM orders, and giveaways on SubHero.",
                action_url="/dashboard/",
                level="success"
            )

            return JsonResponse({"success": True, "created": created})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


class PushUnsubscribeView(LoginRequiredMixin, View):
    """Deletes a WebPush subscription endpoint."""
    def post(self, request):
        try:
            data = json.loads(request.body.decode("utf-8"))
            endpoint = data.get("endpoint")
            if endpoint:
                PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


class SendTestPushView(LoginRequiredMixin, View):
    """Triggers a test push notification to the logged-in user."""
    def post(self, request):
        sent = send_push_notification(
            user=request.user,
            title="💰 Wallet Credited — ₦5,000",
            body="Received via Bank Transfer. New Balance: ₦14,250. Tap to view receipt.",
            action_url="/vtu/",
            level="financial"
        )
        return JsonResponse({"success": True, "sent_count": sent})
