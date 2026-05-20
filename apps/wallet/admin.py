from django.contrib import admin

from .models import Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "virtual_account_number", "virtual_account_bank", "is_frozen", "created_at")
    list_filter = ("is_frozen",)
    search_fields = ("user__phone_number", "user__email", "virtual_account_number")
    readonly_fields = ("id", "created_at")
    actions = ["freeze_wallets", "unfreeze_wallets"]

    @admin.action(description="Freeze selected wallets")
    def freeze_wallets(self, request, queryset):
        count = queryset.update(is_frozen=True)
        self.message_user(request, f"{count} wallet(s) frozen.")

    @admin.action(description="Unfreeze selected wallets")
    def unfreeze_wallets(self, request, queryset):
        count = queryset.update(is_frozen=False)
        self.message_user(request, f"{count} wallet(s) unfrozen.")


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "wallet", "txn_type", "amount", "status", "created_at")
    list_filter = ("txn_type", "status")
    search_fields = ("reference", "wallet__user__phone_number")
    readonly_fields = ("id", "created_at")
    date_hierarchy = "created_at"
