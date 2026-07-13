from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any, List
from django.db.models import Sum, Count, Q, F, Avg, ExpressionWrapper, DurationField, OuterRef, Subquery
from django.db.models.functions import TruncDate, ExtractHour, Coalesce
from django.utils.timezone import now
from django.core.cache import cache
from datetime import datetime, date, timedelta, timezone
import logging

from apps.wallet.models import WalletTransaction, Wallet
from apps.vtu.models import VTUOrder
from apps.smm.models import SMMOrder
from apps.giveaway.models import Giveaway, GiveawayClaim
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)

CUTOFF_DATE = datetime(2026, 7, 4, tzinfo=timezone.utc)

def get_total_wallet_balance() -> Decimal:
    """Total funds held across ALL user wallets right now. No date filter."""
    return cache.get_or_set(
        "analytics:total_wallet_balance",
        lambda: Wallet.objects.aggregate(total=Sum('balance'))['total'] or Decimal('0.00'),
        timeout=60
    )

def get_gross_revenue(start: date, end: date) -> Dict[str, Decimal]:
    """Total naira from all SUCCESS purchases in range. Includes VTU + SMM + Giveaway."""
    key = f"analytics:gross_revenue:{start}:{end}"
    
    def run_query():
        # Start/End date as timezone-aware datetimes
        s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        
        # Apply cutoff
        s_dt = max(s_dt, CUTOFF_DATE)
        if e_dt < CUTOFF_DATE:
            return {'vtu': Decimal('0.00'), 'smm': Decimal('0.00'), 'giveaway': Decimal('0.00'), 'total': Decimal('0.00')}
            
        vtu = VTUOrder.objects.filter(
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        smm = SMMOrder.objects.filter(
            status__in=['SUCCESS', 'PARTIAL'],
            created_at__range=(s_dt, e_dt)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        giveaway = Giveaway.objects.filter(
            created_at__range=(s_dt, e_dt)
        ).aggregate(total=Sum('total_locked'))['total'] or Decimal('0.00')

        return {
            'vtu': vtu,
            'smm': smm,
            'giveaway': giveaway,
            'total': vtu + smm + giveaway
        }
        
    return cache.get_or_set(key, run_query, timeout=300)

def get_net_profit(start: date, end: date) -> Dict[str, Decimal]:
    """Actual profit: VTU profit + SMM profit + Deposit fees."""
    key = f"analytics:net_profit:{start}:{end}"
    
    def run_query():
        s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        
        s_dt = max(s_dt, CUTOFF_DATE)
        if e_dt < CUTOFF_DATE:
            return {'vtu': Decimal('0.00'), 'smm': Decimal('0.00'), 'fees': Decimal('0.00'), 'total': Decimal('0.00')}
            
        vtu = VTUOrder.objects.filter(
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).aggregate(
            profit=Sum(F('amount') - F('api_cost'))
        )['profit'] or Decimal('0.00')

        smm = SMMOrder.objects.filter(
            status__in=['SUCCESS', 'PARTIAL'],
            created_at__range=(s_dt, e_dt)
        ).aggregate(
            profit=Sum(F('amount') - F('api_cost'))
        )['profit'] or Decimal('0.00')

        fees = WalletTransaction.objects.filter(
            txn_type='FUND',
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).aggregate(
            total_fees=Sum('deposit_fee')
        )['total_fees'] or Decimal('0.00')

        return {
            'vtu': vtu,
            'smm': smm,
            'fees': fees,
            'total': vtu + smm + fees
        }
        
    return cache.get_or_set(key, run_query, timeout=300)

def get_deposit_fee_revenue(start: date, end: date) -> Dict[str, Any]:
    """Retrieves statistics on deposit fees collected in the date range."""
    key = f"analytics:deposit_fee_revenue:{start}:{end}"
    
    def run_query():
        s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        
        s_dt = max(s_dt, CUTOFF_DATE)
        if e_dt < CUTOFF_DATE:
            return {'small_deposits': 0, 'large_deposits': 0, 'fee_revenue': Decimal('0.00'), 'calculated': Decimal('0.00')}
            
        result = WalletTransaction.objects.filter(
            txn_type='FUND',
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).aggregate(
            small_count=Count('id', filter=Q(amount__lt=1000)),
            large_count=Count('id', filter=Q(amount__gte=1000)),
            total_fees=Sum('deposit_fee')
        )
        small = result['small_count'] or 0
        large = result['large_count'] or 0
        fees = result['total_fees'] or Decimal('0.00')
        return {
            'small_deposits': small,
            'large_deposits': large,
            'fee_revenue': fees,
            'calculated': Decimal(str((small * 20) + (large * 50)))
        }
        
    return cache.get_or_set(key, run_query, timeout=300)

def get_revenue_chart_data(start: date, end: date) -> List[Dict[str, Any]]:
    """Daily revenue + profit for line chart."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        VTUOrder.objects.filter(
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).annotate(
            day=TruncDate('created_at')
        ).values('day').annotate(
            revenue=Sum('amount'),
            profit=Sum(F('amount') - F('api_cost'))
        ).order_by('day')
    )

def get_average_order_value(start: date, end: date) -> Decimal:
    """Average order value combining VTU and SMM successful orders."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return Decimal('0.00')
        
    vtu = VTUOrder.objects.filter(status='SUCCESS', created_at__range=(s_dt, e_dt)).aggregate(total=Sum('amount'), count=Count('id'))
    smm = SMMOrder.objects.filter(status__in=['SUCCESS', 'PARTIAL'], created_at__range=(s_dt, e_dt)).aggregate(total=Sum('amount'), count=Count('id'))
    
    total_val = (vtu['total'] or Decimal('0.00')) + (smm['total'] or Decimal('0.00'))
    total_cnt = (vtu['count'] or 0) + (smm['count'] or 0)
    
    return total_val / total_cnt if total_cnt > 0 else Decimal('0.00')

def get_total_refunds(start: date, end: date) -> Dict[str, Any]:
    """Total counts and volume of refunds."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return {'count': 0, 'total': Decimal('0.00')}
        
    result = WalletTransaction.objects.filter(
        txn_type='REFUND',
        status='SUCCESS',
        created_at__range=(s_dt, e_dt)
    ).aggregate(count=Count('id'), total=Sum('amount'))
    return {
        'count': result['count'] or 0,
        'total': result['total'] or Decimal('0.00')
    }

def get_user_stats(start: date, end: date) -> Dict[str, Any]:
    """General stats relating to users."""
    key = f"analytics:user_stats:{start}:{end}"
    
    def run_query():
        s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        s_dt = max(s_dt, CUTOFF_DATE)
        
        total = User.objects.count()
        new_in_range = User.objects.filter(date_joined__range=(s_dt, e_dt)).count()
        
        thirty_days_ago = now() - timedelta(days=30)
        active = User.objects.filter(
            wallet__transactions__created_at__gte=thirty_days_ago,
            wallet__transactions__status='SUCCESS'
        ).distinct().count()
        
        funded = User.objects.filter(wallet__balance__gt=0).count()
        dormant = User.objects.filter(wallet__transactions__isnull=True).count()
        
        return {
            'total': total,
            'new_in_range': new_in_range,
            'active_30d': active,
            'funded': funded,
            'dormant': dormant,
            'zero_balance': total - funded,
        }
        
    return cache.get_or_set(key, run_query, timeout=300)

def get_user_growth_chart(start: date, end: date) -> List[Dict[str, Any]]:
    """Registrations timeseries."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        User.objects.filter(
            date_joined__range=(s_dt, e_dt)
        ).annotate(
            day=TruncDate('date_joined')
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
    )

def get_top_users_by_spend(limit: int = 10) -> List[User]:
    """Leaderboard of top spenders (excluding mock orders)."""
    return list(
        User.objects.annotate(
            total_spent=Sum(
                'wallet__transactions__amount',
                filter=Q(
                    wallet__transactions__txn_type__in=['VTU', 'SMM', 'GIVEAWAY_LOCK'],
                    wallet__transactions__status='SUCCESS',
                    wallet__transactions__created_at__gte=CUTOFF_DATE
                )
            )
        ).order_by('-total_spent')[:limit]
    )

def get_arpu(start: date, end: date) -> Decimal:
    """Average Revenue Per User in time range."""
    revenue = get_gross_revenue(start, end)['total']
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    user_count = User.objects.filter(date_joined__lte=e_dt).count()
    return revenue / user_count if user_count else Decimal('0.00')

def get_vtu_stats(start: date, end: date) -> Dict[str, Any]:
    """Total stats for VTU orders."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return {'total': 0, 'success': 0, 'failed': 0, 'pending': 0, 'revenue': Decimal('0.00'), 'profit': Decimal('0.00')}
        
    base = VTUOrder.objects.filter(created_at__range=(s_dt, e_dt))
    return {
        'total': base.count(),
        'success': base.filter(status='SUCCESS').count(),
        'failed': base.filter(status='FAILED').count(),
        'pending': base.filter(status='PENDING').count(),
        'revenue': base.filter(status='SUCCESS').aggregate(t=Sum('amount'))['t'] or Decimal('0.00'),
        'profit': base.filter(status='SUCCESS').aggregate(p=Sum(F('amount') - F('api_cost')))['p'] or Decimal('0.00'),
    }

def get_vtu_network_split(start: date, end: date) -> List[Dict[str, Any]]:
    """VTU success orders by network split."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        VTUOrder.objects.filter(
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).values('network').annotate(
            count=Count('id'),
            revenue=Sum('amount')
        ).order_by('-count')
    )

