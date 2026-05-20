"""
Accounts — Admin Configuration
================================
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("phone_number", "full_name", "email", "is_verified", "is_active", "date_joined")
    list_filter = ("is_verified", "is_active", "is_staff", "date_joined")
    search_fields = ("phone_number", "email", "full_name")
    ordering = ("-date_joined",)
    readonly_fields = ("id", "date_joined", "last_login", "last_login_ip", "referral_code")

    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        ("Personal Info", {"fields": ("full_name", "email")}),
        ("Security", {"fields": ("pin_hash", "failed_login_count", "last_login_ip")}),
        ("Status", {"fields": ("is_verified", "is_active", "is_staff", "is_superuser")}),
        ("Referral", {"fields": ("referral_code",)}),
        ("Important Dates", {"fields": ("last_login", "date_joined")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("phone_number", "email", "full_name", "password1", "password2"),
        }),
    )
