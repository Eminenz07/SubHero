"""
Support — Admin registration
============================
Hero support models registered in Django admin for staff oversight.
"""

from django.contrib import admin

from .models import (
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketEvent,
    StaffProfile,
    CannedReply,
    RefundRequest,
)


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "display_name", "is_available", "created_at")
    list_filter = ("role", "is_available")
    search_fields = ("user__full_name", "user__phone_number", "display_name")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("reference", "subject", "user", "category", "status", "priority", "assigned_to", "created_at")
    list_filter = ("status", "priority", "category", "assigned_to")
    search_fields = ("reference", "subject", "user__phone_number", "user__full_name")
    readonly_fields = ("reference", "created_at", "updated_at")


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "sender_type", "is_internal", "created_at")
    list_filter = ("sender_type", "is_internal")
    search_fields = ("ticket__reference", "body")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("message", "filename", "size", "created_at")
    search_fields = ("filename",)


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("ticket__reference", "description")


@admin.register(CannedReply)
class CannedReplyAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("title", "body")


@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    list_display = ("ticket", "order_reference", "amount", "status", "requested_by", "decided_by", "created_at")
    list_filter = ("status",)
    search_fields = ("ticket__reference", "order_reference", "reason")
