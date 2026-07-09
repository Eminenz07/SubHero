import random
import string
import qrcode
import base64
from io import BytesIO

import os
from django.conf import settings
from PIL import Image

def generate_giveaway_slug():
    """Generates a random 8-character uppercase alphanumeric slug."""
    chars = string.ascii_uppercase + string.digits
    return "GWY" + "".join(random.choices(chars, k=5))

def generate_qr_code_base64(url: str) -> str:
    """
    Generates a branded green QR code for the given URL with favicon overlay,
    returning it as a base64 encoded PNG string.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Generate brand green QR code
    img = qr.make_image(fill_color="#006B3E", back_color="white").convert("RGB")
    
    # Overlay logo
    try:
        # favicon.png is in static directory
        favicon_path = os.path.join(settings.BASE_DIR, 'static', 'favicon.png')
        if os.path.exists(favicon_path):
            logo = Image.open(favicon_path).convert("RGBA")
            img_w, img_h = img.size
            logo_size = int(img_w * 0.15)
            logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
            
            # Put logo on a white container background to make it stand out
            logo_bg = Image.new("RGBA", (logo_size + 8, logo_size + 8), "white")
            logo_bg.paste(logo, (4, 4), mask=logo)
            
            pos = ((img_w - logo_bg.size[0]) // 2, (img_h - logo_bg.size[1]) // 2)
            img.paste(logo_bg, pos, mask=logo_bg)
    except Exception:
        pass
    
    # Save to BytesIO buffer
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    
    # Encode as Base64
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"
