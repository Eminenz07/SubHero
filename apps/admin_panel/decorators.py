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

from .models import SystemSetting


def staff_required(view_func):
    """
    Access Control: Only allows authenticated users with is_staff = True.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # Redirect to auth login with next parameter
            login_url = reverse("accounts:login")
            return redirect(f"{login_url}?next={request.path}")
            
        if not request.user.is_staff:
            # Authenticated but not staff — redirect to landing
            return redirect("landing")
            
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
            
        # Get client IP address
        ip_addr = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
        if ip_addr and "," in ip_addr:
            ip_addr = ip_addr.split(",")[0].strip()
        else:
            ip_addr = ip_addr.strip()
            
        # Parse allowed IPs
        allowed_ips = [ip.strip() for ip in whitelist_str.split(",") if ip.strip()]
        
        if ip_addr not in allowed_ips:
            raise PermissionDenied(f"Access Denied: IP address '{ip_addr}' not whitelisted.")
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def admin_required(view_func):
    """
    Combined decorator: staff member validation + IP whitelist checks.
    """
    return staff_required(ip_whitelist(view_func))
