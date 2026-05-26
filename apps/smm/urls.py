"""
SMM — URL Configuration
========================
"""

from django.urls import path
from . import views

app_name = "smm"

urlpatterns = [
    path("", views.SmmIndexView.as_view(), name="index"),
    path("ajax/categories/", views.SmmCategoriesAjaxView.as_view(), name="ajax_categories"),
    path("ajax/services/", views.SmmServicesAjaxView.as_view(), name="ajax_services"),
    path("receipt/status/<uuid:order_id>/", views.SmmReceiptStatusAjaxView.as_view(), name="receipt_status"),
]
