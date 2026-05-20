"""
SMM — URL Configuration
========================
"""

from django.urls import path
from . import views

app_name = "smm"

urlpatterns = [
    path("", views.SmmIndexView.as_view(), name="index"),
]
