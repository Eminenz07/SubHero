from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.urls import reverse
from django.core.cache import cache

from apps.giveaway.models import Giveaway, GiveawayEscrow, GiveawayClaim
from apps.giveaway.utils import generate_giveaway_slug, generate_qr_code_base64
from apps.wallet.models import Wallet, WalletTransaction
from apps.vtu.models import VTUPlan
from apps.giveaway.tasks import process_giveaway_claim

@login_required
def create_giveaway(request):
    if request.method == 'POST':
        try:
            reward_type = request.POST.get('reward_type')
            network = request.POST.get('network')
            
            try:
                slots = int(request.POST.get('slots', 0))
            except ValueError:
                messages.error(request, "Number of recipients must be a valid integer.")
                return redirect('giveaway:create')
                
            title = request.POST.get('title') or "Giveaway 🎉"
            pin = request.POST.get('transaction_pin')
            
            # Verify PIN
            if not request.user.check_pin(pin):
                messages.error(request, "Invalid transaction PIN.")
                return redirect('giveaway:create')
                
            if slots < 1:
                messages.error(request, "Number of recipients must be at least 1.")
                return redirect('giveaway:create')

            amount_per_slot = Decimal('0.00')
            plan_id = ""

            if reward_type == 'DATA':
                plan_id = request.POST.get('plan_id')
                if not plan_id:
                    messages.error(request, "Please select a valid data plan.")
                    return redirect('giveaway:create')
                plan = get_object_or_404(VTUPlan, plan_id=plan_id)
                network = plan.network # Use the actual plan's network, not the user's potentially out-of-sync selection
                amount_per_slot = plan.subhero_price
            else:
                try:
                    amount_per_slot = Decimal(request.POST.get('amount_per_slot', 0))
                except (ValueError, ArithmeticError):
                    messages.error(request, "Invalid airtime amount.")
                    return redirect('giveaway:create')
                    
                if amount_per_slot < Decimal('10'):
                    messages.error(request, "Airtime amount per recipient must be at least ₦10.")
                    return redirect('giveaway:create')

            total_cost = amount_per_slot * slots
            
            with transaction.atomic():
                wallet = Wallet.objects.select_for_update().get(user=request.user)
                if wallet.balance < total_cost:
                    messages.error(request, "Insufficient wallet balance.")
                    return redirect('giveaway:create')
                
                # Deduct wallet
                balance_before = wallet.balance
                wallet.balance -= total_cost
                wallet.save()

                # Generate unique slug
                slug = generate_giveaway_slug()
                while Giveaway.objects.filter(slug=slug).exists():
                    slug = generate_giveaway_slug()

                claim_url = f"{request.scheme}://{request.get_host()}/g/{slug}"
                qr_base64 = generate_qr_code_base64(claim_url)

                giveaway = Giveaway.objects.create(
                    host=request.user,
                    slug=slug,
                    title=title,
                    giveaway_type=reward_type,
                    network=network,
                    plan_id=plan_id,
                    amount_per_slot=amount_per_slot,
                    total_slots=slots,
                    total_locked=total_cost,
                    qr_code_base64=qr_base64
                )

                GiveawayEscrow.objects.create(
                    giveaway=giveaway,
                    wallet=wallet,
                    locked_amount=total_cost,
                    debit_reference=f"ESCROW_{giveaway.id}"
                )
                
                # Wallet Transaction
                WalletTransaction.objects.create(
                    wallet=wallet,
                    txn_type=WalletTransaction.TxnType.GIVEAWAY_LOCK,
                    amount=total_cost,
                    balance_before=balance_before,
                    balance_after=wallet.balance,
                    status=WalletTransaction.Status.SUCCESS,
                    reference=f"GWY_LOCK_{giveaway.id}",
                    description=f"Locked funds for giveaway: {title}"
                )

            messages.success(request, "Giveaway created successfully!")
            return redirect('giveaway:detail', slug=slug)
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('giveaway:create')

    # GET Request
    plans = VTUPlan.objects.filter(is_active=True).order_by('network', 'subhero_price')
    return render(request, 'giveaway/create.html', {'plans': plans})


@login_required
def my_giveaways(request):
    giveaways = Giveaway.objects.filter(host=request.user).order_by('-created_at')
    return render(request, 'giveaway/mine.html', {'giveaways': giveaways})

@login_required
def giveaway_detail(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug, host=request.user)
    return render(request, 'giveaway/detail.html', {'giveaway': giveaway})

import re

PHONE_REGEX = re.compile(r'^(0[7-9][0-1]\d{8}|\+234[7-9][0-1]\d{8}|234[7-9][0-1]\d{8})$')

def normalize_phone(raw_phone: str) -> str:
    if not raw_phone:
        return ""
    phone = str(raw_phone).replace("+", "").replace(" ", "").strip()
    if phone.startswith("234"):
        phone = "0" + phone[3:]
    if len(phone) == 10 and not phone.startswith("0"):
        phone = "0" + phone
    return phone

