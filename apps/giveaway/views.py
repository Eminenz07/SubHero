from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.urls import reverse
from django.core.cache import cache
from django.utils.timezone import now

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
            
            # Parse optional expires_at
            expires_at = None
            expires_at_raw = request.POST.get('expires_at')
            if expires_at_raw:
                from django.utils.dateparse import parse_datetime
                from django.utils.timezone import is_aware, make_aware, get_current_timezone
                parsed_dt = parse_datetime(expires_at_raw)
                if parsed_dt:
                    if not is_aware(parsed_dt):
                        parsed_dt = make_aware(parsed_dt, get_current_timezone())
                    if parsed_dt <= now():
                        messages.error(request, "Expiry date and time must be in the future.")
                        return redirect('giveaway:create')
                    expires_at = parsed_dt
                else:
                    messages.error(request, "Invalid expiry date/time format.")
                    return redirect('giveaway:create')
            
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
                    qr_code_base64=qr_base64,
                    expires_at=expires_at
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
    wallet_balance = request.user.wallet.balance if hasattr(request.user, 'wallet') else Decimal('0.00')
    return render(request, 'giveaway/create.html', {'plans': plans, 'wallet_balance': wallet_balance})


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

import datetime

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

# ================= PUBLIC VIEWS =================
def claim_page(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug)
    
    if not giveaway.is_claimable:
        return render(request, 'giveaway/closed.html', {'giveaway': giveaway})
        
    if request.method == 'POST':
        ip_address = get_client_ip(request)
        
        # Rate limit 1: Per IP daily across all giveaways (max 10 successful claims)
        today_str = datetime.date.today().isoformat()
        daily_cache_key = f"ga_daily_success:{ip_address}:{today_str}"
        daily_count = cache.get(daily_cache_key, 0)
        if daily_count >= 10:
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'Daily limit of 10 successful claims exceeded for this IP.'})
            
        # Rate limit 2: Per IP per giveaway (max 2 successful claims per hour)
        gwy_cache_key = f"ga_success:{giveaway.id}:{ip_address}"
        success_count = cache.get(gwy_cache_key, 0)
        if success_count >= 2:
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'This IP address has already successfully claimed from this giveaway the maximum allowed times.'})
            
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
                if not giveaway_locked.is_claimable:
                    return render(request, 'giveaway/closed.html', {'giveaway': giveaway_locked})
                    
                # Clean up any failed attempts for this number so they can retry
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
                    ip_address=ip_address
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
        redirect_url = reverse('giveaway:claim_success', kwargs={'slug': slug}) + f"?phone={claim.phone_number}"
        if request.headers.get('HX-Request'):
            response = HttpResponse()
            response['HX-Redirect'] = redirect_url
            return response
        return redirect(redirect_url)
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
    phone = request.GET.get('phone', '')
    register_url = reverse('accounts:register') + f"?phone={phone}&source=giveaway&ref={slug}"
    return render(request, 'giveaway/success.html', {
        'giveaway': giveaway,
        'phone': phone,
        'register_url': register_url
    })

def claim_failed(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug)
    return render(request, 'giveaway/failed.html', {'giveaway': giveaway})

@login_required
def cancel_giveaway(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug, host=request.user)
    
    if giveaway.status != 'ACTIVE':
        messages.error(request, "Only active giveaways can be cancelled.")
        return redirect('giveaway:detail', slug=slug)
        
    if giveaway.claimed_slots > 0:
        messages.error(request, "Giveaways with active claims cannot be cancelled.")
        return redirect('giveaway:detail', slug=slug)
        
    try:
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(user=request.user)
            balance_before = wallet.balance
            
            # Refund escrow
            refund_amount = giveaway.total_locked
            wallet.balance += refund_amount
            wallet.save()
            
            # Update giveaway
            giveaway.status = 'CANCELLED'
            giveaway.save()
            
            # Transaction log
            WalletTransaction.objects.create(
                wallet=wallet,
                txn_type=WalletTransaction.TxnType.REFUND,
                amount=refund_amount,
                balance_before=balance_before,
                balance_after=wallet.balance,
                status=WalletTransaction.Status.SUCCESS,
                reference=f"GWY_REFUND_{giveaway.id}",
                description=f"Cancelled giveaway refund: {giveaway.title}"
            )
            
        messages.success(request, f"Giveaway cancelled successfully! ₦{refund_amount} has been refunded to your wallet.")
    except Exception as e:
        messages.error(request, f"Failed to cancel giveaway: {str(e)}")
        
    return redirect('giveaway:mine')

import os
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

import qrcode

