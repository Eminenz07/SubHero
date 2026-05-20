"""
Accounts — Custom User Manager
================================
PRD Section 5.1: Custom user model with phone_number as USERNAME_FIELD.
"""

from django.contrib.auth.models import BaseUserManager

from apps.core.utils import normalize_phone


class UserManager(BaseUserManager):
    """Custom manager for User model with phone_number as identifier."""

    def _create_user(self, phone_number, email, password, **extra_fields):
        if not phone_number:
            raise ValueError("Phone number is required.")
        if not email:
            raise ValueError("Email is required.")

        phone_number = normalize_phone(phone_number)
        email = self.normalize_email(email).lower()
        user = self.model(phone_number=phone_number, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, phone_number, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone_number, email, password, **extra_fields)

    def create_superuser(self, phone_number, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        # Superusers are auto-verified
        extra_fields.setdefault("is_verified", True)

        return self._create_user(phone_number, email, password, **extra_fields)
