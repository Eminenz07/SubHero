"""
Promo Campaigns — URLs
======================
Public join link + admin routes (admin routes live under admin_panel).
"""

from django.urls import path

from . import views

app_name = "promos"

urlpatterns = [
    # Public join link — noindex, ratelimited by IP
    path("join/<str:code>/", views.join_promo, name="join"),
]