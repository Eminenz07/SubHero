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
    TIER_CHOICES = [
        ("basic", "Basic (Quick Boost)"),
        ("standard", "Standard (Growth Boost)"),
        ("premium", "Premium (Elite Boost)"),
    ]

    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        help_text="Confirmed tier classification (basic, standard, premium). Null means unclassified."
    )
    suggested_tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        blank=True,
        null=True,
        help_text="Auto-suggested tier based on description keywords and category price banding"
    )
    TIER_SOURCE_CHOICES = [
        ("auto", "Auto-classified"),
        ("manual", "Admin override"),
    ]
    tier_source = models.CharField(
        max_length=10,
        choices=TIER_SOURCE_CHOICES,
        blank=True,
        default="",
        help_text="How 'tier' was set. 'manual' tiers are never overwritten by catalogue syncs."
    )
    description = models.TextField(blank=True, default="", help_text="Full service details, rules, and start time fetched from gateway")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "smm_service"
        ordering = ["category", "subhero_price_per_1k"]

    @property
    def tier_title(self):
        if self.tier == "basic":
            return "Quick Boost"
        elif self.tier == "standard":
            return "Growth Boost"
        elif self.tier == "premium":
            return "Elite Boost"
        return "Unclassified"

    @property
    def tier_tag(self):
        if self.tier == "standard":
            return "Most Popular"
        elif self.tier == "premium":
            return "Recommended"
        return None

    @property
    def retention_label(self):
        if self.tier == "basic":
            return "Short-term spike · Lower retention"
        elif self.tier == "standard":
            return "30-Day Refill Guarantee · ~70-85% retention"
        elif self.tier == "premium":
            return "Permanent / Non-Drop · 95%+ high retention"
        return "Standard retention"

    @property
    def delivery_speed(self):
        if self.tier == "basic":
            return "Instant (Starts in 5–15 mins)"
        elif self.tier == "standard":
            return "Steady Delivery (Starts in 15–30 mins)"
        elif self.tier == "premium":
            return "Natural Paced (Starts in 20–45 mins)"
        return "Starts in ~15 mins"

    @property
    def tier_honest_description(self):
        if self.tier == "basic":
            return "Fast & affordable — best for quick visibility, engagement may drop over time."
        elif self.tier == "standard":
            return "Balanced speed and retention — reliable momentum with refill protection."
        elif self.tier == "premium":
            return "Real, active engagement, highest retention, slower natural-paced delivery."
        return ""


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
    api_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Cost price from provider API")
    reference = models.CharField(max_length=50, unique=True)
    provider_order_id = models.CharField(max_length=100, blank=True, default="")
    start_count = models.IntegerField(default=0, help_text="Starting count on user account before delivery")
    remains = models.IntegerField(default=0, help_text="Quantity left to deliver")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "smm_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"SMMOrder {self.reference} - {self.status}"

    @property
    def delivered_count(self):
        """Calculates how many followers/likes have been delivered so far."""
        if self.status == self.Status.SUCCESS:
            return self.quantity
        if self.status == self.Status.FAILED or self.status == self.Status.CANCELLED:
            return 0
        if self.remains is not None and self.remains > 0:
            if self.quantity >= self.remains:
                return self.quantity - self.remains
            return 0
        if self.status == self.Status.PROCESSING and self.start_count > 0 and self.remains == 0:
            # If start_count was recorded and remains is 0, delivery completed
            return self.quantity
        return 0

    @property
    def progress_percent(self):
        """Returns integer 0-100 representing percentage delivered."""
        if self.status == self.Status.SUCCESS:
            return 100
        if not self.quantity or self.quantity <= 0:
            return 0
        delivered = self.delivered_count
        pct = int((delivered / self.quantity) * 100)
        return min(100, max(0, pct))

    @property
    def current_count(self):
        """Estimated current profile count: start_count + delivered_count."""
        if self.start_count and self.start_count > 0:
            return self.start_count + self.delivered_count
        return None

    @property
    def target_final_count(self):
        """Target count when order completes: start_count + quantity."""
        if self.start_count and self.start_count > 0:
            return self.start_count + self.quantity
        return None
