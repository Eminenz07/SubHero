from django.contrib import admin

from .models import WebhookLog


@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    list_display = ("reference", "provider", "amount", "account_number", "status", "signature_valid", "created_at")
    list_filter = ("provider", "status", "signature_valid")
    search_fields = ("reference", "account_number")
    readonly_fields = ("id", "payload_hash", "created_at")
    date_hierarchy = "created_at"
