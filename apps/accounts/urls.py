"""
Accounts — URL Configuration
==============================
"""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("verify/", views.VerifyOTPView.as_view(), name="verify_otp"),
    path("verify/resend/", views.ResendOTPView.as_view(), name="resend_otp"),
    path("set-pin/", views.SetPINView.as_view(), name="set_pin"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
]
