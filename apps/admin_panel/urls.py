"""
Admin Panel — URLs
==================
Defines routing patterns for the custom administrative dashboard.
"""

from django.urls import path
from . import views

app_name = "admin_panel"

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),
    path("api/revenue-chart/", views.revenue_chart_api, name="revenue_chart_api"),

    # User Management
    path("users/", views.users_list, name="users"),
    path("users/export/", views.export_users_csv, name="export_users_csv"),
    path("users/<uuid:user_id>/", views.user_detail, name="user_detail"),
    path("users/<uuid:user_id>/toggle-status/", views.user_toggle_status, name="user_toggle_status"),
    path("users/<uuid:user_id>/toggle-freeze/", views.wallet_toggle_freeze, name="wallet_toggle_freeze"),

    # VTU Pricing
    path("vtu-pricing/", views.vtu_pricing_manager, name="vtu_pricing"),
    path("vtu-pricing/save/", views.vtu_pricing_save, name="vtu_pricing_save"),
    path("vtu-pricing/bulk-update/", views.vtu_pricing_bulk_update, name="vtu_pricing_bulk_update"),
    path("vtu-pricing/airtime-save/", views.vtu_airtime_pricing_save, name="vtu_airtime_pricing_save"),

    # SMM Pricing
    path("smm-pricing/", views.smm_pricing_manager, name="smm_pricing"),
    path("smm-pricing/save/", views.smm_pricing_save, name="smm_pricing_save"),
    path("smm-pricing/bulk-update/", views.smm_pricing_bulk_update, name="smm_pricing_bulk_update"),
    path("smm-pricing/exchange-rate/", views.update_exchange_rate, name="update_exchange_rate"),
    path("smm-pricing/sync-descriptions/", views.sync_smm_descriptions_admin, name="sync_smm_descriptions_admin"),

    # Orders & Giveaways
    path("orders/", views.orders_list, name="orders"),
    path("giveaways/", views.giveaways_list, name="giveaways"),
    path("orders/<uuid:order_id>/refund/", views.manual_refund, name="manual_refund"),
    path("orders/<uuid:order_id>/retry/", views.manual_retry, name="manual_retry"),
    path("orders/<uuid:order_id>/mark-delivered/", views.manual_mark_delivered, name="manual_mark_delivered"),

    # API Wallet Monitor
    path("api-wallets/", views.api_wallets, name="api_wallets"),
    path("api-wallets/test-alert/", views.test_alert_email, name="test_alert_email"),
    path("api-wallets/dispatch-push/", views.dispatch_admin_push, name="dispatch_admin_push"),

    # Live Logs
    path("logs/", views.logs_console, name="logs"),
    path("logs/stream/", views.log_stream, name="log_stream"),

    # Transaction Logs
    path("transactions/", views.transactions_list, name="transactions"),
    path("transactions/export/", views.export_transactions_csv, name="export_transactions_csv"),

    # Analytics Dashboard
    path("analytics/", views.analytics_page, name="analytics"),
    path("analytics/data/", views.analytics_data, name="analytics_data"),
    path("analytics/chart/", views.analytics_chart_data, name="analytics_chart"),

    # Settings
    path("settings/", views.system_settings, name="settings"),
]
