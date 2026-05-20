"""
Wallet — Forms
================
PRD Section 6.2.3: P2P transfers and wallet operations.
All monetary inputs validated server-side — client-side is UX only.
"""

from decimal import Decimal

from django import forms
from django.conf import settings

from apps.core.utils import normalize_phone
from apps.core.validators import validate_nigerian_phone


class P2PTransferForm(forms.Form):
    """
    Form for P2P user-to-user transfers.
    PRD Section 6.2.3: Min ₦50, Max ₦100,000.
    """

    recipient_phone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. 08012345678",
            "class": "form-input",
            "inputmode": "tel",
            "autocomplete": "off",
        }),
        label="Recipient Phone Number",
    )

    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal(str(settings.P2P_MIN_AMOUNT)),
        max_value=Decimal(str(settings.P2P_MAX_AMOUNT)),
        widget=forms.NumberInput(attrs={
            "placeholder": "0.00",
            "class": "form-input",
            "inputmode": "decimal",
            "autocomplete": "off",
        }),
        label="Amount (₦)",
    )

    pin = forms.CharField(
        max_length=4,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            "placeholder": "••••",
            "class": "form-input text-center tracking-[0.5em] font-mono text-xl",
            "inputmode": "numeric",
            "maxlength": "4",
            "autocomplete": "off",
        }),
        label="Transaction PIN",
    )

    def clean_recipient_phone(self):
        phone = self.cleaned_data["recipient_phone"]
        phone = normalize_phone(phone)
        validate_nigerian_phone(phone)
        return phone

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount < settings.P2P_MIN_AMOUNT:
            raise forms.ValidationError(f"Minimum transfer is ₦{settings.P2P_MIN_AMOUNT}")
        if amount > settings.P2P_MAX_AMOUNT:
            raise forms.ValidationError(f"Maximum transfer is ₦{settings.P2P_MAX_AMOUNT:,}")
        return amount
