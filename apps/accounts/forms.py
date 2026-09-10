"""
Accounts — Forms
=================
All forms use explicit Meta.fields — never "__all__" (PRD Section 7.1).
All validation is server-side (PRD Section 7.4).
"""

from django import forms
from django.contrib.auth import get_user_model

from apps.core.utils import normalize_phone
from .validators import validate_nigerian_phone, validate_password_strength, validate_pin

User = get_user_model()


class RegistrationForm(forms.Form):
    """
    PRD Section 6.1.1: Registration form.
    Fields: Full Name, Phone Number, Email, Password, Confirm Password.
    """

    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "placeholder": "Full Name",
            "autocomplete": "name",
            "class": "form-input",
        }),
    )
    phone_number = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={
            "placeholder": "08012345678",
            "autocomplete": "tel",
            "inputmode": "tel",
            "class": "form-input",
            "type": "tel",
        }),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "you@example.com",
            "autocomplete": "email",
            "class": "form-input",
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password (8+ chars, letter + number)",
            "autocomplete": "new-password",
            "class": "form-input",
        }),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Confirm Password",
            "autocomplete": "new-password",
            "class": "form-input",
        }),
    )

    def clean_phone_number(self):
        phone = self.cleaned_data["phone_number"]
        phone = normalize_phone(phone)
        validate_nigerian_phone(phone)

        if User.objects.filter(phone_number=phone).exists():
            # PRD: Return identical error messages to prevent enumeration
            raise forms.ValidationError("Unable to complete registration. Please try again.")
        return phone

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            # PRD: Return identical error messages to prevent enumeration
            raise forms.ValidationError("Unable to complete registration. Please try again.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password_strength(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")

        return cleaned_data


class LoginForm(forms.Form):
    """
    PRD Section 6.1.2: Login via phone number + password.
    """

    phone_number = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={
            "placeholder": "Phone Number",
            "autocomplete": "tel",
            "inputmode": "tel",
            "class": "form-input",
            "type": "tel",
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "autocomplete": "current-password",
            "class": "form-input",
        }),
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            "class": "form-checkbox",
        }),
    )


class OTPVerificationForm(forms.Form):
    """
    PRD Section 6.1.1: 6-digit OTP verification.
    """

    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter 6-digit code",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "pattern": "[0-9]{6}",
            "class": "form-input form-input--otp",
            "maxlength": "6",
        }),
    )

    def clean_otp_code(self):
        code = self.cleaned_data["otp_code"].strip()
        if not code.isdigit() or len(code) != 6:
            raise forms.ValidationError("Enter a valid 6-digit code.")
        return code


class TransactionPINForm(forms.Form):
    """
    PRD Section 6.1.3: 4-digit transaction PIN setup.
    """

    pin = forms.CharField(
        max_length=4,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Enter 4-digit PIN",
            "inputmode": "numeric",
            "pattern": "[0-9]{4}",
            "class": "form-input form-input--pin",
            "maxlength": "4",
            "autocomplete": "off",
        }),
    )
    confirm_pin = forms.CharField(
        max_length=4,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Confirm PIN",
            "inputmode": "numeric",
            "pattern": "[0-9]{4}",
            "class": "form-input form-input--pin",
            "maxlength": "4",
            "autocomplete": "off",
        }),
    )

    def clean_pin(self):
        pin = self.cleaned_data["pin"]
        validate_pin(pin)
        return pin

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        confirm_pin = cleaned_data.get("confirm_pin")

        if pin and confirm_pin and pin != confirm_pin:
            self.add_error("confirm_pin", "PINs do not match.")

        return cleaned_data


class ForgotPasswordForm(forms.Form):
    """
    Form to request a password reset OTP using registered email or phone number.
    """
    identifier = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. user@gmail.com or 08012345678",
            "class": "form-input",
            "id": "identifier",
            "autofocus": "autofocus",
        }),
    )

    def clean_identifier(self):
        return self.cleaned_data["identifier"].strip()


class VerifyResetOTPForm(forms.Form):
    """
    Form to verify 6-digit reset code before creating a new password.
    """
    reset_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "placeholder": "123456",
            "class": "form-input font-mono font-bold tracking-widest text-center text-lg",
            "id": "reset_code",
            "maxlength": "6",
            "inputmode": "numeric",
            "pattern": "[0-9]*",
        }),
    )

    def clean_reset_code(self):
        code = self.cleaned_data["reset_code"].strip()
        if not code.isdigit() or len(code) != 6:
            raise forms.ValidationError("Enter a valid 6-digit code.")
        return code


class SetNewPasswordForm(forms.Form):
    """
    Form to set a new password after confirming reset OTP.
    """
    new_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Min 8 characters",
            "class": "form-input pr-11",
            "id": "new_password",
            "autocomplete": "new-password",
        }),
    )
    confirm_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Repeat new password",
            "class": "form-input pr-11",
            "id": "confirm_password",
            "autocomplete": "new-password",
        }),
    )

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        validate_password_strength(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")

        return cleaned_data


# Alias for backward compatibility
ResetPasswordForm = SetNewPasswordForm

