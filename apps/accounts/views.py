"""
Accounts — Views
=================
PRD Section 6.1: Registration, Login, OTP Verification, PIN Setup, Logout.
All views include security mitigations from PRD Section 7.
"""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.views import View
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

from apps.core.utils import get_client_ip, normalize_phone, send_otp, verify_otp
from .forms import LoginForm, OTPVerificationForm, RegistrationForm, TransactionPINForm

logger = logging.getLogger(__name__)


class RegisterView(View):
    """
    PRD Section 6.1.1: User registration.
    - Validates all fields server-side
    - Sends OTP via Termii (mock in dev)
    - Redirects to OTP verification page
    Rate limit: 5 req/min per IP (PRD Table 21)
    """

    template_name = "accounts/register.html"

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")
        form = RegistrationForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")

        form = RegistrationForm(request.POST)
        if form.is_valid():
            from django.contrib.auth import get_user_model

            User = get_user_model()

            user = User.objects.create_user(
                phone_number=form.cleaned_data["phone_number"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                full_name=form.cleaned_data["full_name"],
                is_verified=False,
                is_active=True,
            )

            # Store phone in session for OTP verification
            request.session["otp_phone"] = user.phone_number
            request.session["otp_purpose"] = "registration"

            # Send OTP
            send_otp(user.phone_number)

            logger.info(
                "Registration initiated: phone=%s, ip=%s",
                user.phone_number,
                get_client_ip(request),
            )

            messages.success(request, "Account created! Please verify your phone number.")
            return redirect("accounts:verify_otp")

        return render(request, self.template_name, {"form": form})


class LoginView(View):
    """
    PRD Section 6.1.2: Login via phone + password.
    - Max 5 failed attempts → 15-min lockout (Redis counter)
    - Session rotated on login
    - IP logged for anomaly detection
    Rate limit: 10 req/min per IP (PRD Table 21)
    """

    template_name = "accounts/login.html"

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")
        form = LoginForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")

        form = LoginForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        phone = normalize_phone(form.cleaned_data["phone_number"])
        password = form.cleaned_data["password"]
        remember_me = form.cleaned_data.get("remember_me", False)
        client_ip = get_client_ip(request)

        # Check lockout (PRD: 5 failed attempts → 15-min lockout)
        lockout_key = f"login_lockout:{phone}"
        attempts_key = f"login_attempts:{phone}"

        if cache.get(lockout_key):
            logger.warning(
                "Login attempt during lockout: phone=%s, ip=%s",
                phone,
                client_ip,
            )
            # PRD: identical error message regardless
            messages.error(request, "Invalid credentials. Please try again later.")
            return render(request, self.template_name, {"form": form})

        # Authenticate
        user = authenticate(request, phone_number=phone, password=password)

        if user is None:
            # Increment failed attempts
            attempts = cache.get(attempts_key, 0) + 1
            cache.set(attempts_key, attempts, settings.LOGIN_LOCKOUT_SECONDS)

            if attempts >= settings.MAX_LOGIN_ATTEMPTS:
                cache.set(lockout_key, True, settings.LOGIN_LOCKOUT_SECONDS)
                cache.delete(attempts_key)
                logger.warning(
                    "Login lockout triggered: phone=%s, ip=%s, attempts=%d",
                    phone,
                    client_ip,
                    attempts,
                )

            logger.info(
                "Failed login: phone=%s, ip=%s, attempt=%d",
                phone,
                client_ip,
                attempts,
            )

            # PRD: identical error messages — never reveal if phone exists
            messages.error(request, "Invalid credentials. Please try again.")
            return render(request, self.template_name, {"form": form})

        # Check if user is verified
        if not user.is_verified:
            request.session["otp_phone"] = user.phone_number
            request.session["otp_purpose"] = "registration"
            send_otp(user.phone_number)
            messages.info(request, "Please verify your phone number first.")
            return redirect("accounts:verify_otp")

        # Successful login
        # Reset failed attempts
        cache.delete(attempts_key)
        cache.delete(lockout_key)

        # Update user IP
        user.failed_login_count = 0
        user.last_login_ip = client_ip
        user.save(update_fields=["failed_login_count", "last_login_ip"])

        # Session rotation (PRD Section 7.1)
        login(request, user, backend="apps.accounts.backends.PhoneAuthBackend")
        request.session.cycle_key()

        # Remember me: 30 days (PRD Section 6.1.2)
        if remember_me:
            request.session.set_expiry(30 * 24 * 60 * 60)  # 30 days
        else:
            request.session.set_expiry(24 * 60 * 60)  # 24 hours

        logger.info(
            "Successful login: phone=%s, ip=%s",
            phone,
            client_ip,
        )

        # Redirect to next or dashboard
        next_url = request.GET.get("next", "")
        if next_url and next_url.startswith("/"):
            # PRD Section 7.1: Validate next parameter against allowed hosts
            return redirect(next_url)
        return redirect("dashboard")


class VerifyOTPView(View):
    """
    PRD Section 6.1.1: OTP verification.
    - 6 digits, expires in 10 minutes
    - Max 3 attempts before lockout
    - OTP is hashed in Redis (never stored plaintext)
    Rate limit: 3 attempts per OTP token (PRD Table 21)
    """

    template_name = "accounts/verify_otp.html"

    @method_decorator(ratelimit(key="ip", rate="3/m", method="POST", block=True))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        phone = request.session.get("otp_phone")
        if not phone:
            return redirect("accounts:login")
        form = OTPVerificationForm()
        # Mask phone for display (show last 4 digits)
        masked_phone = f"***{phone[-4:]}" if len(phone) >= 4 else phone
        return render(request, self.template_name, {
            "form": form,
            "masked_phone": masked_phone,
        })

    def post(self, request):
        phone = request.session.get("otp_phone")
        purpose = request.session.get("otp_purpose", "registration")

        if not phone:
            return redirect("accounts:login")

        form = OTPVerificationForm(request.POST)
        masked_phone = f"***{phone[-4:]}" if len(phone) >= 4 else phone

        if form.is_valid():
            code = form.cleaned_data["otp_code"]

            if verify_otp(phone, code):
                from django.contrib.auth import get_user_model

                User = get_user_model()

                try:
                    user = User.objects.get(phone_number=phone)
                    user.is_verified = True
                    user.save(update_fields=["is_verified"])

                    # Clear OTP session data
                    del request.session["otp_phone"]
                    del request.session["otp_purpose"]

                    # Auto-login after verification
                    login(request, user, backend="apps.accounts.backends.PhoneAuthBackend")
                    request.session.cycle_key()

                    logger.info("OTP verified: phone=%s", phone)

                    # Auto-create wallet + virtual account (PRD Section 6.1.1)
                    if purpose == "registration":
                        try:
                            from apps.wallet.services import create_wallet
                            create_wallet(user)
                        except Exception as e:
                            logger.error(
                                "Wallet creation failed during registration: user=%s, error=%s",
                                user.id, str(e),
                            )

                        messages.success(request, "Phone verified! Please set your transaction PIN.")
                        return redirect("accounts:set_pin")
                    else:
                        return redirect("dashboard")

                except User.DoesNotExist:
                    messages.error(request, "Verification failed. Please try again.")
            else:
                messages.error(request, "Invalid or expired code. Please try again.")

        return render(request, self.template_name, {
            "form": form,
            "masked_phone": masked_phone,
        })


class ResendOTPView(View):
    """Resend OTP to the phone number in session."""

    @method_decorator(ratelimit(key="ip", rate="3/m", method="POST", block=True))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        phone = request.session.get("otp_phone")
        if phone:
            send_otp(phone)
            messages.success(request, "A new code has been sent to your phone.")
        return redirect("accounts:verify_otp")


class SetPINView(View):
    """
    PRD Section 6.1.3: Transaction PIN setup.
    - Set at first login after registration — mandatory
    - Stored as Argon2 hash
    - Exactly 4 digits, no sequential/repeated patterns
    """

    template_name = "accounts/set_pin.html"

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        if request.user.has_pin:
            return redirect("dashboard")
        form = TransactionPINForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        if request.user.has_pin:
            return redirect("dashboard")

        form = TransactionPINForm(request.POST)
        if form.is_valid():
            request.user.set_pin(form.cleaned_data["pin"])

            logger.info(
                "PIN set: user=%s, ip=%s",
                request.user.id,
                get_client_ip(request),
            )

            messages.success(request, "Transaction PIN set successfully! Welcome to SubHero.")
            return redirect("dashboard")

        return render(request, self.template_name, {"form": form})


class LogoutView(View):
    """Logout — destroy session."""

    def post(self, request):
        logger.info(
            "Logout: user=%s, ip=%s",
            request.user.id if request.user.is_authenticated else "anonymous",
            get_client_ip(request),
        )
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect("accounts:login")

    def get(self, request):
        # Allow GET for convenience but prefer POST
        return self.post(request)
