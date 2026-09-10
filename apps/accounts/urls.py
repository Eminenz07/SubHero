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
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="forgot_password"),
    path("forgot-password/verify/", views.VerifyResetOTPView.as_view(), name="verify_reset_otp"),
    path("forgot-password/resend/", views.ResendResetOTPView.as_view(), name="resend_reset_otp"),
    path("reset-password/", views.ResetPasswordView.as_view(), name="reset_password"),
]
