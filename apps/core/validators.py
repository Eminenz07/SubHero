"""
Core — Shared Validators
==========================
"""

import re

from django.core.exceptions import ValidationError


def validate_nigerian_phone(value):
    """
    Validate Nigerian phone number format.
    Accepts: +234XXXXXXXXXX (E.164), 0XXXXXXXXXX (local).
    PRD Section 7.4: Validated with regex for Nigerian numbers.
    """
    pattern = r"^(\+234|0)[789][01]\d{8}$"
    if not re.match(pattern, value):
        raise ValidationError(
            "Enter a valid Nigerian phone number (e.g., +2348012345678 or 08012345678)."
        )
