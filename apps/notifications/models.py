import uuid
from django.db import models
from django.conf import settings

class Notification(models.Model):
    """
    Dynamic database-backed user notification system.
    Supports individual mark-as-read and customized visual icon styling.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    
    # Material symbol or Feather icon name
    icon = models.CharField(max_length=50, default="bell")
    
    # Custom Tailwind style classes for background & foreground accents
    icon_bg = models.CharField(max_length=100, default="bg-blue-50 text-blue-500")
    
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def add(cls, user, title, description, level="info"):
        """
        Synthesizes and adds a notification for a user based on level:
        - info: Soft Blue
        - success / financial: Soft Green
        - warning: Soft Amber
        - security / danger: Soft Red
        """
        icon = "bell"
        icon_bg = "bg-blue-50 text-blue-500"

        # Normalize strings
        title_lower = title.lower()

        if level == "info":
            icon = "info"
            icon_bg = "bg-blue-50 text-blue-600"
        elif level == "success" or level == "financial":
            icon = "check-circle"
            if "fund" in title_lower or "received" in title_lower or "deposit" in title_lower:
                icon = "arrow-down-left"
            elif "transfer" in title_lower or "send" in title_lower:
                icon = "arrow-up-right"
            icon_bg = "bg-green-50 text-status-success-text"
        elif level == "warning":
            icon = "alert-triangle"
            if "refund" in title_lower or "fail" in title_lower:
                icon = "refresh-cw"
            icon_bg = "bg-yellow-50 text-yellow-600"
        elif level == "security" or level == "danger":
            icon = "shield"
            if "pin" in title_lower or "password" in title_lower:
                icon = "lock"
            icon_bg = "bg-red-50 text-status-danger"

        return cls.objects.create(
            user=user,
            title=title,
            description=description,
            icon=icon,
            icon_bg=icon_bg
        )

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.user.phone_number}"


class PushSubscription(models.Model):
    """
    Stores Web Push subscription endpoints and VAPID keys per user device.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.TextField(unique=True, help_text="Browser WebPush endpoint URL")
    p256dh = models.TextField(help_text="Browser p256dh public key")
    auth = models.TextField(help_text="Browser auth secret")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications_push_subscription"
        ordering = ["-created_at"]

    def __str__(self):
        return f"PushSub {self.user.phone_number} - {self.endpoint[:30]}..."
