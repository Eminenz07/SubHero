"""
Accounts — User Model
======================
PRD Section 5.1: Custom User with UUID PK, phone auth, Argon2 PIN.
All fields match PRD Table 7 exactly.
"""

import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.core.utils import generate_reference
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for SubHero.
    UUID primary key — prevents enumeration attacks (PRD Section 7).
    Phone number is the login identifier (PRD Section 6.1.2).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    phone_number = models.CharField(
        max_length=15,
        unique=True,
        help_text="Nigerian phone number in E.164 format (+234XXXXXXXXXX)",
    )
    email = models.EmailField(
        unique=True,
        help_text="Lowercased on save",
    )
    full_name = models.CharField(
        max_length=150,
        help_text="Required at registration",
    )

    # Transaction PIN — Argon2 hashed (PRD Section 6.1.3)
    pin_hash = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Argon2 hashed 4-digit transaction PIN",
    )

    # Verification
    is_verified = models.BooleanField(
        default=False,
        help_text="Phone OTP verified",
    )

    # Account status
    is_active = models.BooleanField(
        default=True,
        help_text="Account active/suspended flag",
    )
    is_staff = models.BooleanField(
        default=False,
    )

    # Security tracking
    failed_login_count = models.IntegerField(
        default=0,
        help_text="Brute force lockout counter",
    )
    last_login_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Stored for anomaly detection",
    )

    # Timestamps
    date_joined = models.DateTimeField(auto_now_add=True)

    # Referral (Phase 2)
    referral_code = models.CharField(
        max_length=12,
        unique=True,
        blank=True,
        help_text="Auto-generated — Phase 2 use",
    )

    # Manager
    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["email", "full_name"]

    class Meta:
        db_table = "accounts_user"
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"

    def save(self, *args, **kwargs):
        # Lowercase email on save (PRD Section 5.1)
        if self.email:
            self.email = self.email.lower()

        # Auto-generate referral code if not set
        if not self.referral_code:
            self.referral_code = generate_reference("REF")[:12]

        super().save(*args, **kwargs)

    # ----------------------------------------------------------
    # Transaction PIN methods (PRD Section 6.1.3)
    # ----------------------------------------------------------
    def set_pin(self, raw_pin):
        """Hash and store the transaction PIN using Argon2."""
        self.pin_hash = make_password(raw_pin, hasher="argon2")
        self.save(update_fields=["pin_hash"])

    def check_pin(self, raw_pin):
        """Verify a raw PIN against the stored Argon2 hash."""
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

    @property
    def has_pin(self):
        """Check if user has set their transaction PIN."""
        return bool(self.pin_hash)

    @property
    def first_name(self):
        """Extract first name from full_name."""
        if self.full_name:
            return self.full_name.strip().split()[0]
        return ""

    def get_full_name(self):
        """Return full name or fallback identifier."""
        return self.full_name or self.phone_number or self.email
