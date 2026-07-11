from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any, List
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
import logging

from apps.wallet.models import WalletTransaction, Wallet
from apps.vtu.models import VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder
from apps.smm.models import SMMOrder
from apps.giveaway.models import Giveaway
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)

@dataclass
class AnalyticsData:
    total_users: int
    total_wallet_balance: Decimal
    total_revenue: Decimal
    total_profit: Decimal
    total_deposits: Decimal
    giveaways_created: int
    
    # Timeseries data for charts
    revenue_chart: List[Dict[str, Any]]
    profit_chart: List[Dict[str, Any]]
    deposits_chart: List[Dict[str, Any]]


class AnalyticsQueries:
    """Handles cached dashboard analytics calculations."""
    
    @staticmethod
    def get_dashboard_stats(days=30) -> AnalyticsData:
        now = timezone.now()
        start_date = now - timedelta(days=days)
        
        import datetime
        cutoff_date = datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc)
        
        # 1. Global simple stats
        total_users = User.objects.count()
        total_balance = Wallet.objects.aggregate(t=Sum('balance'))['t'] or Decimal('0.00')
        giveaways_created = Giveaway.objects.filter(created_at__gte=cutoff_date).count()

        # Helper to get range stats
        def get_vtu_stats(model, qs_filter):
            f = dict(qs_filter)
            start = f.get('created_at__gte')
            if start:
                f['created_at__gte'] = max(start, cutoff_date)
            else:
                f['created_at__gte'] = cutoff_date
            res = model.objects.filter(**f, status='SUCCESS').aggregate(
                revenue=Sum('amount'),
                cost=Sum('api_cost')
            )
            r = res['revenue'] or Decimal('0.00')
            c = res['cost'] or Decimal('0.00')
            return r, (r - c)

        def get_all_vtu_stats(qs_filter):
            models = [VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder]
            total_rev = Decimal('0.00')
            total_prof = Decimal('0.00')
            for m in models:
                r, p = get_vtu_stats(m, qs_filter)
                total_rev += r
                total_prof += p
            return total_rev, total_prof

        def get_smm_stats(qs_filter):
            f = dict(qs_filter)
            start = f.get('created_at__gte')
            if start:
                f['created_at__gte'] = max(start, cutoff_date)
            else:
                f['created_at__gte'] = cutoff_date
            res = SMMOrder.objects.filter(
                **f, 
                status__in=['SUCCESS', 'PARTIAL', 'PROCESSING'] # Often SMM is processing for long
            ).aggregate(
                revenue=Sum('amount'),
                cost=Sum('api_cost')
            )
            r = res['revenue'] or Decimal('0.00')
            c = res['cost'] or Decimal('0.00')
            return r, (r - c)

        def get_deposit_stats(qs_filter):
            f = dict(qs_filter)
            start = f.get('created_at__gte')
            if start:
                f['created_at__gte'] = max(start, cutoff_date)
            else:
                f['created_at__gte'] = cutoff_date
            res = WalletTransaction.objects.filter(
                **f, 
                txn_type=WalletTransaction.TxnType.FUND,
                status=WalletTransaction.Status.SUCCESS
            ).aggregate(
                volume=Sum('amount'),
                fees=Sum('deposit_fee')
            )
            v = res['volume'] or Decimal('0.00')
            f = res['fees'] or Decimal('0.00')
            return v, f

        # Range filter
        time_filter = {'created_at__gte': start_date}

        # Totals for the time period
        vtu_rev, vtu_prof = get_all_vtu_stats(time_filter)
        smm_rev, smm_prof = get_smm_stats(time_filter)
        dep_vol, dep_fees = get_deposit_stats(time_filter)

        total_revenue = vtu_rev + smm_rev
        total_profit = vtu_prof + smm_prof + dep_fees
        total_deposits = dep_vol

        # Generate daily timeseries for the chart
        revenue_chart = []
        profit_chart = []
        deposits_chart = []

        # We will loop day by day for the requested range to build arrays for Chart.js
        # For larger datasets, we would use TruncDate on the DB, but this is fine for ~30 days
        for i in range(days):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            day_filter = {'created_at__gte': day_start, 'created_at__lt': day_end}
            
            day_vtu_rev, day_vtu_prof = get_all_vtu_stats(day_filter)
            day_smm_rev, day_smm_prof = get_smm_stats(day_filter)
            day_dep_vol, day_dep_fees = get_deposit_stats(day_filter)
            
            day_total_rev = day_vtu_rev + day_smm_rev
            day_total_prof = day_vtu_prof + day_smm_prof + day_dep_fees
            
            label = day_start.strftime("%b %d")
            revenue_chart.append({"x": label, "y": float(day_total_rev)})
            profit_chart.append({"x": label, "y": float(day_total_prof)})
            deposits_chart.append({"x": label, "y": float(day_dep_vol)})

        return AnalyticsData(
            total_users=total_users,
            total_wallet_balance=total_balance,
            total_revenue=total_revenue,
            total_profit=total_profit,
            total_deposits=total_deposits,
            giveaways_created=giveaways_created,
            revenue_chart=revenue_chart,
            profit_chart=profit_chart,
            deposits_chart=deposits_chart
        )
