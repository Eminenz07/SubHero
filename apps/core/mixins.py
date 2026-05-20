"""
Core — Mixins
==============
Shared view mixins for authentication and PIN enforcement.
"""

from django.contrib.auth.mixins import LoginRequiredMixin as DjangoLoginRequiredMixin
from django.shortcuts import redirect


class LoginRequiredMixin(DjangoLoginRequiredMixin):
    """Custom LoginRequiredMixin that redirects to SubHero login URL."""

    login_url = "/auth/login/"
    redirect_field_name = "next"


class PinRequiredMixin:
    """
    Mixin that ensures the user has set their transaction PIN
    before accessing financial views.
    Redirects to /auth/set-pin/ if PIN is not set.
    """

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_pin:
            return redirect("accounts:set_pin")
        return super().dispatch(request, *args, **kwargs)
