"""
Admin Panel — Models
====================
Defines database models for custom operations, alerts, auditing, and system logs.
"""

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class AdminLog(models.Model):
    """
    Logs every action performed by an administrator inside the admin panel.
    """
    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="admin_actions"
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50)
    target_id = models.CharField(max_length=100)
    detail = models.TextField()
    ip_address = models.GenericIPAddressField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        user_email = self.admin_user.email if self.admin_user else "System"
        return f"{user_email} | {self.action} on {self.target_type} ({self.target_id})"


class SystemLog(models.Model):
    """
    Unified application-wide system logging database.
    """
    class Level(models.TextChoices):
        SUCCESS = "SUCCESS", "SUCCESS"
        INFO = "INFO", "INFO"
        WARNING = "WARNING", "WARNING"
        ERROR = "ERROR", "ERROR"
        CRITICAL = "CRITICAL", "CRITICAL"

    class Category(models.TextChoices):
        AUTH = "AUTH", "AUTH"
        WALLET = "WALLET", "WALLET"
        VTU = "VTU", "VTU"
        SMM = "SMM", "SMM"
        SYSTEM = "SYSTEM", "SYSTEM"

    level = models.CharField(max_length=20, choices=Level.choices)
    category = models.CharField(max_length=20, choices=Category.choices)
    message = models.TextField()
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["level", "created_at"]),
            models.Index(fields=["category", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.level}][{self.category}] {self.message[:50]}"


class AlertConfig(models.Model):
    """
    Singleton configuration for external API balance thresholds and system rate configurations.
    """
    alert_email = models.EmailField()
    sabuss_warning_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=10000.00)
    sabuss_critical_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=3000.00)
    cdh_warning_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=10000.00)
    cdh_critical_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=3000.00)
    ogaviral_warning_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=10000.00)
    ogaviral_critical_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=3000.00)
    jap_warning_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=5.00)
    jap_critical_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=2.00)
    usd_ngn_rate = models.DecimalField(max_digits=10, decimal_places=2, default=1600.00)
    rate_last_updated = models.DateTimeField(auto_now=True)

    def clean(self):
        if not self.pk and AlertConfig.objects.exists():
            raise ValidationError("Only one instance of AlertConfig is allowed.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"System Alert Config ({self.alert_email})"


class SystemSetting(models.Model):
    """
    Key-Value pair configuration system for application feature flags.
    """
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()

    def __str__(self):
        return f"{self.key} = {self.value}"

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value):
        setting, _ = cls.objects.update_or_create(key=key, defaults={"value": str(value)})
        return setting
