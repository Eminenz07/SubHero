import base64
import os
import logging
from io import BytesIO
from decimal import Decimal
from PIL import Image, ImageDraw, ImageFont

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.urls import reverse
from django.core.cache import cache
from django.utils.timezone import now
from django.conf import settings

from apps.giveaway.models import Giveaway, GiveawayEscrow, GiveawayClaim
from apps.giveaway.utils import generate_giveaway_slug, generate_qr_code_base64
from apps.wallet.models import Wallet, WalletTransaction
from apps.vtu.models import VTUPlan
from apps.giveaway.tasks import process_giveaway_claim

logger = logging.getLogger(__name__)

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

    # Auto-resolve any claims that were stuck in PENDING
    pending_claims = list(giveaway.claims.filter(status='PENDING'))
    if pending_claims:
        from apps.giveaway.tasks import process_giveaway_claim
        for p_claim in pending_claims:
            try:
                process_giveaway_claim(str(p_claim.id))
            except Exception as p_err:
                logger.error("Error auto-resolving pending claim %s: %s", p_claim.id, p_err)
        giveaway.refresh_from_db()

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
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf_ip:
        return cf_ip.strip()
    x_real_ip = request.META.get('HTTP_X_REAL_IP')
    if x_real_ip:
        return x_real_ip.strip()
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')

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
                    
                # Clean up any failed or pending attempts for this number so they can retry
                GiveawayClaim.objects.filter(giveaway=giveaway_locked, phone_number=normalized_phone, status__in=['FAILED', 'PENDING']).delete()
                
                # Check for successfully claimed numbers
                if GiveawayClaim.objects.filter(giveaway=giveaway_locked, phone_number=normalized_phone, status='SUCCESS').exists():
                    return render(request, 'giveaway/claim.html', {'giveaway': giveaway_locked, 'error': 'This phone number has already claimed from this giveaway!'})
 
                giveaway_locked.claimed_slots += 1
                giveaway_locked.save(update_fields=['claimed_slots'])
                
                claim = GiveawayClaim.objects.create(
                    giveaway=giveaway_locked,
                    phone_number=normalized_phone,
                    amount=giveaway_locked.amount_per_slot,
                    ip_address=ip_address
                )

            # Process claim immediately so vending and SMS happen in real-time
            try:
                process_giveaway_claim(str(claim.id))
            except Exception as proc_err:
                logger.error("Immediate claim process error: %s", proc_err)
                try:
                    process_giveaway_claim.delay(str(claim.id))
                except Exception as delay_err:
                    logger.error("Celery delay fallback error: %s", delay_err)
                    # If immediate and delay both failed (e.g. broker error), fail and release slot
                    with transaction.atomic():
                        claim.status = 'FAILED'
                        claim.save(update_fields=['status'])
                        giveaway_locked.refresh_from_db()
                        giveaway_locked.claimed_slots = max(0, giveaway_locked.claimed_slots - 1)
                        giveaway_locked.save(update_fields=['claimed_slots'])

            claim.refresh_from_db()

            # Trigger Web Push notification to giveaway host
            try:
                from apps.notifications.services import send_push_notification
                send_push_notification(
                    user=giveaway.host,
                    title="🎉 Giveaway Slot Claimed!",
                    body=f"{giveaway_locked.claimed_slots} of {giveaway_locked.total_slots} slots claimed in your {giveaway_locked.get_giveaway_type_display()} Giveaway.",
                    action_url=f"/giveaway/{giveaway_locked.slug}/",
                    level="info"
                )
            except Exception:
                pass

            if claim.status == 'SUCCESS':
                return redirect(reverse('giveaway:claim_success', kwargs={'slug': giveaway.slug}) + f"?phone={claim.phone_number}")
            elif claim.status == 'FAILED':
                return redirect('giveaway:claim_failed', slug=giveaway.slug)

            return redirect('giveaway:claim_status', slug=giveaway.slug, claim_id=claim.id)
            
        except Exception as e:
            logger.exception("Error during giveaway claim: %s", e)
            return render(request, 'giveaway/claim.html', {'giveaway': giveaway, 'error': 'An error occurred while processing your claim. Please try again.'})

    return render(request, 'giveaway/claim.html', {'giveaway': giveaway})

