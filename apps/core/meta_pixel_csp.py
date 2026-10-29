"""
CSP Middleware for Meta Pixel
==============================
Adds Content-Security-Policy headers to whitelist Facebook/Meta domains
for Meta Pixel tracking.
"""

from django.conf import settings


class MetaPixelCSPMiddleware:
    """
    Adds Content-Security-Policy headers to allow Meta Pixel to load
    and send events. Only applied in production.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only add CSP in production (DEBUG=False)
        if not settings.DEBUG:
            # Build CSP directives
            csp_directives = [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://connect.facebook.net https://www.facebook.com",
                "img-src 'self' data: https://www.facebook.com https://www.facebook.com",
                "connect-src 'self' https://connect.facebook.net https://www.facebook.com https://graph.facebook.com",
                "frame-src 'self' https://www.facebook.com",
                "font-src 'self' data: https://fonts.gstatic.com",
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                "frame-ancestors 'self'",
                "form-action 'self'",
            ]

            # Only add CSP if not already set (e.g., by other middleware)
            if "Content-Security-Policy" not in response:
                response["Content-Security-Policy"] = "; ".join(csp_directives)

        return response