def get_network_by_prefix(phone: str) -> str:
    if not phone or len(phone) < 4:
        return None
    prefix = phone[:4]
    mtn_prefixes = {'0703', '0706', '0803', '0806', '0810', '0813', '0814', '0816', '0903', '0906', '0913', '0916'}
    airtel_prefixes = {'0701', '0708', '0802', '0808', '0812', '0901', '0902', '0904', '0907', '0912'}
    glo_prefixes = {'0705', '0805', '0807', '0811', '0815', '0905', '0915'}
    nine_mobile_prefixes = {'0809', '0817', '0818', '0908', '0909'}
    
    if prefix in mtn_prefixes:
        return 'mtn'
    elif prefix in airtel_prefixes:
        return 'airtel'
    elif prefix in glo_prefixes:
        return 'glo'
    elif prefix in nine_mobile_prefixes:
        return '9mobile'
    return None

# ================= PUBLIC VIEWS =================
def claim_page(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug)
    
    if not giveaway.is_claimable:
        return render(request, 'giveaway/closed.html', {'giveaway': giveaway})
        
    if request.method == 'POST':
        raw_phone = request.POST.get('phone_number')
        if not raw_phone:
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'Phone number required'})
            
        if not PHONE_REGEX.match(raw_phone.strip()):
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'Invalid Nigerian phone number format. Use 080XXXXXXXX.'})
            
        normalized_phone = normalize_phone(raw_phone)
        
        # Self-claim check
        if normalized_phone == normalize_phone(giveaway.host.phone_number):
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'You cannot claim your own giveaway!'})
            
        # Network mismatch validation (skip if network is 'all')
        if giveaway.network != 'all':
            detected_network = get_network_by_prefix(normalized_phone)
            if not detected_network or detected_network != giveaway.network:
                expected_net = giveaway.get_network_display()
                detected_net = detected_network.upper() if detected_network else 'unknown'
                return render(request, 'giveaway/claim.html', {
                    'giveaway': giveaway,
                    'error': f"This number looks like an {detected_net} line. This giveaway is for {expected_net} numbers only."
                })
            
        try:
            with transaction.atomic():
                giveaway_locked = Giveaway.objects.select_for_update().get(id=giveaway.id)
                
                if giveaway_locked.remaining_slots <= 0 or giveaway_locked.status != 'ACTIVE':
                    return render(request, 'giveaway/closed.html', {'giveaway': giveaway_locked})
                
                # Delete any failed claims first so the user can retry
                GiveawayClaim.objects.filter(giveaway=giveaway_locked, phone_number=normalized_phone, status='FAILED').delete()
                
                # Check for active or pending claims
                if GiveawayClaim.objects.filter(giveaway=giveaway_locked, phone_number=normalized_phone).exists():
                    return render(request, 'giveaway/claim.html', {'giveaway': giveaway_locked, 'error': 'Number already claimed!'})
 
                giveaway_locked.claimed_slots += 1
                giveaway_locked.save(update_fields=['claimed_slots'])
                
                claim = GiveawayClaim.objects.create(
                    giveaway=giveaway_locked,
                    phone_number=normalized_phone,
                    amount=giveaway_locked.amount_per_slot,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
            # Dispatch Celery Task
            process_giveaway_claim.delay(claim.id)
            return redirect('giveaway:claim_status', slug=giveaway.slug, claim_id=claim.id)
            
        except Exception as e:
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'An error occurred. Try again later.'})

    return render(request, 'giveaway/claim.html', {'giveaway': giveaway})

def claim_status(request, slug, claim_id):
    claim = get_object_or_404(GiveawayClaim, id=claim_id, giveaway__slug=slug)
    if claim.status == 'SUCCESS':
        if request.headers.get('HX-Request'):
            response = HttpResponse()
            response['HX-Redirect'] = reverse('giveaway:claim_success', kwargs={'slug': slug})
            return response
        return redirect('giveaway:claim_success', slug=slug)
    elif claim.status == 'FAILED':
        if request.headers.get('HX-Request'):
            response = HttpResponse()
            response['HX-Redirect'] = reverse('giveaway:claim_failed', kwargs={'slug': slug})
            return response
        return redirect('giveaway:claim_failed', slug=slug)
        
    # HTMX Polling Endpoint
    if request.headers.get('HX-Request'):
        return render(request, 'giveaway/partials/_claim_status.html', {'claim': claim})
        
    return render(request, 'giveaway/pending.html', {'claim': claim})

def claim_success(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug)
    return render(request, 'giveaway/success.html', {'giveaway': giveaway})

def claim_failed(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug)
    return render(request, 'giveaway/failed.html', {'giveaway': giveaway})
