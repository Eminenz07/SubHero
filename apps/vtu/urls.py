"""
VTU — URL Configuration
========================
"""

from django.urls import path
from . import views
from . import webhooks

app_name = "vtu"

urlpatterns = [
    # Data
    path("data/",        views.BuyDataView.as_view(),        name="buy_data"),
    path("ajax/plans/",  views.VtuPlansAjaxView.as_view(),   name="ajax_plans"),

    # Airtime
    path("airtime/",     views.BuyAirtimeView.as_view(),     name="buy_airtime"),

    # Cable TV
    path("cable/",       views.BuyCableView.as_view(),       name="buy_cable"),
    path("ajax/cable-plans/", views.CablePlansAjaxView.as_view(), name="ajax_cable_plans"),

    # Electricity
    path("electricity/", views.BuyElectricityView.as_view(), name="buy_electricity"),

    # Exam PINs
    path("exam-pin/",    views.BuyExamPinView.as_view(),     name="buy_exam_pin"),

    # Receipt Polling Ajax
    path("receipt/status/<str:order_type>/<uuid:order_id>/", views.ReceiptStatusAjaxView.as_view(), name="receipt_status"),

    # Utility Verification
    path("api/verify-utility/", views.VerifyUtilityAjaxView.as_view(), name="verify_utility"),

    # Provider Webhooks
    path("webhooks/dancity/", webhooks.DancityWebhookView.as_view(), name="dancity_webhook"),
    path("webhooks/gsubz/", webhooks.GsubzWebhookView.as_view(), name="gsubz_webhook"),
]
