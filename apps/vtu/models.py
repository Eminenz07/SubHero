import uuid
from django.db import models
from django.conf import settings

class VTUPlan(models.Model):
    """
    Local cache of data plans synced from CheapDataHub API.
    All client pricing is computed using this table.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan_id = models.CharField(max_length=50, unique=True, help_text="CheapDataHub plan ID")
    network = models.CharField(max_length=20, help_text="e.g. mtn, airtel, glo, 9mobile")
    name = models.CharField(max_length=100)
    provider_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="CheapDataHub cost price")
    subhero_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price charged to SubHero customers")
    validity = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vtu_plan"
        ordering = ["network", "subhero_price"]

    def __str__(self):
        return f"{self.network.upper()} - {self.name} (₦{self.subhero_price})"


class VTUOrder(models.Model):
    """
    Stores data/VTU orders and tracks fulfillment status from CheapDataHub outbound API.
    """
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vtu_orders"
    )
    network = models.CharField(max_length=20)
    recipient = models.CharField(max_length=20, help_text="Target phone number or meter number")
    plan_id = models.CharField(max_length=50)
    plan_name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price paid by customer")
    reference = models.CharField(max_length=50, unique=True)
    provider_ref = models.CharField(max_length=100, blank=True, default="", help_text="Provider's order reference")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "vtu_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"VTUOrder {self.reference} - {self.status}"
