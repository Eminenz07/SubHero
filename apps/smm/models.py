import uuid
from django.db import models
from django.conf import settings

class SMMService(models.Model):
    """
    SMM panels services cached from JustAnotherPanel.
    Includes rate per 1k, min/max limits, category, and local custom SubHero markup pricing.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_service_id = models.CharField(max_length=50, unique=True, help_text="JustAnotherPanel service ID")
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    subcategory = models.CharField(max_length=150, blank=True, default="", db_index=True)
    provider_min = models.IntegerField(default=0)
    provider_max = models.IntegerField(default=0)
    provider_rate = models.DecimalField(max_digits=10, decimal_places=4, help_text="JAP rate per 1k")
    subhero_price_per_1k = models.DecimalField(max_digits=10, decimal_places=2, help_text="SubHero rate per 1k charged to users")
    markup_type = models.CharField(
        max_length=10,
        choices=[("percent", "Percentage"), ("fixed", "Fixed")],
        default="fixed"
    )
    markup_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "smm_service"
        ordering = ["category", "subhero_price_per_1k"]

    def __str__(self):
        return f"{self.category} - {self.name} (₦{self.subhero_price_per_1k})"


class SMMOrder(models.Model):
    """
    SMM Social media booster orders tracked via JustAnotherPanel.
    """
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS = "SUCCESS", "Success"
        PARTIAL = "PARTIAL", "Partial Delivery"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="smm_orders"
    )
    service = models.ForeignKey(
        SMMService,
        on_delete=models.CASCADE,
        related_name="orders"
    )
    target_url = models.URLField(max_length=500)
    quantity = models.IntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Naira charge paid by customer")
    reference = models.CharField(max_length=50, unique=True)
    provider_order_id = models.CharField(max_length=100, blank=True, default="")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "smm_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"SMMOrder {self.reference} - {self.status}"
