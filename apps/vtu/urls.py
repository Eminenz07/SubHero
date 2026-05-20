"""
VTU — URL Configuration
========================
"""

from django.urls import path
from . import views

app_name = "vtu"

urlpatterns = [
    path("data/", views.BuyDataView.as_view(), name="buy_data"),
]
