"""
Admin Panel — Decorators
========================
Defines security access controls for HQ admin sections including IP whitelisting
and staff verification.
"""

from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.http import HttpResponseForbidden

from apps.core.utils import get_client_ip
from .models import SystemSetting


def _is_support_staff_role(user):
    """True if the user has a StaffProfile with role agent or lead."""
    if not user.is_authenticated or not user.is_staff:
        return False
    try:
        return user.staff_profile.role in ("agent", "lead")
    except AttributeError:
        return False


def staff_required(view_func):
    """
    Access Control: Only allows authenticated users with is_staff = True.
    Blocks support desk staff (agent/lead roles) from admin_panel URLs —
    they reach only /support/desk/. Existing admins (superusers or staff
    without an agent/lead profile) are allowed.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            return redirect(f"{login_url}?next={request.path}")

        if not request.user.is_staff:
            return redirect("landing")

        # Block agent/lead support staff from admin_panel URLs.
        if _is_support_staff_role(request.user):
            return HttpResponseForbidden(
                "Support desk staff are not permitted to access admin panel URLs."
            )

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def ip_whitelist(view_func):
    """
    Access Control: Enforces a strict IP address whitelist read from SystemSetting.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        whitelist_str = SystemSetting.get("admin_ip_whitelist", "").strip()
        if not whitelist_str:
            # Whitelist is empty — developer mode, allow all
            return view_func(request, *args, **kwargs)

        # Get client IP address securely (supports CF-Connecting-IP, X-Real-IP, and X-Forwarded-For)
        ip_addr = get_client_ip(request)

        # Parse allowed IPs
        allowed_ips = [ip.strip() for ip in whitelist_str.split(",") if ip.strip()]

        if ip_addr not in allowed_ips:
            raise PermissionDenied(f"Access Denied: IP address '{ip_addr}' not whitelisted.")

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def admin_required(view_func):
    """
    Combined decorator: staff member validation + IP whitelist checks.
    Blocks support desk staff (agent/lead roles).
    """
    return staff_required(ip_whitelist(view_func))


def promo_admin_required(view_func):
    """
    Access Control for promo campaign management: admin only, never for
    support staff roles (agent/lead). Requires is_staff and no support
    staff profile.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            return redirect(f"{login_url}?next={request.path}")
        if not request.user.is_staff:
            return redirect("landing")
        # Exclude support staff roles (agent / lead) — promos are admin-only.
        try:
            if request.user.staff_profile.role in ("agent", "lead"):
                return redirect("landing")
        except AttributeError:
            pass  # no support profile = true admin
        return view_func(request, *args, **kwargs)
    return _wrapped_view
