import random
import string
import qrcode
import base64
from io import BytesIO

import os
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

def generate_giveaway_slug():
    """Generates a random 8-character uppercase alphanumeric slug."""
    chars = string.ascii_uppercase + string.digits
    return "GWY" + "".join(random.choices(chars, k=5))

import requests

def generate_qr_code_base64(url: str) -> str:
    """
    Generates a branded QRCode Monkey QR code for the given URL
    with mosaic body, frame13/ball13 eyes, green-to-navy gradient,
    and SH SubHero logo overlay, returning a base64 encoded PNG string.
    """
    img = None

    # 1. Primary: Use QRCode Monkey API for exact mosaic/frame13 design
    qrmonkey_api = "https://api.qrcode-monkey.com/qr/custom"
    payload = {
        "data": url,
        "config": {
            "body": "mosaic",
            "eye": "frame13",
            "eyeBall": "ball13",
            "bodyColor": "#00B058",
            "bgColor": "#FFFFFF",
            "gradientColor1": "#00B058",
            "gradientColor2": "#0F172A",
            "gradientType": "linear",
            "gradientOnEyes": True,
            "logoMode": "default"
        },
        "size": 600,
        "download": False,
        "file": "png"
    }

    try:
        response = requests.post(qrmonkey_api, json=payload, timeout=5)
        if response.status_code == 200 and response.content:
            img = Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception:
        img = None

    # 2. Fallback: Local Pillow QR Generator if API is offline
    if img is None:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=24,
            border=3,
        )
        qr.add_data(url)
        qr.make(fit=True)

        matrix = qr.get_matrix()
        num_modules = len(matrix)
        box_size = 24
        img_size = num_modules * box_size

        img = Image.new("RGBA", (img_size, img_size), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)

        top_color = (0, 176, 88)
        bottom_color = (15, 23, 42)

        def get_gradient_color(y_ratio):
            r = int(top_color[0] + (bottom_color[0] - top_color[0]) * y_ratio)
            g = int(top_color[1] + (bottom_color[1] - top_color[1]) * y_ratio)
            b = int(top_color[2] + (bottom_color[2] - top_color[2]) * y_ratio)
            return (r, g, b, 255)

        for r in range(num_modules):
            col = get_gradient_color(r / float(num_modules - 1))
            for c in range(num_modules):
                if matrix[r][c]:
                    x = c * box_size
                    y = r * box_size
                    draw.rounded_rectangle(
                        [x + 2, y + 2, x + box_size - 2, y + box_size - 2],
                        radius=8,
                        fill=col
                    )

    # 3. Overlay SH SubHero Logo in Center
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'sh-logo.png')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'favicon.png')

    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            target_logo_size = int(img.width * 0.22)
            logo.thumbnail((target_logo_size, target_logo_size), Image.LANCZOS)

            bg_size = target_logo_size + 24
            bg_x = (img.width - bg_size) // 2
            bg_y = (img.height - bg_size) // 2

            logo_bg = Image.new("RGBA", (bg_size, bg_size), (0, 0, 0, 0))
            bg_draw = ImageDraw.Draw(logo_bg)
            bg_draw.rounded_rectangle([0, 0, bg_size, bg_size], radius=24, fill=(255, 255, 255, 255))
            img.paste(logo_bg, (bg_x, bg_y), mask=logo_bg)

            logo_x = (img.width - logo.width) // 2
            logo_y = (img.height - logo.height) // 2
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception:
            pass

    # Save to BytesIO buffer
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    
    # Encode as Base64
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"
