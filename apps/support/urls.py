"""
Support — URLs
==============
Customer-facing support ticketing routes.
"""

from django.urls import include, path

from . import views

app_name = "support"

urlpatterns = [
    # Staff support desk (must come before <str:reference>/ to avoid capture)
    path("desk/", include("apps.support.desk_urls", namespace="desk")),
    # Customer ticket list
    path("", views.TicketListView.as_view(), name="ticket_list"),
    path("new/", views.TicketCreateView.as_view(), name="ticket_create"),
    # Help-with-order entry point (used from failed order screens) — must come
    # before <reference>/ so fixed paths are never swallowed
    path("help-with-order/", views.HelpWithOrderView.as_view(), name="help_with_order"),
    # Ticket detail / actions — reference pattern restricted to HRO-XXXXXX
    path("HRO-<int:ref_num>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("HRO-<int:ref_num>/messages/", views.TicketMessagesPartialView.as_view(), name="ticket_messages_partial"),
    path("HRO-<int:ref_num>/reply/", views.TicketReplyView.as_view(), name="ticket_reply"),
    path("HRO-<int:ref_num>/csat/", views.TicketCsatView.as_view(), name="ticket_csat"),
    # Refund requests (agent creates, lead/admin approves)
    path("refund-request/<str:ticket_id>/", views.RefundRequestCreateView.as_view(), name="refund_request"),
    path("refund-request/<uuid:refund_id>/decide/", views.RefundRequestDecideView.as_view(), name="refund_request_decide"),
]
