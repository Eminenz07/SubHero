"""
Accounts — Validators
======================
PRD Section 7.4: All user input validated server-side.
"""

import re

from django.core.exceptions import ValidationError


def validate_nigerian_phone(value):
    """
    Validate Nigerian phone number.
    Accepts: +234XXXXXXXXXX or 0XXXXXXXXXX
    PRD: Phone number must be Nigerian format — validated with regex (+234 or 0XX)
    """
    pattern = r"^(\+234|0)[789][01]\d{8}$"
    if not re.match(pattern, value):
        raise ValidationError(
            "Enter a valid Nigerian phone number (e.g., 08012345678)."
        )


def validate_password_strength(value):
    """
    PRD Section 6.1.1: Minimum 8 characters, must contain letter + number.
    """
    if len(value) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if not re.search(r"[a-zA-Z]", value):
        raise ValidationError("Password must contain at least one letter.")
    if not re.search(r"\d", value):
        raise ValidationError("Password must contain at least one number.")


def validate_pin(value):
    """
    Validate transaction PIN.
    PRD Section 6.1.3: 4-digit PIN.
    Also reject sequential/repeated patterns for security.
    """
    if not re.match(r"^\d{4}$", value):
        raise ValidationError("PIN must be exactly 4 digits.")

    # Reject sequential patterns (1234, 4321, etc.)
    sequential = ["0123", "1234", "2345", "3456", "4567", "5678", "6789", "9876", "8765", "7654", "6543", "5432", "4321", "3210"]
    if value in sequential:
        raise ValidationError("PIN cannot be a sequential number pattern.")

    # Reject all same digits (0000, 1111, etc.)
    if len(set(value)) == 1:
        raise ValidationError("PIN cannot be all the same digit.")
