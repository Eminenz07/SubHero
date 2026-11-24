"""
Core — Middleware
==================
1. PinSetupMiddleware: PIN setup enforcement middleware (exempts staff).
2. StaffSessionTimeoutMiddleware: Staff idle (30 min) and max (8 hr) session limits.
3. ErrorAlertMiddleware: Immediate 500 error email notification to admin with diagnostics and deduplication.
"""

import logging
import traceback
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from apps.core.email import send_async_app_email
from apps.support.models import StaffProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Staff session timeout settings (configurable via env)
# ---------------------------------------------------------------------------
STAFF_IDLE_TIMEOUT_SECONDS = int(getattr(settings, "STAFF_IDLE_TIMEOUT_SECONDS", 30 * 60))   # 30 min
STAFF_MAX_SESSION_SECONDS = int(getattr(settings, "STAFF_MAX_SESSION_SECONDS", 8 * 60 * 60))  # 8 hr


class PinSetupMiddleware:
    """
    Redirects authenticated users without a transaction PIN to the
    PIN setup page. Skips admin URLs, auth URLs, and STAFF users to avoid
    loops — staff accounts do not need a transaction PIN or wallet.
    PRD Section 6.1.3: PIN is mandatory before wallet is active.
    """

    EXEMPT_URLS = [
        "/auth/",
        "/static/",
        "/media/",
        "/notifications/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Staff accounts are exempt from PIN/wallet requirements.
            if request.user.is_staff:
                return self.get_response(request)

            path = request.path

            # Skip exempt URLs (auth pages, static, admin)
            is_exempt = any(path.startswith(url) for url in self.EXEMPT_URLS)
            is_admin = path.startswith(f"/{getattr(request, '_admin_url', 'admin/')}")

            if not is_exempt and not is_admin:
                # Check if user has set their PIN
                if not request.user.has_pin and path != reverse("accounts:set_pin"):
                    return redirect("accounts:set_pin")

        response = self.get_response(request)
        return response


class StaffSessionTimeoutMiddleware:
    """
    Enforces staff session limits:
      - 30-minute idle timeout (resets on each request)
      - 8-hour maximum session length since login
    Only applies to authenticated staff users on /desk/ paths.
    """

    STAFF_PASSWORD_CHANGE_URLS = [
        "/support/desk/change-password/",
        "/support/desk/login/",
        "/support/desk/logout/",
        "/auth/logout/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.is_staff:
            path = request.path
            is_desk = path.startswith("/support/desk/") or path.startswith(f"/{getattr(settings, 'ADMIN_HQ_URL', 'subhero-hq/')}/")
            if is_desk:
                # Force password change if required (exempt the change-password page itself)
                is_pw_change_path = any(path.startswith(u) for u in self.STAFF_PASSWORD_CHANGE_URLS)
                try:
                    sp = request.user.staff_profile
                    if sp.must_change_password and not is_pw_change_path:
                        return redirect("support:desk:staff_change_password")
                except StaffProfile.DoesNotExist:
                    pass

                now = timezone.now()
                start = request.session.get("staff_session_start")
                last_activity = request.session.get("staff_last_activity")

                # Max session age check
                if start:
                    try:
                        started = timezone.datetime.fromisoformat(start)
                        if timezone.is_naive(started):
                            started = timezone.make_aware(started)
                        if (now - started).total_seconds() > STAFF_MAX_SESSION_SECONDS:
                            from django.contrib.auth import logout
                            logout(request)
                            return redirect("support:desk:staff_login")
                    except (ValueError, OSError):
                        request.session["staff_session_start"] = now.isoformat()

                # Idle timeout check
                if last_activity:
                    try:
                        last = timezone.datetime.fromisoformat(last_activity)
                        if timezone.is_naive(last):
                            last = timezone.make_aware(last)
                        if (now - last).total_seconds() > STAFF_IDLE_TIMEOUT_SECONDS:
                            from django.contrib.auth import logout
                            logout(request)
                            return redirect("desk:staff_login")
                    except (ValueError, OSError):
                        pass

                # Refresh idle timestamp
                request.session["staff_last_activity"] = now.isoformat()

        response = self.get_response(request)
        return response


class ErrorAlertMiddleware:
    """
    Catches unhandled server exceptions (500 errors) and immediately
    dispatches a formatted, high-priority email alert to the admin with
    user info, endpoint, and stack trace details.
    Includes smart rate-limiting via cache to prevent email storms.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # Ignore normal expected client errors (404, 403, suspicious scans)
        if isinstance(exception, (Http404, SuspiciousOperation, PermissionDenied)):
            return None

        try:
            admin_email = getattr(settings, "ADMIN_ALERT_EMAIL", "subherong@gmail.com")
            if not admin_email:
                return None

            endpoint = request.path
            exc_type = exception.__class__.__name__
            exc_message = str(exception)
            tb = traceback.format_exc()

            # Anti-spam rate limiting: 1 email per exception type & endpoint per 10 minutes (bypass if ?force=1)
            is_forced = bool(request.GET.get("force"))
            cache_key = f"err_alert:{exc_type}:{endpoint}"
            if not is_forced and cache.get(cache_key):
                logger.info("Error alert throttled for %s at %s", exc_type, endpoint)
                return None

            cache.set(cache_key, True, timeout=600)  # 10 minutes

            # Extract user info
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                user_info = f"{user.full_name or user.username} (ID: {user.id}, Email: {user.email}, Phone: {getattr(user, 'phone_number', 'N/A')})"
            else:
                user_info = "Guest / Unauthenticated Visitor"

            # Extract client IP
            cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
            x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            client_ip = cf_ip or (x_forwarded.split(",")[0].strip() if x_forwarded else request.META.get("REMOTE_ADDR", "Unknown"))

            context = {
                "exc_type": exc_type,
                "exc_message": exc_message,
                "endpoint": endpoint,
                "method": request.method,
                "full_url": request.build_absolute_uri(),
                "user_info": user_info,
                "client_ip": client_ip,
                "timestamp": timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "traceback": tb,
            }

            html_content = render_to_string("emails/admin_error_alert.html", context)
            subject = f"🚨 [SubHero Error Alert] {exc_type} on {endpoint}"

            send_async_app_email(
                subject=subject,
                recipient_email=admin_email,
                html_content=html_content,
            )
            logger.info("Immediate error alert dispatched to %s for %s on %s", admin_email, exc_type, endpoint)

        except Exception as e:
            logger.error("Failed to dispatch error alert email: %s", e)

        return None
