"""
Core — Middleware
==================
1. PinSetupMiddleware: PIN setup enforcement middleware.
2. ErrorAlertMiddleware: Immediate 500 error email notification to admin with diagnostics and deduplication.
"""

import logging
import traceback
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from apps.core.email import send_async_app_email

logger = logging.getLogger(__name__)


class PinSetupMiddleware:
    """
    Redirects authenticated users without a transaction PIN to the
    PIN setup page. Skips admin URLs and auth URLs to avoid loops.
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

            # Anti-spam rate limiting: 1 email per exception type & endpoint per 10 minutes
            cache_key = f"err_alert:{exc_type}:{endpoint}"
            if cache.get(cache_key):
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
