"""
SMM — URL Configuration
========================
"""

from django.urls import path
from . import views

app_name = "smm"

urlpatterns = [
    path("", views.SmmIndexView.as_view(), name="index"),
    # New 3-tier architecture endpoints
    path("ajax/tier-services/", views.SmmTierServicesAjaxView.as_view(), name="ajax_tier_services"),
    path("ajax/services-list/", views.SmmServicesListAjaxView.as_view(), name="ajax_services_list"),
    # Legacy HTMX endpoints (kept for compatibility)
    path("ajax/categories/", views.SmmCategoriesAjaxView.as_view(), name="ajax_categories"),
    path("ajax/services/", views.SmmServicesAjaxView.as_view(), name="ajax_services"),
    path("receipt/status/<uuid:order_id>/", views.SmmReceiptStatusAjaxView.as_view(), name="receipt_status"),
    path("orders/<uuid:order_id>/progress/", views.SmmOrderProgressAjaxView.as_view(), name="order_progress"),
]
