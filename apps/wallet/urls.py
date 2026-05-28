"""
Wallet — URL Configuration
============================
PRD Table 27: Wallet page URLs.
"""

from django.urls import path
from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.WalletOverviewView.as_view(), name="overview"),
    path("fund/", views.FundWalletView.as_view(), name="fund"),
    path("transfer/", views.P2PTransferView.as_view(), name="transfer"),
    path("transactions/", views.TransactionHistoryView.as_view(), name="transactions"),
    path("transactions/<uuid:txn_id>/", views.TransactionDetailView.as_view(), name="transaction_detail"),
    # HTMX endpoint: lookup recipient by phone
    path("lookup-recipient/", views.LookupRecipientView.as_view(), name="lookup_recipient"),
    # AJAX endpoint: generate virtual account on-demand
    path("generate-virtual-account/", views.GenerateVirtualAccountView.as_view(), name="generate_virtual_account"),
]
