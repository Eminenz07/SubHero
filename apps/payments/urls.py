"""
Payments — URL Configuration
===============================
PRD Section 8.2: Webhook endpoints.
"""

from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("webhook/providus/", views.ProvidusWebhookView.as_view(), name="providus_webhook"),
]
