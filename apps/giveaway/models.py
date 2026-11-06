import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.timezone import now

class Giveaway(models.Model):
    TYPES = [('DATA','Data'),('AIRTIME','Airtime')]
    NETWORKS = [('mtn','MTN'),('airtel','Airtel'),
                ('glo','Glo'),('9mobile','9mobile'),
                ('all','All Networks')]
    STATUS = [('ACTIVE','Active'),('COMPLETED','Completed'),
              ('EXPIRED','Expired'),('CANCELLED','Cancelled')]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='giveaways')
    slug            = models.CharField(max_length=20, unique=True)
    title           = models.CharField(max_length=100, default='Data Giveaway')
    giveaway_type   = models.CharField(max_length=10, choices=TYPES)
    network         = models.CharField(max_length=10, choices=NETWORKS)
    plan_id         = models.CharField(max_length=80, blank=True)
    amount_per_slot = models.DecimalField(max_digits=10, decimal_places=2)
    total_slots     = models.IntegerField()
    claimed_slots   = models.IntegerField(default=0)
    total_locked    = models.DecimalField(max_digits=12, decimal_places=2)
    total_spent     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status          = models.CharField(max_length=15, choices=STATUS, default='ACTIVE')
    qr_code_base64  = models.TextField(blank=True, help_text="Base64 encoded QR Code PNG")
    expires_at      = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    @property
    def remaining_slots(self):
        return self.total_slots - self.claimed_slots

    @property
    def claim_url(self):
        from django.conf import settings
        site_url = settings.SITE_URL.rstrip('/')
        return f'{site_url}/g/{self.slug}'

    @property
    def is_claimable(self):
        if self.status != 'ACTIVE':
            return False
        if self.remaining_slots <= 0:
            return False
        if self.expires_at and self.expires_at < now():
            return False
        return True

    @property
    def host_display(self):
        if self.host:
            return self.host.full_name or self.host.phone_number or "SubHero User"
        return "SubHero User"

    @property
    def prize_display(self):
        if self.giveaway_type == 'DATA':
            return f"{self.plan_id} Data" if self.plan_id else "Free Data"
        return f"₦{int(self.amount_per_slot):,} Airtime"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('giveaway_short_link', kwargs={'slug': self.slug})


class GiveawayClaim(models.Model):
    STATUS = [('PENDING','Pending'),('SUCCESS','Success'),
              ('FAILED','Failed')]

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    giveaway      = models.ForeignKey(Giveaway, on_delete=models.CASCADE, related_name='claims')
    phone_number  = models.CharField(max_length=15)
    amount        = models.DecimalField(max_digits=10, decimal_places=2)
    provider_ref  = models.CharField(max_length=100, blank=True)
    status        = models.CharField(max_length=10, choices=STATUS, default='PENDING')
    ip_address    = models.GenericIPAddressField(null=True, blank=True)
    claimed_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['giveaway', 'phone_number']]


class GiveawayEscrow(models.Model):
    giveaway        = models.OneToOneField(Giveaway, on_delete=models.CASCADE, related_name='escrow')
    wallet          = models.ForeignKey('wallet.Wallet', on_delete=models.CASCADE)
    locked_amount   = models.DecimalField(max_digits=12, decimal_places=2)
    released_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    debit_reference = models.CharField(max_length=100)
    created_at      = models.DateTimeField(auto_now_add=True)
