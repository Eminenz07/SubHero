import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from apps.payments.models import WebhookLog
from apps.wallet.models import Transaction, Wallet
from django.contrib.auth import get_user_model

print("=== WEBHOOK LOGS ===")
logs = WebhookLog.objects.all().order_by('-id')[:30]
for log in logs:
    print(f"ID: {log.id} | Ref: {log.reference} | Status: {log.status} | Err: {log.error_message} | Amt: {log.amount} | Date: {log.created_at}")

print("\n=== RECENT TRANSACTIONS ===")
txns = Transaction.objects.all().order_by('-id')[:20]
for txn in txns:
    print(f"ID: {txn.id} | Ref: {txn.transaction_ref} | Type: {txn.txn_type} | Status: {txn.status} | Amt: {txn.amount} | User: {txn.wallet.user.email if txn.wallet else 'No Wallet'}")

print("\n=== USER WALLETS ===")
User = get_user_model()
for user in User.objects.all():
    balance = user.wallet.balance if hasattr(user, 'wallet') and user.wallet else 'No Wallet'
    print(f"User: {user.email} | ID: {user.id} | Balance: {balance}")