def get_vtu_service_split(start: date, end: date) -> List[Dict[str, Any]]:
    """Split between VTU order type category classifications."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    orders = VTUOrder.objects.filter(status='SUCCESS', created_at__range=(s_dt, e_dt))
    return list(
        orders.annotate(
            service_type=Coalesce(
                Q(network__in=['mtn', 'airtel', 'glo', '9mobile']),
                True
            )
        ).values('network').annotate(
            count=Count('id'),
            revenue=Sum('amount')
        ).order_by('-count')
    )

def get_top_vtu_plans(start: date, end: date, limit: int = 5) -> List[Dict[str, Any]]:
    """Top 5 data plans purchased."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        VTUOrder.objects.filter(
            status='SUCCESS',
            created_at__range=(s_dt, e_dt)
        ).values('plan_name', 'network').annotate(
            count=Count('id'),
            revenue=Sum('amount')
        ).order_by('-count')[:limit]
    )

def get_vtu_orders_by_hour(start: date, end: date) -> List[Dict[str, Any]]:
    """Returns order count grouped by hour of the day."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        VTUOrder.objects.filter(
            created_at__range=(s_dt, e_dt)
        ).annotate(
            hour=ExtractHour('created_at')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour')
    )

def get_smm_stats(start: date, end: date) -> Dict[str, Any]:
    """Total stats for SMM orders."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return {'total': 0, 'completed': 0, 'processing': 0, 'partial': 0, 'failed': 0, 'revenue': Decimal('0.00'), 'profit': Decimal('0.00')}
        
    base = SMMOrder.objects.filter(created_at__range=(s_dt, e_dt))
    return {
        'total': base.count(),
        'completed': base.filter(status='SUCCESS').count(),
        'processing': base.filter(status='PROCESSING').count(),
        'partial': base.filter(status='PARTIAL').count(),
        'failed': base.filter(status='FAILED').count(),
        'revenue': base.filter(status__in=['SUCCESS', 'PARTIAL']).aggregate(t=Sum('amount'))['t'] or Decimal('0.00'),
        'profit': base.filter(status__in=['SUCCESS', 'PARTIAL']).aggregate(p=Sum(F('amount') - F('api_cost')))['p'] or Decimal('0.00'),
    }

