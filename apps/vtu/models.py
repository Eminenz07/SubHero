import uuid
from django.db import models
from django.conf import settings

# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

class VTUPlan(models.Model):
    """
    Local cache of data plans synced from the outbound VTU provider.
    All client pricing is computed using this table.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan_id = models.CharField(max_length=80, unique=True, help_text="Provider plan identifier used when buying")
    provider_product = models.CharField(max_length=80, blank=True, default="", help_text="Provider product label, e.g. MTN GIFTING")
    network = models.CharField(max_length=20, help_text="e.g. mtn, airtel, glo, 9mobile")
    plan_type = models.CharField(max_length=30, blank=True, default="", help_text="Plan category, e.g. SME, SME2, SMART, DATA, CG, AWOOF")
    name = models.CharField(max_length=100)
    provider_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Provider cost price")
    subhero_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price charged to SubHero customers")
    validity = models.CharField(max_length=50, blank=True, default="")
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
        db_table = "vtu_plan"
        ordering = ["network", "plan_type", "subhero_price"]

    def __str__(self):
        return f"{self.network.upper()} {self.plan_type} - {self.name} (₦{self.subhero_price})"


class VTUOrder(models.Model):
    """
    Stores data/VTU orders and tracks fulfillment status from the outbound VTU provider.
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
    plan_id = models.CharField(max_length=80)
    plan_name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price paid by customer")
    api_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Cost price from provider API")
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


# ─────────────────────────────────────────────
# AIRTIME
# ─────────────────────────────────────────────

# Supported mobile networks. The provider product name is resolved at runtime
# from the live catalogue, so a provider rename needs no code change.
AIRTIME_NETWORKS = {
    "mtn":     {"label": "MTN"},
    "airtel":  {"label": "Airtel"},
    "glo":     {"label": "Glo"},
    "9mobile": {"label": "9mobile"},
}


class AirtimeOrder(models.Model):
    """Tracks airtime top-up orders via the outbound VTU provider."""
    class Status(models.TextChoices):
        PENDING    = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS    = "SUCCESS", "Success"
        FAILED     = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="airtime_orders")
    network = models.CharField(max_length=20)
    provider_product = models.CharField(max_length=80, blank=True, default="", help_text="Provider airtime product name")
    recipient = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    api_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference = models.CharField(max_length=50, unique=True)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "airtime_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"AirtimeOrder {self.reference} - {self.network} ₦{self.amount}"


# ─────────────────────────────────────────────
# CABLE TV
# ─────────────────────────────────────────────

class CablePlan(models.Model):
    """
    Local cache of Cable TV subscription plans from the outbound VTU provider.
    """
    plan_id = models.CharField(max_length=80, unique=True, help_text="Provider cable plan identifier")
    provider = models.CharField(max_length=20, help_text="dstv, gotv, startimes")
    provider_product = models.CharField(max_length=40, blank=True, default="", help_text="Provider product label, e.g. GOTV")
    name = models.CharField(max_length=150, help_text="Package name e.g. DStv Compact")
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Subscription amount in NGN")
    subhero_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price charged to customer")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cable_plan"
        ordering = ["provider", "amount"]

    def __str__(self):
        return f"{self.provider.upper()} - {self.name} (₦{self.subhero_price})"


class CableOrder(models.Model):
    """Tracks cable TV subscription orders via the outbound VTU provider."""
    class Status(models.TextChoices):
        PENDING    = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS    = "SUCCESS", "Success"
        FAILED     = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cable_orders")
    provider = models.CharField(max_length=20)
    provider_product = models.CharField(max_length=40, blank=True, default="", help_text="Provider product label used for validation")
    plan_id = models.CharField(max_length=80)
    plan_name = models.CharField(max_length=150)
    card_number = models.CharField(max_length=30, help_text="Smart card / IUC number")
    customer_name = models.CharField(max_length=120, blank=True, default="", help_text="Subscriber name returned by provider validation")
    phone = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    api_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference = models.CharField(max_length=50, unique=True)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "cable_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"CableOrder {self.reference} - {self.provider} {self.plan_name}"


# ─────────────────────────────────────────────
# ELECTRICITY
# ─────────────────────────────────────────────

