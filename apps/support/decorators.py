"""
Support — Desk Decorators
=========================
Access controls for the Hero support staff desk.
Agents and leads can access the desk; leads have additional privileges.
No IP whitelist (distinct from admin_panel's admin_required).
"""

from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def support_required(view_func):
    """
    Access control: only authenticated staff members (is_staff=True)
    can access the support desk. Agents, leads, and admins all qualify.
    No IP whitelist is applied here.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            return redirect(f"{login_url}?next={request.path}")
        if not request.user.is_staff:
            return redirect("landing")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def lead_required(view_func):
    """
    Access control: only staff with staff_profile.role == 'lead' can access.
    Used for actions like reassigning tickets, approving refunds, viewing exam PINs.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            return redirect(f"{login_url}?next={request.path}")
        if not request.user.is_staff:
            return redirect("landing")
        try:
            if request.user.staff_profile.role != "lead":
                return redirect("landing")
        except AttributeError:
            return redirect("landing")
        return view_func(request, *args, **kwargs)
    return _wrapped_view