def claim_status(request, slug, claim_id):
    claim = get_object_or_404(GiveawayClaim, id=claim_id, giveaway__slug=slug)

    # If still pending, process it on demand
    if claim.status == 'PENDING':
        try:
            from apps.giveaway.tasks import process_giveaway_claim
            process_giveaway_claim(str(claim.id))
            claim.refresh_from_db()
        except Exception as proc_err:
            logger.error("claim_status on-demand process error: %s", proc_err)

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
    
    try:
        with transaction.atomic():
            giveaway = Giveaway.objects.select_for_update().get(id=giveaway.id)
            if giveaway.status != 'ACTIVE':
                messages.error(request, "This giveaway is no longer active.")
                return redirect('giveaway:mine')

            wallet = Wallet.objects.select_for_update().get(user=request.user)
            balance_before = wallet.balance
            
            # Calculate refund for remaining unclaimed slots
            unclaimed_slots = max(0, giveaway.total_slots - giveaway.claimed_slots)
            refund_amount = unclaimed_slots * giveaway.amount_per_slot
            
            if refund_amount > 0:
                wallet.balance += refund_amount
                wallet.save(update_fields=['balance'])
                
                # Transaction log
                WalletTransaction.objects.create(
                    wallet=wallet,
                    txn_type=WalletTransaction.TxnType.REFUND,
                    amount=refund_amount,
                    balance_before=balance_before,
                    balance_after=wallet.balance,
                    status=WalletTransaction.Status.SUCCESS,
                    reference=f"GWY_REFUND_{giveaway.id}",
                    description=f"Refund for {unclaimed_slots} unclaimed slot(s) from giveaway: {giveaway.title}"
                )
            
            giveaway.status = 'CANCELLED'
            giveaway.save(update_fields=['status'])
            
        if refund_amount > 0:
            messages.success(request, f"Giveaway cancelled! ₦{refund_amount:,.2f} for {unclaimed_slots} unclaimed slot(s) has been refunded to your wallet.")
        else:
            messages.success(request, "Giveaway has been closed.")
    except Exception as e:
        logger.exception("Error cancelling giveaway: %s", e)
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
    GREEN = (0, 176, 88)         # #00B058 brand green
    LABEL_GREEN = (5, 150, 105)   # #059669
    GRAY = (100, 116, 139)       # #64748B
    LIGHT_GRAY = (226, 232, 240) # #E2E8F0

    def get_font(size, bold=False):
        if bold:
            font_paths = [
                "C:\\Windows\\Fonts\\segoeuib.ttf",
                "C:\\Windows\\Fonts\\arialbd.ttf",
                os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Inter.ttf'),
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
        else:
            font_paths = [
                "C:\\Windows\\Fonts\\segoeui.ttf",
                "C:\\Windows\\Fonts\\arial.ttf",
                "C:\\Windows\\Fonts\\calibri.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Inter.ttf'),
            ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    font_hero = get_font(64, bold=True)
    font_sub = get_font(32, bold=False)
    font_date = get_font(24, bold=False)
    font_label = get_font(28, bold=False)
    font_val = get_font(28, bold=False)
    font_footer = get_font(22, bold=False)

    top_y = 70
    qr_size = 145

    # 1. Top Left Branded Logo (far left, aligned with QR code)
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'sh-logo.png')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'favicon.png')

    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            target_w = 210
            w_percent = (target_w / float(logo.width))
            h_size = int((float(logo.height) * float(w_percent)))
            logo = logo.resize((target_w, h_size), Image.LANCZOS)
            logo_y = top_y + (qr_size - h_size) // 2
            img.paste(logo, (80, logo_y), mask=logo)
        except Exception:
            pass

    # 2. Top Right Branded QRCode Monkey QR (leading to homepage, aligned at top_y)
    try:
        site_url = f"{request.scheme}://{request.get_host()}"
        qr_b64 = generate_qr_code_base64(site_url) or giveaway.qr_code_base64
        if qr_b64 and "," in qr_b64:
            b64_data = qr_b64.split(",")[1]
            qr_bytes = base64.b64decode(b64_data)
            qr_img = Image.open(BytesIO(qr_bytes)).convert("RGBA")
            qr_img = qr_img.resize((qr_size, qr_size), Image.LANCZOS)
            img.paste(qr_img, (width - 80 - qr_size, top_y), mask=qr_img)
    except Exception as err:
        logger.error(f"Failed to generate receipt QR code: {err}")

    # 3. Hero Amount
    total_val = giveaway.claimed_slots * giveaway.amount_per_slot if giveaway.claimed_slots > 0 else giveaway.total_locked
    total_val_str = f"₦ {int(total_val):,}.00"
    draw.text((width // 2, 230), total_val_str, fill=NAVY, font=font_hero, anchor="mm")

    # 4. Status Text + Drawn Checkmark Icon
    status_text = "Giveaway Successful"
    bbox = draw.textbbox((0, 0), status_text, font=font_sub)
    text_w = bbox[2] - bbox[0]

    center_x = width // 2
    status_y = 315

    text_x = center_x - 18
    draw.text((text_x, status_y), status_text, fill=NAVY, font=font_sub, anchor="mm")

    icon_x = text_x + (text_w // 2) + 20
    icon_y = status_y
    r = 16
    draw.ellipse([icon_x - r, icon_y - r, icon_x + r, icon_y + r], fill=GREEN)
    draw.line([(icon_x - 7, icon_y), (icon_x - 2, icon_y + 5)], fill=(255, 255, 255), width=3)
    draw.line([(icon_x - 2, icon_y + 5), (icon_x + 7, icon_y - 5)], fill=(255, 255, 255), width=3)

    # 5. Date
    date_str = giveaway.created_at.strftime("%B %d, %Y %I:%M:%S %p")
    draw.text((width // 2, 375), date_str, fill=LABEL_GREEN, font=font_date, anchor="mm")

    # 6. Top Dashed Line
    def draw_dashed_line(y):
        dash_len = 16
        gap_len = 10
        x = 80
        while x < width - 80:
            draw.line([(x, y), (min(x + dash_len, width - 80), y)], fill=LIGHT_GRAY, width=2)
            x += dash_len + gap_len

    draw_dashed_line(440)

    # 7. Key-Value Rows
    type_label = "Data Top up" if giveaway.giveaway_type == 'DATA' else "Airtime Top up"
    host_name = giveaway.host.full_name or giveaway.host.phone_number or "SubHero Host"

    rows = [
        ("Giveaway Type:", type_label),
        ("Network Provider:", giveaway.get_network_display()),
        ("Amount Per Slot:", f"₦{int(giveaway.amount_per_slot):,}"),
        ("Slots Claimed:", f"{giveaway.claimed_slots} / {giveaway.total_slots}"),
        ("Giveaway ID:", giveaway.slug),
        ("Host Name:", host_name),
    ]

    start_y = 510
    row_height = 90

    for i, (label, val) in enumerate(rows):
        y = start_y + (i * row_height)
        draw.text((80, y), label, fill=LABEL_GREEN, font=font_label, anchor="lm")
        draw.text((width - 80, y), val, fill=NAVY, font=font_val, anchor="rm")

    # 8. Bottom Dashed Line
    draw_dashed_line(start_y + (len(rows) * row_height) + 10)

    # 9. Footer
    footer_prefix = "Host your own giveaway at "
    footer_link = "subhero.com.ng"
    try:
        bbox_pref = draw.textbbox((0, 0), footer_prefix, font=font_footer)
        bbox_link = draw.textbbox((0, 0), footer_link, font=font_footer)
        w_pref = bbox_pref[2] - bbox_pref[0]
        w_link = bbox_link[2] - bbox_link[0]
        total_w = w_pref + w_link
        start_x = (width - total_w) // 2
        footer_y = 1310
        draw.text((start_x, footer_y), footer_prefix, fill=GRAY, font=font_footer, anchor="lm")
        draw.text((start_x + w_pref, footer_y), footer_link, fill=GREEN, font=font_footer, anchor="lm")
    except Exception:
        draw.text((width // 2, 1310), "Host your own giveaway at subhero.com.ng", fill=GREEN, font=font_footer, anchor="mm")

    response = HttpResponse(content_type="image/png")
    response['Content-Disposition'] = f'attachment; filename="giveaway_receipt_{giveaway.slug}.png"'
    img.save(response, "PNG")
    return response
