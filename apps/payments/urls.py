"""
Payments — URL Configuration
===========================
Defines endpoints for Squad Payment Gateway integration.
"""

from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("fund/", views.fund_wallet_page, name="fund_wallet"),
    path("initiate/", views.InitiateCardPaymentView.as_view(), name="initiate_payment"),
    path("callback/", views.payment_callback, name="payment_callback"),
    path("webhook/squad/", views.SquadWebhookView.as_view(), name="squad_webhook"),
]
