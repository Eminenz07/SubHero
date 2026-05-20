"""
Core — Middleware
==================
PIN setup enforcement middleware.
"""

from django.shortcuts import redirect
from django.urls import reverse


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
