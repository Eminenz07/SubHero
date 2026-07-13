"""
Admin Panel — Views
===================
Handles all administrative and operational dashboard controllers.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum, F, Count
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.core.mail import send_mail
from django.core.cache import cache
from decimal import Decimal, InvalidOperation
import datetime
import json
import csv
import time
import requests
import logging

from apps.admin_panel.decorators import admin_required
from apps.admin_panel.models import AdminLog, SystemLog, AlertConfig, SystemSetting
from apps.admin_panel.utils import syslog, log_admin_action
from apps.wallet.models import Wallet, WalletTransaction
from apps.vtu.models import VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder, VTUPlan, CablePlan, ExamProduct
from apps.smm.models import SMMOrder, SMMService
from django.conf import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DASHBOARD METRIC HELPERS
# ─────────────────────────────────────────────────────────────

def get_vtu_order_stats(start_date=None):
    valid_refs = WalletTransaction.objects.values('reference')
    q = VTUOrder.objects.filter(status="SUCCESS", reference__in=valid_refs)
    if start_date:
        q = q.filter(created_at__gte=start_date)
    vtu_rev = q.aggregate(sum=Sum('amount'))['sum'] or Decimal("0")
    vtu_profit = vtu_rev * Decimal("0.05")  # Approximate 5% profit margin
    return vtu_rev, vtu_profit


def get_smm_order_stats(start_date=None):
    valid_refs = WalletTransaction.objects.values('reference')
    q = SMMOrder.objects.filter(status="SUCCESS", reference__in=valid_refs)
    if start_date:
        q = q.filter(created_at__gte=start_date)
    smm_rev = q.aggregate(sum=Sum('amount'))['sum'] or Decimal("0")
    smm_profit = smm_rev * Decimal("0.10")  # Approximate 10% profit margin
    return smm_rev, smm_profit


def get_other_order_stats(start_date=None):
    valid_refs = WalletTransaction.objects.values('reference')
    rev = Decimal("0")
    profit = Decimal("0")
    for model, pct in [
        (AirtimeOrder, 0.02),
        (CableOrder, 0.03),
        (ElectricityOrder, 0.02),
        (ExamPinOrder, 0.05)
    ]:
        q = model.objects.filter(status="SUCCESS", reference__in=valid_refs)
        if start_date:
            q = q.filter(created_at__gte=start_date)
        model_rev = q.aggregate(sum=Sum('amount'))['sum'] or Decimal("0")
        rev += model_rev
        profit += model_rev * Decimal(str(pct))
    return rev, profit


def fetch_cheapdatahub_balance():
    try:
        url = f"{settings.CHEAPDATAHUB_BASE_URL}/balance/"
        r = requests.get(
            url,
            headers={"Authorization": f"Token {settings.CHEAPDATAHUB_API_KEY}"},
            timeout=8
        )
        if r.status_code == 200:
            return Decimal(str(r.json()['balance']))
    except Exception:
        pass
    return Decimal("0.00")


def fetch_sabuss_balance():
    try:
        api_key = getattr(settings, "SABUSS_API_KEY", "")
        pin = getattr(settings, "SABUSS_PIN", "")
        base_url = getattr(settings, "SABUSS_BASE_URL", "https://sabuss.com")
        url = f"{base_url}/vtu/api/balance/{api_key}"
        response = requests.post(url, data={'pin': pin}, timeout=8)
        if response.status_code == 200:
            data = response.json()
            if str(data.get("code")) == "200":
                return Decimal(str(data.get("balance", "0")))
    except Exception:
        pass
    return Decimal("0.00")


def fetch_ogaviral_balance():
    try:
        r = requests.post(settings.OGAVIRAL_API_URL, data={
            "key": settings.OGAVIRAL_API_KEY, "action": "balance"
        }, timeout=8)
        if r.status_code == 200:
            return Decimal(str(r.json()['balance']))
    except Exception:
        pass
    return Decimal("0.00")


# ─────────────────────────────────────────────────────────────
# VIEW ACTIONS
# ─────────────────────────────────────────────────────────────

@admin_required
def dashboard(request):
    User = get_user_model()
    
    # Use cached analytics structure (could cache the output in Redis here if traffic is high)
    from apps.admin_panel.queries import AnalyticsQueries
    stats = AnalyticsQueries.get_dashboard_stats(days=30)
    
    new_users_today = User.objects.filter(date_joined__date=timezone.now().date()).count()
    
    # Active orders count (excluding mock orders before July 4th, 2026)
    import datetime
    cutoff_date = datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc)
    valid_refs = WalletTransaction.objects.filter(created_at__gte=cutoff_date).values('reference')
    active_orders = (
        VTUOrder.objects.filter(status__in=["PENDING", "PROCESSING"], reference__in=valid_refs).count() +
        SMMOrder.objects.filter(status__in=["PENDING", "PROCESSING"], reference__in=valid_refs).count() +
        AirtimeOrder.objects.filter(status__in=["PENDING", "PROCESSING"], reference__in=valid_refs).count() +
        CableOrder.objects.filter(status__in=["PENDING", "PROCESSING"], reference__in=valid_refs).count() +
        ElectricityOrder.objects.filter(status__in=["PENDING", "PROCESSING"], reference__in=valid_refs).count() +
        ExamPinOrder.objects.filter(status__in=["PENDING", "PROCESSING"], reference__in=valid_refs).count()
    )
    
    # Live balance fetch
    sabuss_balance = fetch_sabuss_balance()
    cdh_balance = fetch_cheapdatahub_balance()
    ogaviral_balance = fetch_ogaviral_balance()
    
    alert_config = AlertConfig.objects.first()
    if not alert_config:
        alert_config = AlertConfig.objects.create(alert_email="admin@subhero.ng")
        
    # Threshold checks
    if sabuss_balance <= alert_config.cdh_critical_threshold:
        sabuss_status = "critical"
    elif sabuss_balance <= alert_config.cdh_warning_threshold:
        sabuss_status = "warning"
    else:
        sabuss_status = "healthy"
        
    if cdh_balance <= alert_config.cdh_critical_threshold:
        cdh_status = "critical"
    elif cdh_balance <= alert_config.cdh_warning_threshold:
        cdh_status = "warning"
    else:
        cdh_status = "healthy"
        
    if ogaviral_balance <= alert_config.jap_critical_threshold:
        ogaviral_status = "critical"
    elif ogaviral_balance <= alert_config.jap_warning_threshold:
        ogaviral_status = "warning"
    else:
        ogaviral_status = "healthy"
        
    # HTMX Auto-refresh handling
    if request.headers.get("HX-Request"):
        target = request.headers.get("HX-Target", "")
        if target == "active-orders-count":
            return HttpResponse(str(active_orders))
        elif target == "failed-orders-today":
            failed_today = (
                VTUOrder.objects.filter(status="FAILED", created_at__date=timezone.now().date(), reference__in=valid_refs).count() +
                SMMOrder.objects.filter(status="FAILED", created_at__date=timezone.now().date(), reference__in=valid_refs).count()
            )
            return HttpResponse(str(failed_today))
        elif target == "revenue-today":
            day_stats = AnalyticsQueries.get_dashboard_stats(days=1)
            return HttpResponse(f"₦{day_stats.total_revenue:,.2f}")
            
    vtu_count = VTUOrder.objects.filter(reference__in=valid_refs).count()
    smm_count = SMMOrder.objects.filter(reference__in=valid_refs).count()
    airtime_count = AirtimeOrder.objects.filter(reference__in=valid_refs).count()
    cable_count = CableOrder.objects.filter(reference__in=valid_refs).count()
    electricity_count = ElectricityOrder.objects.filter(reference__in=valid_refs).count()
    exampin_count = ExamPinOrder.objects.filter(reference__in=valid_refs).count()

    context = {
        "active_nav": "dashboard",
        "total_users": stats.total_users,
        "new_users_today": new_users_today,
        "total_revenue": stats.total_revenue,
        "total_profit": stats.total_profit,
        "total_deposits": stats.total_deposits,
        "active_orders": active_orders,
        "sabuss_balance": sabuss_balance,
        "sabuss_status": sabuss_status,
        "cdh_balance": cdh_balance,
        "cdh_status": cdh_status,
        "ogaviral_balance": ogaviral_balance,
        "ogaviral_status": ogaviral_status,
        "alert_config": alert_config,
        "revenue_chart_json": json.dumps(stats.revenue_chart),
        "profit_chart_json": json.dumps(stats.profit_chart),
        "deposits_chart_json": json.dumps(stats.deposits_chart),
        "order_dist": {
            "vtu": vtu_count,
            "smm": smm_count,
            "airtime": airtime_count,
            "cable": cable_count,
            "electricity": electricity_count,
            "exampin": exampin_count,
        }
    }
    return render(request, "admin_panel/dashboard.html", context)


@admin_required
def revenue_chart_api(request):
    days = int(request.GET.get("days", 30))
    chart_data = []
    
    from apps.admin_panel.queries import AnalyticsQueries
    stats = AnalyticsQueries.get_dashboard_stats(days=days)
    
    chart_data = []
    for r, p, d in zip(stats.revenue_chart, stats.profit_chart, stats.deposits_chart):
        chart_data.append({
            "date": r["x"],
            "revenue": r["y"],
            "profit": p["y"],
            "deposits": d["y"]
        })
        
    return JsonResponse(chart_data, safe=False)


# ─────────────────────────────────────────────────────────────
# USER MANAGEMENT VIEWS
# ─────────────────────────────────────────────────────────────

@admin_required
def users_list(request):
    User = get_user_model()
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    sort_by = request.GET.get("sort", "date_joined").strip()
    direction = request.GET.get("dir", "desc").strip()
    
    users = User.objects.all().select_related("wallet")
    
    if q:
        users = users.filter(
            Q(full_name__icontains=q) |
            Q(phone_number__icontains=q) |
            Q(email__icontains=q)
        )
        
    if status_filter == "active":
        users = users.filter(is_active=True)
    elif status_filter == "suspended":
        users = users.filter(is_active=False)
    elif status_filter == "frozen":
        users = users.filter(wallet__is_frozen=True)
        
    # Sort mapping
    sort_fields = {
        "name": "full_name",
        "email": "email",
        "phone": "phone_number",
        "date_joined": "date_joined",
    }
    
    order_field = sort_fields.get(sort_by)
    if order_field:
        if direction == "desc":
            users = users.order_by(f"-{order_field}")
        else:
            users = users.order_by(order_field)
    elif sort_by == "balance":
        if direction == "desc":
            users = users.order_by("-wallet__balance")
        else:
            users = users.order_by("wallet__balance")
    else:
        users = users.order_by("-date_joined")
        
    from django.core.paginator import Paginator
    paginator = Paginator(users, 30)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        "active_nav": "users",
        "page_obj": page_obj,
        "q": q,
        "status": status_filter,
        "sort": sort_by,
        "dir": direction,
    }
    return render(request, "admin_panel/users.html", context)


@admin_required
def export_users_csv(request):
    User = get_user_model()
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    
    users = User.objects.all().select_related("wallet").order_by("-date_joined")
    
    if q:
        users = users.filter(
            Q(full_name__icontains=q) |
            Q(phone_number__icontains=q) |
            Q(email__icontains=q)
        )
        
    if status_filter == "active":
        users = users.filter(is_active=True)
    elif status_filter == "suspended":
        users = users.filter(is_active=False)
    elif status_filter == "frozen":
        users = users.filter(wallet__is_frozen=True)
        
    class Echo:
        def write(self, value):
            return value
            
    def row_generator():
        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)
        
        yield pseudo_buffer.write(["User ID", "Full Name", "Email", "Phone", "Wallet Balance (₦)", "Account Status", "Wallet Status", "Date Joined"])
        
        for u in users.iterator():
            balance = u.wallet.balance if hasattr(u, "wallet") and u.wallet else Decimal("0.00")
            acct_status = "Active" if u.is_active else "Suspended"
            wallet_status = "Frozen" if (hasattr(u, "wallet") and u.wallet and u.wallet.is_frozen) else "Active"
            joined = u.date_joined.strftime("%Y-%m-%d %H:%M:%S")
            yield pseudo_buffer.write([
                str(u.id), u.full_name, u.email, u.phone_number,
                f"{balance:.2f}", acct_status, wallet_status, joined
            ])
            
    response = StreamingHttpResponse(row_generator(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="subhero_users_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    return response


@admin_required
def user_detail(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, id=user_id)
    wallet = getattr(user, "wallet", None)
    
    # Last 50 transactions
    txns = WalletTransaction.objects.filter(wallet=wallet).order_by("-created_at")[:50] if wallet else []
    
    # Last 20 SMM / VTU
    vtu_orders = VTUOrder.objects.filter(user=user).order_by("-created_at")[:20]
    smm_orders = SMMOrder.objects.filter(user=user).order_by("-created_at")[:20]
    
    context = {
        "active_nav": "users",
        "user_profile": user,
        "wallet": wallet,
        "transactions": txns,
        "vtu_orders": vtu_orders,
        "smm_orders": smm_orders,
    }
    return render(request, "admin_panel/user_detail.html", context)


@admin_required
def user_toggle_status(request, user_id):
    if request.method == "POST":
        User = get_user_model()
        user = get_object_or_404(User, id=user_id)
        reason = request.POST.get("reason", "").strip()
        
        old_status = user.is_active
        user.is_active = not old_status
        user.save()
        
        action = "USER_SUSPEND" if old_status else "USER_ACTIVATE"
        detail = f"Changed status from {'Active' if old_status else 'Suspended'} to {'Suspended' if old_status else 'Active'}. Reason: {reason}"
        log_admin_action(request.user, action, "USER", user.id, detail, request)
        
        return redirect("admin_panel:user_detail", user_id=user.id)
    return HttpResponse("Invalid request", status=400)


@admin_required
def wallet_toggle_freeze(request, user_id):
    if request.method == "POST":
        User = get_user_model()
        user = get_object_or_404(User, id=user_id)
        wallet = get_object_or_404(Wallet, user=user)
        reason = request.POST.get("reason", "").strip()
        
        old_status = wallet.is_frozen
        wallet.is_frozen = not old_status
        wallet.save()
        
        action = "WALLET_FREEZE" if not old_status else "WALLET_UNFREEZE"
        detail = f"Changed wallet state from {'Active' if not old_status else 'Frozen'} to {'Frozen' if not old_status else 'Active'}. Reason: {reason}"
        log_admin_action(request.user, action, "WALLET", wallet.id, detail, request)
        
        return redirect("admin_panel:user_detail", user_id=user.id)
    return HttpResponse("Invalid request", status=400)


# ─────────────────────────────────────────────────────────────
# VTU PRICING MANAGER
# ─────────────────────────────────────────────────────────────

@admin_required
def vtu_pricing_manager(request):
    networks = ["mtn", "airtel", "glo", "9mobile"]
    plans_by_network = {}
    
    for net in networks:
        plans = list(VTUPlan.objects.filter(network=net).order_by("plan_type", "provider_price"))
        for p in plans:
            p.estimated_profit = p.subhero_price - p.provider_price
        plans_by_network[net] = plans
        
    airtime_settings = {}
    for net in networks:
        airtime_settings[net] = {
            "markup_type": SystemSetting.get(f"{net}_airtime_markup_type", "percent"),
            "markup_value": SystemSetting.get(f"{net}_airtime_markup_value", "0.00"),
            "is_active": SystemSetting.get(f"{net}_airtime_is_active", "True") == "True"
        }
        
    vtu_profit_margin = SystemSetting.get("vtu_profit_margin", "10.00")
        
    context = {
        "active_nav": "vtu_pricing",
        "plans_by_network": plans_by_network,
        "airtime_settings": airtime_settings,
        "networks": networks,
        "vtu_profit_margin": vtu_profit_margin,
    }
    return render(request, "admin_panel/vtu_pricing.html", context)


@admin_required
def vtu_pricing_save(request):
    if request.method == "POST":
        plan_id = request.POST.get("plan_id")
        markup_type = request.POST.get("markup_type")
        markup_value_str = request.POST.get("markup_value", "0").strip()
        is_active = request.POST.get("is_active") == "on" or request.POST.get("is_active") == "true"
        
        try:
            markup_value = Decimal(markup_value_str)
        except InvalidOperation:
            return HttpResponse("Invalid format", status=400)
            
        plan = get_object_or_404(VTUPlan, id=plan_id)
        cost = plan.provider_price
        
        # If markup_value is 0, revert to global profit margin
        if markup_value == 0:
            vtu_margin_pct = Decimal(SystemSetting.get("vtu_profit_margin", "10.00"))
            sell = cost * (1 + vtu_margin_pct / 100)
            plan.markup_type = "percent"
            plan.markup_value = Decimal("0.00")
        else:
            if markup_type == "percent":
                sell = cost * (1 + markup_value / 100)
            else:
                sell = cost + markup_value
            plan.markup_type = markup_type
            plan.markup_value = markup_value
            
        plan.subhero_price = sell
        plan.is_active = is_active
        plan.save()
        
        detail = f"Updated VTUPlan pricing plan_id={plan.plan_id}: type={markup_type}, value={markup_value}, sell={sell}, active={is_active}"
        log_admin_action(request.user, "PRICING_UPDATE", "VTU_PLAN", plan.id, detail, request)
        
        return HttpResponse('<button type="submit" class="px-2.5 py-1 rounded bg-slate-800 border border-white/[0.04] text-[10px] font-bold text-white hover:bg-slate-700 transition-colors">Save</button><span class="text-emerald-500 text-[10px] font-bold block mt-1 animate-pulse">✓ Saved</span>')
    return HttpResponse("Invalid request", status=400)


@admin_required
def vtu_pricing_bulk_update(request):
    if request.method == "POST":
        network = request.POST.get("network")
        markup_type = request.POST.get("markup_type")
        markup_value_str = request.POST.get("markup_value", "0").strip()
        plan_type = request.POST.get("plan_type", "all").strip()
        
        try:
            markup_value = Decimal(markup_value_str)
        except InvalidOperation:
            return HttpResponse("Invalid format", status=400)
            
        plans = VTUPlan.objects.filter(network=network)
        if plan_type != "all":
            plans = plans.filter(plan_type=plan_type)
            
        if markup_type == "percent":
            updated = plans.update(
                markup_type=markup_type,
                markup_value=markup_value,
                subhero_price=F('provider_price') * (Decimal('1') + markup_value / Decimal('100'))
            )
        else:
            updated = plans.update(
                markup_type=markup_type,
                markup_value=markup_value,
                subhero_price=F('provider_price') + markup_value
            )
                
        detail = f"Bulk pricing update for network={network} (type={plan_type}): {updated} plans updated to markup={markup_value} ({markup_type})"
        log_admin_action(request.user, "PRICING_BULK_UPDATE", "VTU_PLAN", f"NETWORK:{network}", detail, request)
        
        return redirect("admin_panel:vtu_pricing")
    return HttpResponse("Invalid request", status=400)


@admin_required
def vtu_airtime_pricing_save(request):
    if request.method == "POST":
        network = request.POST.get("network")
        markup_type = request.POST.get("markup_type")
        markup_value = request.POST.get("markup_value", "0").strip()
        is_active = request.POST.get("is_active") == "on" or request.POST.get("is_active") == "true"
        
        SystemSetting.set(f"{network}_airtime_markup_type", markup_type)
        SystemSetting.set(f"{network}_airtime_markup_value", markup_value)
        SystemSetting.set(f"{network}_airtime_is_active", str(is_active))
        
        detail = f"Updated Airtime pricing network={network}: type={markup_type}, value={markup_value}, active={is_active}"
        log_admin_action(request.user, "PRICING_UPDATE", "AIRTIME_SETTING", network, detail, request)
        
        return HttpResponse('<span class="text-emerald-500 font-bold flex items-center gap-1"><i data-feather="check" class="w-4 h-4"></i> Saved</span>')
    return HttpResponse("Invalid request", status=400)


# ─────────────────────────────────────────────────────────────
# SMM PRICING MANAGER
# ─────────────────────────────────────────────────────────────

@admin_required
def smm_pricing_manager(request):
    alert_config = AlertConfig.objects.first()
    if not alert_config:
        alert_config = AlertConfig.objects.create(alert_email="admin@subhero.ng")
        
    usd_rate = alert_config.usd_ngn_rate
    categories = list(SMMService.objects.order_by("category").values_list("category", flat=True).distinct())
    
    selected_category = request.GET.get("category", "").strip()
    q = request.GET.get("q", "").strip()
    
    if not selected_category and not q and categories:
        selected_category = categories[0]
        
    services_qs = SMMService.objects.all()
    if selected_category:
        services_qs = services_qs.filter(category=selected_category)
    if q:
        services_qs = services_qs.filter(Q(name__icontains=q) | Q(provider_service_id__icontains=q))
        
    services = list(services_qs.order_by("provider_rate"))
    for s in services:
        cost_ngn = s.provider_rate * usd_rate
        s.estimated_profit = s.subhero_price_per_1k - cost_ngn
        
    smm_profit_margin = SystemSetting.get("smm_profit_margin", "50.00")
        
    context = {
        "active_nav": "smm_pricing",
        "alert_config": alert_config,
        "categories": categories,
        "selected_category": selected_category,
        "services": services,
        "q": q,
        "usd_rate": usd_rate,
        "smm_profit_margin": smm_profit_margin,
    }
    return render(request, "admin_panel/smm_pricing.html", context)


@admin_required
def smm_pricing_save(request):
    if request.method == "POST":
        service_id = request.POST.get("service_id")
        markup_type = request.POST.get("markup_type")
        markup_value_str = request.POST.get("markup_value", "0").strip()
        is_active = request.POST.get("is_active") == "on" or request.POST.get("is_active") == "true"
        
        try:
            markup_value = Decimal(markup_value_str)
        except InvalidOperation:
            return HttpResponse("Invalid format", status=400)
            
        alert_config = AlertConfig.objects.first()
        usd_rate = alert_config.usd_ngn_rate if alert_config else Decimal("1600.00")
        
        service = get_object_or_404(SMMService, id=service_id)
        cost_ngn = service.provider_rate * usd_rate
        
        # If markup_value is 0, revert to global profit margin
        if markup_value == 0:
            smm_margin_pct = Decimal(SystemSetting.get("smm_profit_margin", "50.00"))
            sell = cost_ngn * (1 + smm_margin_pct / 100)
            service.markup_type = "percent"
            service.markup_value = Decimal("0.00")
        else:
            if markup_type == "percent":
                sell = cost_ngn * (1 + markup_value / 100)
            else:
                sell = cost_ngn + markup_value
            service.markup_type = markup_type
            service.markup_value = markup_value
            
        service.subhero_price_per_1k = sell
        service.is_active = is_active
        service.save()
        
        detail = f"Updated SMM service={service.name}: type={markup_type}, value={markup_value}, sell={sell}, active={is_active}"
        log_admin_action(request.user, "PRICING_UPDATE", "SMM_SERVICE", service.id, detail, request)
        
        return HttpResponse('<button type="submit" class="px-2.5 py-1 rounded bg-slate-800 border border-white/[0.04] text-[10px] font-bold text-white hover:bg-slate-700 transition-colors">Save</button><span class="text-emerald-500 text-[10px] font-bold block mt-1 animate-pulse">✓ Saved</span>')
    return HttpResponse("Invalid request", status=400)


@admin_required
def smm_pricing_bulk_update(request):
    if request.method == "POST":
        category = request.POST.get("category")
        markup_type = request.POST.get("markup_type")
        markup_value_str = request.POST.get("markup_value", "0").strip()
        
        try:
            markup_value = Decimal(markup_value_str)
        except InvalidOperation:
            return HttpResponse("Invalid format", status=400)
            
        alert_config = AlertConfig.objects.first()
        usd_rate = alert_config.usd_ngn_rate if alert_config else Decimal("1600.00")
        
        services = SMMService.objects.filter(category=category)
        
        if markup_type == "percent":
            multiplier = usd_rate * (Decimal("1") + markup_value / Decimal("100"))
            updated = services.update(
                markup_type=markup_type,
                markup_value=markup_value,
                subhero_price_per_1k=F('provider_rate') * multiplier
            )
        else:
            updated = services.update(
                markup_type=markup_type,
                markup_value=markup_value,
                subhero_price_per_1k=F('provider_rate') * usd_rate + markup_value
            )
                
        detail = f"Bulk SMM pricing update for category={category}: {updated} services updated to markup={markup_value} ({markup_type})"
        log_admin_action(request.user, "PRICING_BULK_UPDATE", "SMM_SERVICE", f"CATEGORY:{category}", detail, request)
        
        return redirect("admin_panel:smm_pricing")
    return HttpResponse("Invalid request", status=400)


@admin_required
def update_exchange_rate(request):
    if request.method == "POST":
        rate_str = request.POST.get("usd_ngn_rate", "").strip()
        try:
            rate = Decimal(rate_str)
            if rate <= 0:
                raise InvalidOperation()
        except InvalidOperation:
            return HttpResponse("Invalid exchange rate format", status=400)
            
        alert_config = AlertConfig.objects.first()
        if not alert_config:
            alert_config = AlertConfig.objects.create(alert_email="admin@subhero.ng")
            
        old_rate = alert_config.usd_ngn_rate
        alert_config.usd_ngn_rate = rate
        alert_config.save()
        
        # Recalculate SMM prices
        services = SMMService.objects.all()
        with transaction.atomic():
            for service in services:
                cost_ngn = service.provider_rate * rate
                if service.markup_type == "percent":
                    sell = cost_ngn * (1 + service.markup_value / 100)
                else:
                    sell = cost_ngn + service.markup_value
                service.subhero_price_per_1k = sell
                service.save()
                
        detail = f"Updated USD/NGN exchange rate from ₦{old_rate} to ₦{rate}. Recalculated SMM catalogue."
        log_admin_action(request.user, "EXCHANGE_RATE_UPDATE", "SYSTEM", "EXCHANGE_RATE", detail, request)
        
        return redirect("admin_panel:smm_pricing")
    return HttpResponse("Invalid request", status=400)


# ─────────────────────────────────────────────────────────────
# ORDER MANAGEMENT VIEWS
# ─────────────────────────────────────────────────────────────

def find_order_by_id(order_id):
    for model, label in [
        (VTUOrder, "VTU_DATA"),
        (SMMOrder, "SMM"),
        (AirtimeOrder, "AIRTIME"),
        (CableOrder, "CABLE"),
        (ElectricityOrder, "ELECTRICITY"),
        (ExamPinOrder, "EXAM_PINS")
    ]:
        order = model.objects.filter(id=order_id).first()
        if order:
            return order, label
    return None, None


@admin_required
def orders_list(request):
    status_filter = request.GET.get("status", "").strip()
    type_filter = request.GET.get("type", "").strip()
    q = request.GET.get("q", "").strip()
    
    orders = get_unified_orders(status_filter, type_filter, q)
    
    from django.core.paginator import Paginator
    paginator = Paginator(orders, 30)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        "active_nav": "orders",
        "page_obj": page_obj,
        "status": status_filter,
        "type": type_filter,
        "q": q,
    }
    return render(request, "admin_panel/orders.html", context)


def get_unified_orders(status_filter=None, type_filter=None, query=None):
    orders_list = []
    
    # 1. VTU DATA
    if not type_filter or type_filter == "vtu_data":
        q = VTUOrder.objects.all().select_related("user")
        if status_filter:
            q = q.filter(status=status_filter)
        if query:
            q = q.filter(Q(reference__icontains=query) | Q(recipient__icontains=query) | Q(plan_name__icontains=query) | Q(user__email__icontains=query))
        for o in q[:200]:
            orders_list.append({
                "id": o.id, "type": "VTU_DATA", "type_display": "VTU Data",
                "reference": o.reference, "user": o.user, "recipient": o.recipient,
                "description": o.plan_name, "amount": o.amount, "status": o.status, "created_at": o.created_at,
            })
            
    # 2. SMM
    if not type_filter or type_filter == "smm":
        q = SMMOrder.objects.all().select_related("user", "service")
        if status_filter:
            q = q.filter(status=status_filter)
        if query:
            q = q.filter(Q(reference__icontains=query) | Q(target_url__icontains=query) | Q(service__name__icontains=query) | Q(user__email__icontains=query))
        for o in q[:200]:
            orders_list.append({
                "id": o.id, "type": "SMM", "type_display": "SMM Booster",
                "reference": o.reference, "user": o.user, "recipient": o.target_url,
                "description": o.service.name, "amount": o.amount, "status": o.status, "created_at": o.created_at,
            })
            
    # 3. Airtime
    if not type_filter or type_filter == "airtime":
        q = AirtimeOrder.objects.all().select_related("user")
        if status_filter:
            q = q.filter(status=status_filter)
        if query:
            q = q.filter(Q(reference__icontains=query) | Q(recipient__icontains=query) | Q(user__email__icontains=query))
        for o in q[:200]:
            orders_list.append({
                "id": o.id, "type": "AIRTIME", "type_display": f"Airtime ({o.network.upper()})",
                "reference": o.reference, "user": o.user, "recipient": o.recipient,
                "description": "Airtime Purchase", "amount": o.amount, "status": o.status, "created_at": o.created_at,
            })
            
    # 4. Cable
    if not type_filter or type_filter == "cable":
        q = CableOrder.objects.all().select_related("user")
        if status_filter:
            q = q.filter(status=status_filter)
        if query:
            q = q.filter(Q(reference__icontains=query) | Q(card_number__icontains=query) | Q(user__email__icontains=query))
        for o in q[:200]:
            orders_list.append({
                "id": o.id, "type": "CABLE", "type_display": f"Cable TV ({o.provider.upper()})",
                "reference": o.reference, "user": o.user, "recipient": o.card_number,
                "description": o.plan_name, "amount": o.amount, "status": o.status, "created_at": o.created_at,
            })
            
    # 5. Electricity
    if not type_filter or type_filter == "electricity":
        q = ElectricityOrder.objects.all().select_related("user")
        if status_filter:
            q = q.filter(status=status_filter)
        if query:
            q = q.filter(Q(reference__icontains=query) | Q(meter_number__icontains=query) | Q(user__email__icontains=query))
        for o in q[:200]:
            orders_list.append({
                "id": o.id, "type": "ELECTRICITY", "type_display": f"Electricity ({o.disco_name})",
                "reference": o.reference, "user": o.user, "recipient": o.meter_number,
                "description": f"{o.meter_type.capitalize()} Purchase", "amount": o.amount, "status": o.status, "created_at": o.created_at,
            })
            
    # 6. Exam PINs
    if not type_filter or type_filter == "exam_pins":
        q = ExamPinOrder.objects.all().select_related("user")
        if status_filter:
            q = q.filter(status=status_filter)
        if query:
            q = q.filter(Q(reference__icontains=query) | Q(exam_name__icontains=query) | Q(user__email__icontains=query))
        for o in q[:200]:
            orders_list.append({
                "id": o.id, "type": "EXAM_PINS", "type_display": f"Exam PIN ({o.exam_name})",
                "reference": o.reference, "user": o.user, "recipient": f"{o.quantity} PINs",
                "description": f"{o.exam_name} Result Checker PINs", "amount": o.amount, "status": o.status, "created_at": o.created_at,
            })
            
    orders_list.sort(key=lambda x: x["created_at"], reverse=True)
    return orders_list


@admin_required
def manual_refund(request, order_id):
    if request.method == "POST":
        order, label = find_order_by_id(order_id)
        if not order:
            return HttpResponse("Order not found", status=404)
            
        from apps.vtu.tasks import (
            refund_vtu_order, refund_airtime_order,
            refund_cable_order, refund_electricity_order,
            refund_exam_pin_order
        )
        from apps.smm.tasks import refund_smm_order
        
        try:
            if label == "VTU_DATA":
                refund_vtu_order(str(order.id))
            elif label == "SMM":
                refund_smm_order(str(order.id))
            elif label == "AIRTIME":
                refund_airtime_order(str(order.id))
            elif label == "CABLE":
                refund_cable_order(str(order.id))
            elif label == "ELECTRICITY":
                refund_electricity_order(str(order.id))
            elif label == "EXAM_PINS":
                refund_exam_pin_order(str(order.id))
                
            order.refresh_from_db()
            detail = f"Manually triggered refund for order reference={order.reference} (type={label})"
            log_admin_action(request.user, "MANUAL_REFUND", label, order.id, detail, request)
            
            return HttpResponse('<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-red-950/40 text-red-400 border border-red-900/30">Refunded / Failed</span>')
        except Exception as e:
            return HttpResponse(f"Refund failed: {str(e)}", status=500)
            
    return HttpResponse("Invalid request method", status=400)


@admin_required
def manual_retry(request, order_id):
    if request.method == "POST":
        order, label = find_order_by_id(order_id)
        if not order:
            return HttpResponse("Order not found", status=404)
            
        from apps.vtu.tasks import (
            process_vtu_order, process_airtime_order,
            process_cable_order, process_electricity_order,
            process_exam_pin_order
        )
        from apps.smm.tasks import process_smm_order
        
        try:
            order.status = "PENDING"
            order.save()
            
            if label == "VTU_DATA":
                process_vtu_order.delay(str(order.id))
            elif label == "SMM":
                process_smm_order.delay(str(order.id))
            elif label == "AIRTIME":
                process_airtime_order.delay(str(order.id))
            elif label == "CABLE":
                process_cable_order.delay(str(order.id))
            elif label == "ELECTRICITY":
                process_electricity_order.delay(str(order.id))
            elif label == "EXAM_PINS":
                process_exam_pin_order.delay(str(order.id))
                
            detail = f"Manually triggered retry for order reference={order.reference} (type={label})"
            log_admin_action(request.user, "MANUAL_RETRY", label, order.id, detail, request)
            
            return HttpResponse('<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-yellow-950/40 text-yellow-400 border border-yellow-900/30 animate-pulse">Retrying...</span>')
        except Exception as e:
            return HttpResponse(f"Retry task dispatch failed: {str(e)}", status=500)
            
    return HttpResponse("Invalid request method", status=400)


@admin_required
def manual_mark_delivered(request, order_id):
    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return HttpResponse("Reason is required", status=400)
            
        order, label = find_order_by_id(order_id)
        if not order:
            return HttpResponse("Order not found", status=404)
            
        with transaction.atomic():
            order.status = "SUCCESS"
            order.save()
            
            WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)
            
        detail = f"Manually marked order reference={order.reference} as DELIVERED/SUCCESS (type={label}). Reason: {reason}"
        log_admin_action(request.user, "MANUAL_DELIVERED", label, order.id, detail, request)
        
        return HttpResponse('<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-950/40 text-emerald-400 border border-emerald-900/30">Delivered</span>')
    return HttpResponse("Invalid request method", status=400)


# ─────────────────────────────────────────────────────────────
# API WALLET MONITOR
# ─────────────────────────────────────────────────────────────

@admin_required
def api_wallets(request):
    # Form post logic handled here for AlertConfig
    alert_config = AlertConfig.objects.first()
    if not alert_config:
        alert_config = AlertConfig.objects.create(alert_email="admin@subhero.ng")
        
    if request.method == "POST":
        alert_config.alert_email = request.POST.get("alert_email", "").strip()
        alert_config.cdh_warning_threshold = Decimal(request.POST.get("cdh_warning_threshold", "10000"))
        alert_config.cdh_critical_threshold = Decimal(request.POST.get("cdh_critical_threshold", "3000"))
        alert_config.jap_warning_threshold = Decimal(request.POST.get("jap_warning_threshold", "5.00"))
        alert_config.jap_critical_threshold = Decimal(request.POST.get("jap_critical_threshold", "2.00"))
        alert_config.usd_ngn_rate = Decimal(request.POST.get("usd_ngn_rate", "1600"))
        alert_config.save()
        
        detail = f"Updated API Wallet configuration: email={alert_config.alert_email}, cdh_warn={alert_config.cdh_warning_threshold}, jap_warn={alert_config.jap_warning_threshold}"
        log_admin_action(request.user, "ALERT_CONFIG_UPDATE", "AlertConfig", alert_config.id, detail, request)
        
        return redirect("admin_panel:api_wallets")
        
    sabuss_balance = fetch_sabuss_balance()
    cdh_balance = fetch_cheapdatahub_balance()
    ogaviral_balance = fetch_ogaviral_balance()
    
    # 14-day history mock data
    history_data = []
    today = timezone.now().date()
    import random
    for i in range(13, -1, -1):
        day = today - datetime.timedelta(days=i)
        history_data.append({
            "date": day.strftime("%b %d"),
            "sabuss": float(sabuss_balance) + random.randint(-1500, 2500) if sabuss_balance > 0 else 12000 + random.randint(-1500, 2500),
            "cdh": float(cdh_balance) + random.randint(-1500, 2500) if cdh_balance > 0 else 12000 + random.randint(-1500, 2500),
            "ogaviral": float(ogaviral_balance) + random.randint(-5000, 10000) if ogaviral_balance > 0 else 25000 + random.randint(-5000, 10000),
        })
        
    context = {
        "active_nav": "api_wallets",
        "alert_config": alert_config,
        "sabuss_balance": sabuss_balance,
        "cdh_balance": cdh_balance,
        "ogaviral_balance": ogaviral_balance,
        "history_data": json.dumps(history_data),
    }
    return render(request, "admin_panel/api_wallets.html", context)


@admin_required
def test_alert_email(request):
    if request.method == "POST":
        alert_config = AlertConfig.objects.first()
        if not alert_config:
            return HttpResponse("Alert config not found", status=400)
            
        try:
            send_mail(
                subject="SubHero HQ — API Wallet Alert (TEST)",
                message=f"This is a test notification from SubHero HQ.\n\n"
                        f"Current Alert Thresholds:\n"
                        f"- Sabuss / CheapDataHub Warning: ₦{alert_config.cdh_warning_threshold:,.2f}\n"
                        f"- Sabuss / CheapDataHub Critical: ₦{alert_config.cdh_critical_threshold:,.2f}\n"
                        f"- Ogaviral Warning: ₦{alert_config.jap_warning_threshold:,.2f}\n"
                        f"- Ogaviral Critical: ₦{alert_config.jap_critical_threshold:,.2f}\n",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@subhero.ng"),
                recipient_list=[alert_config.alert_email],
                fail_silently=False
            )
            return HttpResponse(f'<div class="bg-emerald-950/40 text-emerald-400 border border-emerald-900/30 p-3 rounded-lg text-xs font-semibold">Test alert email sent to {alert_config.alert_email}</div>')
        except Exception as e:
            return HttpResponse(f'<div class="bg-red-950/40 text-red-400 border border-red-900/30 p-3 rounded-lg text-xs font-semibold">Email dispatch failed: {str(e)}</div>')
            
    return HttpResponse("Invalid request", status=400)


# ─────────────────────────────────────────────────────────────
# LIVE SYSTEM LOGS
# ─────────────────────────────────────────────────────────────

@admin_required
def logs_console(request):
    logs_list = SystemLog.objects.all().order_by("-created_at")
    
    level_filter = request.GET.get("level", "").strip()
    category_filter = request.GET.get("category", "").strip()
    q = request.GET.get("q", "").strip()
    
    if level_filter:
        logs_list = logs_list.filter(level=level_filter)
    if category_filter:
        logs_list = logs_list.filter(category=category_filter)
    if q:
        logs_list = logs_list.filter(message__icontains=q)
        
    from django.core.paginator import Paginator
    paginator = Paginator(logs_list, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        "active_nav": "logs",
        "page_obj": page_obj,
        "level": level_filter,
        "category": category_filter,
        "q": q,
    }
    return render(request, "admin_panel/logs.html", context)


@admin_required
def log_stream(request):
    """
    JSON polling endpoint returning SystemLog events dynamically.
    """
    last_id = request.GET.get('last_id', 0)
    try:
        last_id = int(last_id)
    except ValueError:
        last_id = 0
        
    if last_id == 0:
        last_log = SystemLog.objects.order_by("-id").first()
        last_id = last_log.id if last_log else 0
        return JsonResponse({"logs": [], "last_id": last_id})
        
    new_logs = SystemLog.objects.filter(id__gt=last_id).order_by("id")[:20]
    
    logs_data = []
    for log in new_logs:
        last_id = log.id
        logs_data.append({
            "id": log.id,
            "level": log.level,
            "category": log.category,
            "message": log.message,
            "time": log.created_at.strftime("%H:%M:%S"),
        })
        
    return JsonResponse({
        "logs": logs_data,
        "last_id": last_id
    })


# ─────────────────────────────────────────────────────────────
# SYSTEM CONFIGURATION
# ─────────────────────────────────────────────────────────────

@admin_required
def system_settings(request):
    alert_config = AlertConfig.objects.first()
    if not alert_config:
        alert_config = AlertConfig.objects.create(alert_email="admin@subhero.ng")
        
    if request.method == "POST":
        keys_to_update = [
            "admin_ip_whitelist",
            "maintenance_mode",
            "disable_registrations",
            "max_vtu_amount",
            "max_p2p_amount",
        ]
        
        changes = []
        with transaction.atomic():
            for key in keys_to_update:
                old_val = SystemSetting.get(key, "")
                new_val = request.POST.get(key, "").strip()
                
                if key in ["maintenance_mode", "disable_registrations"]:
                    new_val = "True" if request.POST.get(key) == "on" else "False"
                    
                if old_val != new_val:
                    SystemSetting.set(key, new_val)
                    changes.append(f"{key}: '{old_val}' -> '{new_val}'")
            
            # Update alert email and rate inline
            old_email = alert_config.alert_email
            new_email = request.POST.get("alert_email", "").strip()
            old_rate = alert_config.usd_ngn_rate
            new_rate_str = request.POST.get("usd_ngn_rate", "1600").strip()
            
            try:
                new_rate = Decimal(new_rate_str)
            except InvalidOperation:
                new_rate = old_rate
                
            if old_email != new_email or old_rate != new_rate:
                alert_config.alert_email = new_email
                alert_config.usd_ngn_rate = new_rate
                alert_config.save()
                changes.append(f"alert_email: '{old_email}' -> '{new_email}'")
                changes.append(f"usd_ngn_rate: '{old_rate}' -> '{new_rate}'")

            # Update VTU profit margin and recalculate default plans (markup_value == 0)
            vtu_margin_pct_str = request.POST.get("vtu_profit_margin", "10.00").strip()
            try:
                vtu_margin_pct = Decimal(vtu_margin_pct_str)
            except InvalidOperation:
                vtu_margin_pct = Decimal("10.00")
            old_margin_pct = Decimal(SystemSetting.get("vtu_profit_margin", "10.00"))
            if old_margin_pct != vtu_margin_pct:
                SystemSetting.set("vtu_profit_margin", str(vtu_margin_pct))
                changes.append(f"vtu_profit_margin: '{old_margin_pct}%' -> '{vtu_margin_pct}%'")
                
                margin = vtu_margin_pct / Decimal("100")
                plans_updated = VTUPlan.objects.filter(markup_value=0).update(
                    subhero_price=F('provider_price') * (Decimal('1') + margin)
                )
                changes.append(f"Recalculated {plans_updated} VTU plan prices based on new margin")

            # Update SMM profit margin and recalculate default services (markup_value == 0)
            smm_margin_pct_str = request.POST.get("smm_profit_margin", "50.00").strip()
            try:
                smm_margin_pct = Decimal(smm_margin_pct_str)
            except InvalidOperation:
                smm_margin_pct = Decimal("50.00")
            old_smm_margin_pct = Decimal(SystemSetting.get("smm_profit_margin", "50.00"))
            smm_setting_changed = old_smm_margin_pct != smm_margin_pct
            if smm_setting_changed:
                SystemSetting.set("smm_profit_margin", str(smm_margin_pct))
                changes.append(f"smm_profit_margin: '{old_smm_margin_pct}%' -> '{smm_margin_pct}%'")
            
            if smm_setting_changed or old_rate != new_rate:
                smm_margin = smm_margin_pct / Decimal("100")
                rate_to_use = Decimal(str(new_rate))
                multiplier = rate_to_use * (Decimal("1") + smm_margin)
                services_updated = SMMService.objects.filter(markup_value=0).update(
                    subhero_price_per_1k=F('provider_rate') * multiplier
                )
                changes.append(f"Recalculated {services_updated} SMM service prices based on new margin/rate")
                
        if changes:
            detail = f"Updated system settings: {', '.join(changes)}"
            log_admin_action(request.user, "SETTINGS_UPDATE", "SystemSetting", "GLOBAL", detail, request)
            
        return redirect("admin_panel:settings")
        
    settings_dict = {
        "admin_ip_whitelist": SystemSetting.get("admin_ip_whitelist", ""),
        "maintenance_mode": SystemSetting.get("maintenance_mode", "False") == "True",
        "disable_registrations": SystemSetting.get("disable_registrations", "False") == "True",
        "max_vtu_amount": SystemSetting.get("max_vtu_amount", "10000.00"),
        "max_p2p_amount": SystemSetting.get("max_p2p_amount", "50000.00"),
        "vtu_profit_margin": SystemSetting.get("vtu_profit_margin", "10.00"),
        "smm_profit_margin": SystemSetting.get("smm_profit_margin", "50.00"),
    }
    
    context = {
        "active_nav": "settings",
        "settings": settings_dict,
        "alert_config": alert_config,
    }
    return render(request, "admin_panel/settings.html", context)


@admin_required
def transactions_list(request):
    type_filter = request.GET.get("type", "").strip()
    status_filter = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()
    
    import datetime
    cutoff_date = datetime.datetime(2026, 7, 4, tzinfo=datetime.timezone.utc)
    txns = WalletTransaction.objects.filter(created_at__gte=cutoff_date).select_related("wallet__user")
    
    if type_filter:
        txns = txns.filter(txn_type=type_filter)
    if status_filter:
        txns = txns.filter(status=status_filter)
    if q:
        txns = txns.filter(
            Q(reference__icontains=q) |
            Q(wallet__user__phone_number__icontains=q) |
            Q(wallet__user__email__icontains=q)
        )
        
    total_volume = txns.filter(status="SUCCESS").exclude(
        txn_type__in=[
            WalletTransaction.TxnType.REFUND,
            WalletTransaction.TxnType.GIVEAWAY_LOCK,
            WalletTransaction.TxnType.P2P_RECEIVE
        ]
    ).aggregate(sum=Sum('amount'))['sum'] or Decimal("0")
    
    from django.core.paginator import Paginator
    paginator = Paginator(txns.order_by("-created_at"), 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        "active_nav": "transactions",
        "page_obj": page_obj,
        "type": type_filter,
        "status": status_filter,
        "q": q,
        "total_volume": total_volume,
        "txn_types": WalletTransaction.TxnType.choices,
        "statuses": WalletTransaction.Status.choices,
    }
    return render(request, "admin_panel/transactions.html", context)


@admin_required
def export_transactions_csv(request):
    type_filter = request.GET.get("type", "").strip()
    status_filter = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()
    
    txns = WalletTransaction.objects.all().select_related("wallet__user").order_by("-created_at")
    
    if type_filter:
        txns = txns.filter(txn_type=type_filter)
    if status_filter:
        txns = txns.filter(status=status_filter)
    if q:
        txns = txns.filter(
            Q(reference__icontains=q) |
            Q(wallet__user__phone_number__icontains=q) |
            Q(wallet__user__email__icontains=q)
        )
        
    class Echo:
        def write(self, value):
            return value
            
    def row_generator():
        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)
        
        yield pseudo_buffer.write(["Transaction ID", "Reference", "User Name", "User Email", "Type", "Amount (₦)", "Before (₦)", "After (₦)", "Status", "Date"])
        
        for t in txns.iterator():
            user = t.wallet.user if t.wallet else None
            name = user.full_name if user else "System"
            email = user.email if user else ""
            date_str = t.created_at.strftime("%Y-%m-%d %H:%M:%S")
            yield pseudo_buffer.write([
                str(t.id), t.reference, name, email, t.txn_type,
                f"{t.amount:.2f}", f"{t.balance_before:.2f}", f"{t.balance_after:.2f}", t.status, date_str
            ])
            
    response = StreamingHttpResponse(row_generator(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="subhero_transactions_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    return response

@admin_required
def giveaways_list(request):
    from apps.giveaway.models import Giveaway
    from django.core.paginator import Paginator
    from django.db.models import Sum, Count

    status_filter = request.GET.get("status", "").strip()
    type_filter = request.GET.get("type", "").strip()
    q = request.GET.get("q", "").strip()

    giveaways = Giveaway.objects.all().select_related("host").order_by("-created_at")

    if status_filter:
        giveaways = giveaways.filter(status=status_filter)
    if type_filter:
        giveaways = giveaways.filter(giveaway_type=type_filter)
    if q:
        giveaways = giveaways.filter(
            Q(slug__icontains=q) |
            Q(title__icontains=q) |
            Q(host__email__icontains=q) |
            Q(host__phone_number__icontains=q)
        )

    # Analytics metrics for giveaways
    total_count = Giveaway.objects.count()
    total_spent = Giveaway.objects.aggregate(sum=Sum('total_spent'))['sum'] or Decimal('0.00')
    total_locked = Giveaway.objects.filter(status='ACTIVE').aggregate(
        locked=Sum(F('total_locked') - F('total_spent'))
    )['locked'] or Decimal('0.00')
    
    metrics = {
        'total_count': total_count,
        'total_locked': total_locked,
        'total_spent': total_spent
    }

    paginator = Paginator(giveaways, 30)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "active_nav": "giveaways",
        "page_obj": page_obj,
        "status": status_filter,
        "type": type_filter,
        "q": q,
        "metrics": metrics
    }
    return render(request, "admin_panel/giveaways.html", context)


# ─────────────────────────────────────────────────────────────
# ANALYTICS DASHBOARD
# ─────────────────────────────────────────────────────────────

from django.http import JsonResponse
from apps.admin_panel.queries import (
    get_total_wallet_balance, get_gross_revenue, get_net_profit,
    get_deposit_fee_revenue, get_revenue_chart_data, get_average_order_value,
    get_total_refunds, get_user_stats, get_user_growth_chart,
    get_top_users_by_spend, get_arpu, get_vtu_stats,
    get_vtu_network_split, get_vtu_service_split, get_top_vtu_plans,
    get_vtu_orders_by_hour, get_smm_stats, get_smm_platform_split,
    get_smm_avg_delivery_time, get_giveaway_stats, get_giveaway_claim_rate,
    get_top_giveaway_hosts, get_transaction_stats, get_peak_transaction_hour
)

from datetime import date, timedelta

def parse_date_range(range_param):
    today = timezone.now().date()
    if range_param == 'today':
        return today, today + timedelta(days=1)
    elif range_param == '7d':
        return today - timedelta(days=7), today
    elif range_param == '90d':
        return today - timedelta(days=90), today
    elif range_param == '1y':
        return today - timedelta(days=365), today
    elif range_param == 'all':
        return date.min, today
    elif range_param.startswith('custom:'):
        try:
            parts = range_param.replace('custom:', '').split(',')
            return date.fromisoformat(parts[0]), date.fromisoformat(parts[1])
        except Exception:
            pass
    # default is 30d
    return today - timedelta(days=30), today


@admin_required
def analytics_page(request):
    """Main analytics page — initial load"""
    range_param = request.GET.get('range', '30d')
    start, end = parse_date_range(range_param)

    context = {
        'active_nav': 'analytics',
        'range': range_param,
        'total_wallet_balance': get_total_wallet_balance(),
        'revenue': get_gross_revenue(start, end),
        'profit': get_net_profit(start, end),
        'deposit_fees': get_deposit_fee_revenue(start, end),
        'user_stats': get_user_stats(start, end),
        'refunds': get_total_refunds(start, end),
    }
    return render(request, 'admin_panel/analytics.html', context)


@admin_required
def analytics_data(request):
    """HTMX endpoint — returns updated metric cards when date range filter changes"""
    range_param = request.GET.get('range', '30d')
    tab = request.GET.get('tab', 'overview')
    start, end = parse_date_range(range_param)

    if tab == 'overview':
        context = {
            'revenue': get_gross_revenue(start, end),
            'profit': get_net_profit(start, end),
            'deposit_fees': get_deposit_fee_revenue(start, end),
            'user_stats': get_user_stats(start, end),
            'refunds': get_total_refunds(start, end),
            'total_wallet_balance': get_total_wallet_balance(),
        }
        return render(request, 'admin_panel/partials/analytics_overview.html', context)

    elif tab == 'users':
        context = {
            'user_stats': get_user_stats(start, end),
            'top_users': get_top_users_by_spend(10),
            'arpu': get_arpu(start, end),
        }
        return render(request, 'admin_panel/partials/analytics_users.html', context)

    elif tab == 'vtu':
        context = {
            'vtu_stats': get_vtu_stats(start, end),
            'network_split': get_vtu_network_split(start, end),
            'service_split': get_vtu_service_split(start, end),
            'top_plans': get_top_vtu_plans(start, end),
            'hourly': get_vtu_orders_by_hour(start, end),
        }
        return render(request, 'admin_panel/partials/analytics_vtu.html', context)

    elif tab == 'smm':
        context = {
            'smm_stats': get_smm_stats(start, end),
            'platform_split': get_smm_platform_split(start, end),
            'avg_delivery': get_smm_avg_delivery_time(start, end),
        }
        return render(request, 'admin_panel/partials/analytics_smm.html', context)

    elif tab == 'giveaway':
        context = {
            'giveaway_stats': get_giveaway_stats(start, end),
            'claim_rate': get_giveaway_claim_rate(start, end),
            'top_hosts': get_top_giveaway_hosts(start, end),
        }
        return render(request, 'admin_panel/partials/analytics_giveaway.html', context)

    elif tab == 'transactions':
        context = {
            'txn_stats': get_transaction_stats(start, end),
            'peak_hour': get_peak_transaction_hour(),
        }
        return render(request, 'admin_panel/partials/analytics_transactions.html', context)

    return HttpResponse("Invalid active tab", status=400)


@admin_required
def analytics_chart_data(request):
    """JSON endpoint for Chart.js — returns chart data"""
    chart = request.GET.get('chart')
    range_param = request.GET.get('range', '30d')
    start, end = parse_date_range(range_param)
    cache_key = f'chart:{chart}:{range_param}'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached, safe=False)

    if chart == 'revenue':
        data = get_revenue_chart_data(start, end)
        result = {
            'labels': [d['day'].strftime('%b %d') for d in data],
            'revenue': [float(d['revenue']) for d in data],
            'profit': [float(d['profit']) for d in data],
        }
    elif chart == 'user_growth':
        data = get_user_growth_chart(start, end)
        result = {
            'labels': [d['day'].strftime('%b %d') for d in data],
            'counts': [d['count'] for d in data],
        }
    elif chart == 'vtu_network':
        data = get_vtu_network_split(start, end)
        result = {
            'labels': [d['network'].upper() for d in data],
            'counts': [d['count'] for d in data],
            'colors': ['#FFCC00', '#E40000', '#00AA00', '#006B3E'],
        }
    elif chart == 'vtu_hourly':
        data = get_vtu_orders_by_hour(start, end)
        hours = {d['hour']: d['count'] for d in data}
        result = {
            'labels': [f'{h:02d}:00' for h in range(24)],
            'counts': [hours.get(h, 0) for h in range(24)],
        }
    elif chart == 'smm_platform':
        data = get_smm_platform_split(start, end)
        result = {
            'labels': [d['platform'].capitalize() if d['platform'] else "Other" for d in data],
            'counts': [d['count'] for d in data],
        }
    elif chart == 'giveaway_claims':
        data = list(
            GiveawayClaim.objects.filter(
                status='SUCCESS',
                claimed_at__range=(
                    datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
                    datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
                )
            ).annotate(
                day=TruncDate('claimed_at')
            ).values('day').annotate(
                count=Count('id')
            ).order_by('day')
        )
        result = {
            'labels': [d['day'].strftime('%b %d') for d in data],
            'counts': [d['count'] for d in data],
        }
    else:
        result = {}

    cache.set(cache_key, result, timeout=300)
    return JsonResponse(result, safe=False)
