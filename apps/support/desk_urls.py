"""
Support — Desk URLs
====================
Staff support desk routes under /desk/.
"""

from django.urls import path

from . import desk_views
from apps.accounts import views as accounts_views

app_name = "desk"

urlpatterns = [
    # Staff auth (dedicated desk login, separate from customer /auth/login/)
    path("login/", accounts_views.StaffLoginView.as_view(), name="staff_login"),
    path("change-password/", accounts_views.StaffChangePasswordView.as_view(), name="staff_change_password"),
    path("logout/", accounts_views.LogoutView.as_view(), name="staff_logout"),
    # Inbox
    path("", desk_views.DeskInboxView.as_view(), name="inbox"),
    path("tickets/<uuid:ticket_id>/", desk_views.DeskTicketView.as_view(), name="ticket"),
    path("tickets/<uuid:ticket_id>/reply/", desk_views.DeskReplyView.as_view(), name="reply"),
    path("tickets/<uuid:ticket_id>/action/", desk_views.DeskActionView.as_view(), name="action"),
]
