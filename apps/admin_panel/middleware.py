"""
Admin Panel — Middleware
========================
Handles global maintenance mode redirecting standard users during system updates.
"""

from django.shortcuts import render
from django.conf import settings
from .models import SystemSetting


class MaintenanceModeMiddleware:
    """
    Blocks non-staff users from accessing user-facing pages when maintenance mode is active.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Staff users always pass through
        if request.user.is_authenticated and request.user.is_staff:
            return self.get_response(request)

        # 2. Check if maintenance mode is enabled
        is_maintenance = SystemSetting.get("maintenance_mode", "False") == "True"
        if is_maintenance:
            path = request.path
            admin_hq_path = f"/{settings.ADMIN_HQ_URL.lstrip('/')}"
            admin_django_path = f"/{settings.ADMIN_URL.lstrip('/')}"

            # 3. Allow static files, media files, auth URLs, admin HQ paths and
            #    provider webhook callbacks to prevent lockouts and dropped events
            if not (
                path.startswith(admin_hq_path) or
                path.startswith(admin_django_path) or
                path.startswith("/auth/") or
                path.startswith("/static/") or
                path.startswith("/media/") or
                path.startswith("/vtu/webhooks/") or
                path.startswith("/manifest.json") or
                path.startswith("/sw.js")
            ):
                # Render the maintenance template with a 503 service unavailable status
                return render(request, "admin_panel/maintenance.html", status=503)

        return self.get_response(request)
