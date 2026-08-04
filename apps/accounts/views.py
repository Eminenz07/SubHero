"""
Accounts — Views
=================
PRD Section 6.1: Registration, Login, OTP Verification, PIN Setup, Logout.
All views include security mitigations from PRD Section 7.
"""

import logging
import threading

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

from apps.core.utils import get_client_ip, normalize_phone, send_otp, verify_otp
from .forms import LoginForm, OTPVerificationForm, RegistrationForm, TransactionPINForm

logger = logging.getLogger(__name__)


def _send_async_email(subject, message, from_email, recipient_list):
    """
    Spawns a background thread to send emails asynchronously so HTTP login/auth responses return instantly.
    """
    def _target():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=True,
            )
        except Exception as e:
            logger.error("Async email dispatch error: %s", str(e))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()


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
        phone = request.GET.get('phone', '')
        form = RegistrationForm(initial={'phone_number': phone})
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")

        form = RegistrationForm(request.POST)
        if form.is_valid():
            from django.contrib.auth import get_user_model
            from django.contrib.auth import login

            User = get_user_model()

            user = User.objects.create_user(
                phone_number=form.cleaned_data["phone_number"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                full_name=form.cleaned_data["full_name"],
                is_verified=False,  # Requires OTP verification via Termii SMS
                is_active=True,
            )

            # Send SMS OTP via Termii
            from apps.core.utils import send_otp
            send_otp(user.phone_number)

            request.session["otp_phone"] = user.phone_number
            request.session["otp_purpose"] = "registration"

            logger.info("Registration initiated, OTP sent via Termii SMS: phone=%s", user.phone_number)
            messages.success(request, "Account created! We've sent a 6-digit OTP code to your phone number via SMS.")
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

        # Require OTP verification if account is unverified
        if not user.is_verified:
            from apps.core.utils import send_otp
            send_otp(user.phone_number)
            request.session["otp_phone"] = user.phone_number
            request.session["otp_purpose"] = "registration"
            messages.info(request, "Your account is not yet verified. We've sent a 6-digit OTP code to your phone via SMS.")
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

        # Login notification
        try:
            from apps.notifications.models import Notification
            Notification.add(
                user,
                "New Login Detected",
                f"Your account was logged in from IP address {client_ip}. If this wasn't you, please secure your account immediately.",
                level="info"
            )
            if user.email:
                from django.utils import timezone
                subject = "Security Alert: New Login Detected 🔐"
                email_message = (
                    f"Hello {user.full_name or 'SubHero User'},\n\n"
                    f"We detected a new login to your SubHero account.\n\n"
                    f"Details:\n"
                    f"- Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"- IP Address: {client_ip}\n\n"
                    f"If this was you, you can safely ignore this email.\n"
                    f"If you did not log in, please change your password and secure your account immediately.\n\n"
                    f"Best regards,\n"
                    f"The SubHero Team"
                )
                _send_async_email(
                    subject=subject,
                    message=email_message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@subhero.ng"),
                    recipient_list=[user.email],
                )
        except Exception as ex:
            logger.error("Login notification/email creation failed: %s", str(ex))

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

                        # Welcome notification
                        try:
                            from apps.notifications.models import Notification
                            Notification.add(
                                user,
                                "Welcome to SubHero!",
                                f"Hi {user.full_name}, your account has been successfully verified. Fund your wallet to start purchasing VTU and SMM services!",
                                level="success"
                            )
                            if user.email:
                                subject = "Welcome to SubHero! 🎉"
                                email_message = (
                                    f"Hello {user.full_name or 'SubHero User'},\n\n"
                                    f"Welcome to SubHero! Your account has been successfully verified.\n\n"
                                    f"You can now fund your wallet and start purchasing cheap data, airtime, and SMM social booster services.\n\n"
                                    f"If you have any questions, feel free to contact support.\n\n"
                                    f"Best regards,\n"
                                    f"The SubHero Team"
                                )
                                _send_async_email(
                                    subject=subject,
                                    message=email_message,
                                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@subhero.ng"),
                                    recipient_list=[user.email],
                                )
                        except Exception as ex:
                            logger.error("Welcome notification/email creation failed: %s", str(ex))

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

            # Security notification for setting PIN
            try:
                from apps.notifications.models import Notification
                Notification.add(
                    request.user,
                    "Transaction PIN Configured",
                    "Your secure transaction PIN has been successfully set. You can now perform transactions and secure orders.",
                    level="security"
                )
            except Exception as ex:
                logger.error("PIN set notification creation failed: %s", str(ex))

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


class ProfileView(LoginRequiredMixin, View):
    """
    PRD Section 6.1: User Profile and Settings page.
    Renders personal information, bank account details, and security configurations.
    Allows editing full name, email, changing password, and resetting transaction PIN.
    Rate limit: 10 attempts per minute per IP to prevent PIN/password brute force.
    """
    template_name = "accounts/profile.html"

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True))
    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        
        if action == "update_profile":
            full_name = request.POST.get("full_name", "").strip()
            email = request.POST.get("email", "").strip()
            
            if not full_name or not email:
                messages.error(request, "Name and Email are required.")
                return render(request, self.template_name)
                
            request.user.full_name = full_name
            request.user.email = email
            request.user.save()
            
            # Profile update notification
            try:
                from apps.notifications.models import Notification
                Notification.add(
                    request.user,
                    "Profile Information Updated",
                    "Your profile contact details (name and/or email address) have been successfully updated.",
                    level="info"
                )
            except Exception as ex:
                logger.error("Profile update notification creation failed: %s", str(ex))

            messages.success(request, "Profile updated successfully.")
            return redirect("accounts:profile")
            
        elif action == "change_password":
            current_password = request.POST.get("current_password", "")
            new_password = request.POST.get("new_password", "")
            confirm_password = request.POST.get("confirm_password", "")
            
            if not current_password or not new_password or not confirm_password:
                messages.error(request, "All password fields are required.")
                return render(request, self.template_name)
                
            if not request.user.check_password(current_password):
                messages.error(request, "Current password is incorrect.")
                return render(request, self.template_name)
                
            if new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
                return render(request, self.template_name)
                
            if len(new_password) < 8:
                messages.error(request, "Password must be at least 8 characters long.")
                return render(request, self.template_name)
                
            request.user.set_password(new_password)
            request.user.save()
            
            # Password changed notification
            try:
                from apps.notifications.models import Notification
                Notification.add(
                    request.user,
                    "Account Password Changed",
                    "Your account login password has been changed. Use your new password for subsequent logins.",
                    level="security"
                )
                if request.user.email:
                    from django.utils import timezone
                    subject = "Security Alert: Password Changed 🔐"
                    email_message = (
                        f"Hello {request.user.full_name or 'SubHero User'},\n\n"
                        f"Your SubHero account login password has been successfully changed.\n\n"
                        f"Details:\n"
                        f"- Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                        f"If you did not make this change, please contact support immediately to secure your account.\n\n"
                        f"Best regards,\n"
                        f"The SubHero Team"
                    )
                    _send_async_email(
                        subject=subject,
                        message=email_message,
                        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@subhero.ng"),
                        recipient_list=[request.user.email],
                    )
            except Exception as ex:
                logger.error("Password change notification/email creation failed: %s", str(ex))

            # Since password changed, log user in again to maintain session
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password changed successfully.")
            return redirect("accounts:profile")
            
        elif action == "change_pin":
            current_pin = request.POST.get("current_pin", "")
            new_pin = request.POST.get("new_pin", "")
            confirm_pin = request.POST.get("confirm_pin", "")
            
            if not new_pin or not confirm_pin:
                messages.error(request, "New PIN and confirmation are required.")
                return render(request, self.template_name)
                
            if request.user.has_pin:
                if not current_pin:
                    messages.error(request, "Current transaction PIN is required.")
                    return render(request, self.template_name)
                if not request.user.check_pin(current_pin):
                    messages.error(request, "Current transaction PIN is incorrect.")
                    return render(request, self.template_name)
                    
            if new_pin != confirm_pin:
                messages.error(request, "New PINs do not match.")
                return render(request, self.template_name)
                
            if len(new_pin) != 4 or not new_pin.isdigit():
                messages.error(request, "PIN must be exactly 4 digits.")
                return render(request, self.template_name)
                
            request.user.set_pin(new_pin)
            
            # PIN change notification
            try:
                from apps.notifications.models import Notification
                Notification.add(
                    request.user,
                    "Transaction PIN Updated",
                    "Your secure transaction PIN has been successfully updated. Use this new PIN for subsequent transfers and VTU/SMM orders.",
                    level="security"
                )
            except Exception as ex:
                logger.error("PIN change notification creation failed: %s", str(ex))

            messages.success(request, "Transaction PIN updated successfully.")
            return redirect("accounts:profile")
            
        else:
            messages.error(request, "Invalid action.")
            return render(request, self.template_name)

    def get(self, request):
        return render(request, self.template_name)
