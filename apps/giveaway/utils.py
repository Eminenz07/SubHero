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
    Generates a branded green-to-navy gradient QR code for the given URL
    with rounded finder patterns and SH SubHero logo overlay,
    returning it as a base64 encoded PNG string.
    """
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

    # Create canvas
    img = Image.new("RGBA", (img_size, img_size), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Color palette gradient: Top Bright Green -> Bottom Dark Navy
    top_color = (0, 176, 88)      # Brand Green
    bottom_color = (15, 23, 42)    # Brand Navy

    def get_gradient_color(y_ratio):
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * y_ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * y_ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * y_ratio)
        return (r, g, b, 255)

    def is_finder_pattern(r, c):
        if r < 7 and c < 7:
            return "tl"
        if r < 7 and c >= num_modules - 7:
            return "tr"
        if r >= num_modules - 7 and c < 7:
            return "bl"
        return None

    # Track drawn finder patterns
    finders = set()

    for r in range(num_modules):
        y_ratio = r / float(num_modules - 1)
        col = get_gradient_color(y_ratio)
        for c in range(num_modules):
            finder_type = is_finder_pattern(r, c)
            if finder_type:
                finders.add(finder_type)
                continue

            if matrix[r][c]:
                x = c * box_size
                y = r * box_size
                pad = 2
                radius = 8
                draw.rounded_rectangle(
                    [x + pad, y + pad, x + box_size - pad, y + box_size - pad],
                    radius=radius,
                    fill=col
                )

    # Custom smooth Finder Eyes
    finder_coords = {
        "tl": (0, 0),
        "tr": (0, num_modules - 7),
        "bl": (num_modules - 7, 0)
    }

    for ftype, (fr, fc) in finder_coords.items():
        y_ratio = fr / float(num_modules - 1)
        col = get_gradient_color(y_ratio)
        x = fc * box_size
        y = fr * box_size
        size = 7 * box_size

        # Outer rounded box
        draw.rounded_rectangle([x, y, x + size, y + size], radius=32, fill=col)
        # Inner white cutout
        cutout_pad = box_size
        draw.rounded_rectangle(
            [x + cutout_pad, y + cutout_pad, x + size - cutout_pad, y + size - cutout_pad],
            radius=20,
            fill=(255, 255, 255, 255)
        )
        # Center dot
        dot_pad = box_size * 2
        draw.rounded_rectangle(
            [x + dot_pad, y + dot_pad, x + size - dot_pad, y + size - dot_pad],
            radius=12,
            fill=col
        )

    # Logo Overlay in Center
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'sh-logo.png')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'favicon.png')

    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            target_logo_size = int(img_size * 0.22)
            logo.thumbnail((target_logo_size, target_logo_size), Image.LANCZOS)

            # White backdrop
            bg_size = target_logo_size + 24
            bg_x = (img_size - bg_size) // 2
            bg_y = (img_size - bg_size) // 2

            # Rounded white background for logo
            logo_bg = Image.new("RGBA", (bg_size, bg_size), (0, 0, 0, 0))
            bg_draw = ImageDraw.Draw(logo_bg)
            bg_draw.rounded_rectangle([0, 0, bg_size, bg_size], radius=24, fill=(255, 255, 255, 255))
            img.paste(logo_bg, (bg_x, bg_y), mask=logo_bg)

            # Paste Logo
            logo_x = (img_size - logo.width) // 2
            logo_y = (img_size - logo.height) // 2
            img.paste(logo, (logo_x, logo_y), mask=logo)
        except Exception:
            pass

    # Save to BytesIO buffer
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    
    # Encode as Base64
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"