@login_required
def giveaway_receipt_card(request, slug):
    giveaway = get_object_or_404(Giveaway, slug=slug, host=request.user)
    
    width = 1080
    height = 1440
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    NAVY = (15, 23, 42)          # #0F172A
    GREEN = (0, 107, 62)        # #006B3E
    GRAY = (100, 116, 139)       # #64748B
    LIGHT_GRAY = (203, 213, 225) # #CBD5E1

    def get_font(size):
        font_paths = [
            os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Inter.ttf'),
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    font_hero = get_font(68)
    font_sub = get_font(34)
    font_date = get_font(26)
    font_label = get_font(30)
    font_val = get_font(30)
    font_footer = get_font(24)

    # 1. Top Header Logo
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'sh-logo.png')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'favicon.png')

    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            w_percent = (320 / float(logo.width))
            h_size = int((float(logo.height) * float(w_percent)))
            logo = logo.resize((320, h_size), Image.LANCZOS)
            img.paste(logo, (80, 75), mask=logo)
        except Exception:
            pass

    # Right: Small QR Code linking to site URL
    try:
        site_url = f"{request.scheme}://{request.get_host()}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1
        )
        qr.add_data(site_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0F172A", back_color="white").convert("RGB")
        qr_img = qr_img.resize((130, 130), Image.LANCZOS)
        img.paste(qr_img, (width - 210, 65))
    except Exception:
        pass

    # 2. Hero Amount
    total_val = giveaway.claimed_slots * giveaway.amount_per_slot if giveaway.claimed_slots > 0 else giveaway.total_locked
    total_val_str = f"₦ {int(total_val):,}.00"
    draw.text((width // 2, 270), total_val_str, fill=NAVY, font=font_hero, anchor="mm")

    # 3. Status Text + Drawn Checkmark Icon
    status_text = "Giveaway Successful"
    bbox = draw.textbbox((0, 0), status_text, font=font_sub)
    text_w = bbox[2] - bbox[0]

    center_x = width // 2
    status_y = 360

    text_x = center_x - 24
    draw.text((text_x, status_y), status_text, fill=NAVY, font=font_sub, anchor="mm")

    icon_x = text_x + (text_w // 2) + 24
    icon_y = status_y
    r = 18
    draw.ellipse([icon_x - r, icon_y - r, icon_x + r, icon_y + r], fill=GREEN)
    draw.line([(icon_x - 8, icon_y), (icon_x - 2, icon_y + 6)], fill=(255, 255, 255), width=4)
    draw.line([(icon_x - 2, icon_y + 6), (icon_x + 8, icon_y - 6)], fill=(255, 255, 255), width=4)

    # 4. Date
    date_str = giveaway.created_at.strftime("%B %d, %Y %I:%M:%S %p")
    draw.text((width // 2, 420), date_str, fill=GREEN, font=font_date, anchor="mm")

    # 5. Top Dashed Line
    def draw_dashed_line(y):
        dash_len = 16
        gap_len = 10
        x = 80
        while x < width - 80:
            draw.line([(x, y), (min(x + dash_len, width - 80), y)], fill=LIGHT_GRAY, width=3)
            x += dash_len + gap_len

    draw_dashed_line(490)

    # 6. Key-Value Rows
    type_label = "Data Top up" if giveaway.giveaway_type == 'DATA' else "Airtime Top up"
    host_name = giveaway.host.get_full_name() or giveaway.host.username

    rows = [
        ("Giveaway Type:", type_label),
        ("Network Provider:", giveaway.get_network_display()),
        ("Amount Per Slot:", f"₦{int(giveaway.amount_per_slot):,}"),
        ("Slots Claimed:", f"{giveaway.claimed_slots} / {giveaway.total_slots}"),
        ("Giveaway ID:", giveaway.slug),
        ("Host Name:", host_name),
    ]

    start_y = 560
    row_height = 95

    for i, (label, val) in enumerate(rows):
        y = start_y + (i * row_height)
        draw.text((80, y), label, fill=GREEN, font=font_label, anchor="lm")
        draw.text((width - 80, y), val, fill=NAVY, font=font_val, anchor="rm")

    # 7. Bottom Dashed Line
    draw_dashed_line(start_y + (len(rows) * row_height) + 20)

    # 8. Footer
    footer_text = "Enjoy cheap subscriptions to all networks endlessly"
    draw.text((width // 2, 1340), footer_text, fill=GRAY, font=font_footer, anchor="mm")

    response = HttpResponse(content_type="image/png")
    response['Content-Disposition'] = f'attachment; filename="giveaway_receipt_{giveaway.slug}.png"'
    img.save(response, "PNG")
    return response