# Distribution companies (DISCOs). The code is the provider biller code;
# it is reconciled against the live provider catalogue at purchase time.
DISCO_CHOICES = [
    ("IKEDC",  "Ikeja Electric (IKEDC)"),
    ("EKEDC",  "Eko Electric (EKEDC)"),
    ("KEDCO",  "Kano Electric (KEDCO)"),
    ("PHEDC",  "Port Harcourt Electric (PHEDC)"),
    ("JED",    "Jos Electric (JED)"),
    ("IBEDC",  "Ibadan Electric (IBEDC)"),
    ("KAEDCO", "Kaduna Electric (KAEDCO)"),
    ("AEDC",   "Abuja Electric (AEDC)"),
    ("EEDC",   "Enugu Electric (EEDC)"),
    ("BEDC",   "Benin Electric (BEDC)"),
    ("YEDC",   "Yola Electric (YEDC)"),
]

DISCO_NAMES = {d[0]: d[1] for d in DISCO_CHOICES}


class ElectricityOrder(models.Model):
    """Tracks prepaid/postpaid electricity token purchases via the outbound VTU provider."""
    class Status(models.TextChoices):
        PENDING    = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS    = "SUCCESS", "Success"
        FAILED     = "FAILED", "Failed"

    class MeterType(models.TextChoices):
        PREPAID  = "prepaid",  "Prepaid"
        POSTPAID = "postpaid", "Postpaid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="electricity_orders")
    disco_id = models.CharField(max_length=20)
    disco_name = models.CharField(max_length=80)
    meter_number = models.CharField(max_length=30)
    meter_type = models.CharField(max_length=10, choices=MeterType.choices)
    customer_name = models.CharField(max_length=120, blank=True, default="", help_text="Account holder name returned by provider validation")
    address = models.CharField(max_length=200, blank=True, default="", help_text="Customer address supplied to the provider")
    phone = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    api_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference = models.CharField(max_length=50, unique=True)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    token = models.CharField(max_length=50, blank=True, default="", help_text="Electricity token from provider")
    units = models.CharField(max_length=20, blank=True, default="", help_text="kWh units credited")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "electricity_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"ElectricityOrder {self.reference} - {self.disco_name} ₦{self.amount}"


# ─────────────────────────────────────────────
# EXAM PINS
# ─────────────────────────────────────────────

class ExamProduct(models.Model):
    """
    Exam PIN products fetched from the outbound VTU provider.
    Synced periodically (every 6 hours).
    """
    product_id = models.CharField(max_length=80, unique=True, help_text="Provider exam product name")
    exam_name = models.CharField(max_length=50, help_text="e.g. WAEC, NECO, NABTEB")
    price_per_pin = models.DecimalField(max_digits=10, decimal_places=2)
    subhero_price_per_pin = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "exam_product"
        ordering = ["exam_name"]

    def __str__(self):
        return f"{self.exam_name} (₦{self.subhero_price_per_pin}/pin)"


class ExamPinOrder(models.Model):
    """Tracks exam PIN purchases and stores delivered PINs from the provider."""
    class Status(models.TextChoices):
        PENDING    = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SUCCESS    = "SUCCESS", "Success"
        FAILED     = "FAILED", "Failed"

    QUANTITY_CHOICES = [(1, "1 PIN"), (2, "2 PINs"), (5, "5 PINs")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_pin_orders")
    product_id = models.CharField(max_length=80)
    exam_name = models.CharField(max_length=50)
    quantity = models.PositiveSmallIntegerField(choices=QUANTITY_CHOICES, default=1)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    api_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference = models.CharField(max_length=50, unique=True)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    # Delivered PINs stored as newline-separated "serial<=>token" strings
    delivered_pins = models.TextField(blank=True, default="", help_text="Delivered PINs (newline separated)")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "exam_pin_order"
        ordering = ["-created_at"]

    def get_pins_list(self):
        """Returns PINs as a list."""
        if not self.delivered_pins:
            return []
        return [p.strip() for p in self.delivered_pins.splitlines() if p.strip()]

    def __str__(self):
        return f"ExamPinOrder {self.reference} - {self.exam_name} x{self.quantity}"

