"""
Support — URLs
==============
Customer-facing support ticketing routes.
"""

from django.urls import include, path

from . import views

app_name = "support"

urlpatterns = [
    # Customer ticket list
    path("", views.TicketListView.as_view(), name="ticket_list"),
    path("new/", views.TicketCreateView.as_view(), name="ticket_create"),
    path("<str:reference>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("<str:reference>/messages/", views.TicketMessagesPartialView.as_view(), name="ticket_messages_partial"),
    path("<str:reference>/reply/", views.TicketReplyView.as_view(), name="ticket_reply"),
    path("<str:reference>/csat/", views.TicketCsatView.as_view(), name="ticket_csat"),
    # Help-with-order entry point (used from failed order screens)
    path("help-with-order/", views.HelpWithOrderView.as_view(), name="help_with_order"),
    # Staff support desk
    path("desk/", include("apps.support.desk_urls")),
]
