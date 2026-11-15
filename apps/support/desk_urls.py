"""
Support — Desk URLs
====================
Staff support desk routes under /desk/.
"""

from django.urls import path

from . import desk_views

app_name = "desk"

urlpatterns = [
    # Inbox
    path("", desk_views.DeskInboxView.as_view(), name="inbox"),
    path("tickets/<uuid:ticket_id>/", desk_views.DeskTicketView.as_view(), name="ticket"),
    path("tickets/<uuid:ticket_id>/reply/", desk_views.DeskReplyView.as_view(), name="reply"),
    path("tickets/<uuid:ticket_id>/action/", desk_views.DeskActionView.as_view(), name="action"),
]