def get_smm_platform_split(start: date, end: date) -> List[Dict[str, Any]]:
    """Orders by SMM platform category split."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        SMMOrder.objects.filter(
            created_at__range=(s_dt, e_dt)
        ).values(
            platform=F('service__category')
        ).annotate(
            count=Count('id'),
            revenue=Sum('amount')
        ).order_by('-count')
    )

def get_smm_avg_delivery_time(start: date, end: date) -> Any:
    """Average hours from SMM order placement to SUCCESS/completed."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return None
        
    return SMMOrder.objects.filter(
        status='SUCCESS',
        created_at__range=(s_dt, e_dt)
    ).aggregate(
        avg_hours=Avg(
            ExpressionWrapper(
                F('created_at') - F('created_at'),
                output_field=DurationField()
            )
        )
    )['avg_hours']

def get_giveaway_stats(start: date, end: date) -> Dict[str, Any]:
    """Total stats for giveaways."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return {'total_created': 0, 'active': 0, 'completed': 0, 'expired': 0, 'total_slots': 0, 'claimed_slots': 0, 'total_locked': Decimal('0.00'), 'total_spent': Decimal('0.00')}
        
    base = Giveaway.objects.filter(created_at__range=(s_dt, e_dt))
    return {
        'total_created': base.count(),
        'active': base.filter(status='ACTIVE').count(),
        'completed': base.filter(status='COMPLETED').count(),
        'expired': base.filter(status='EXPIRED').count(),
        'total_slots': base.aggregate(t=Sum('slots'))['t'] or 0,
        'claimed_slots': base.aggregate(t=Sum('claimed_slots'))['t'] or 0,
        'total_locked': base.aggregate(t=Sum('total_locked'))['t'] or Decimal('0.00'),
        'total_spent': base.aggregate(t=Sum('total_spent'))['t'] or Decimal('0.00'),
    }

def get_giveaway_claim_rate(start: date, end: date) -> float:
    """Giveaway slot claim rates percentage."""
    stats = get_giveaway_stats(start, end)
    if not stats['total_slots']:
        return 0.0
    return (stats['claimed_slots'] / stats['total_slots']) * 100.0

def get_top_giveaway_hosts(start: date, end: date, limit: int = 5) -> List[Dict[str, Any]]:
    """Leaderboard of giveaway hosts by locked volume."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return []
        
    return list(
        User.objects.filter(
            giveaways__created_at__range=(s_dt, e_dt)
        ).annotate(
            total_given=Sum('giveaways__total_locked'),
            giveaway_count=Count('giveaways')
        ).order_by('-total_given')[:limit].values('id', 'first_name', 'last_name', 'phone_number', 'total_given', 'giveaway_count')
    )

