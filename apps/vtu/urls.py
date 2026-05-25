"""
VTU — URL Configuration
========================
"""

from django.urls import path
from . import views

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
]
