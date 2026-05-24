import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from .models import Notification

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