def get_transaction_stats(start: date, end: date) -> Dict[str, Any]:
    """Naira volume and counts for deposits/P2P."""
    s_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    e_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    s_dt = max(s_dt, CUTOFF_DATE)
    if e_dt < CUTOFF_DATE:
        return {'total_initiated': 0, 'total_completed': 0, 'total_failed': 0, 'p2p_count': 0, 'p2p_volume': Decimal('0.00'), 'deposit_count': 0, 'deposit_volume': Decimal('0.00')}
        
    base = WalletTransaction.objects.filter(created_at__range=(s_dt, e_dt))
    return {
        'total_initiated': base.count(),
        'total_completed': base.filter(status='SUCCESS').count(),
        'total_failed': base.filter(status='FAILED').count(),
        'p2p_count': base.filter(txn_type='P2P_SEND').count(),
        'p2p_volume': base.filter(txn_type='P2P_SEND', status='SUCCESS').aggregate(t=Sum('amount'))['t'] or Decimal('0.00'),
        'deposit_count': base.filter(txn_type='FUND').count(),
        'deposit_volume': base.filter(txn_type='FUND', status='SUCCESS').aggregate(t=Sum('amount'))['t'] or Decimal('0.00'),
    }

def get_peak_transaction_hour() -> Any:
    """All-time transaction frequency peak hour."""
    return WalletTransaction.objects.annotate(
        hour=ExtractHour('created_at')
    ).values('hour').annotate(
        count=Count('id')
    ).order_by('-count').first()
