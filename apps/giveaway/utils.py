import random
import string
import qrcode
import base64
from io import BytesIO

def generate_giveaway_slug():
    """Generates a random 8-character uppercase alphanumeric slug."""
    chars = string.ascii_uppercase + string.digits
    return "GWY" + "".join(random.choices(chars, k=5))

def generate_qr_code_base64(url: str) -> str:
    """
    Generates a QR code for the given URL and returns it as a base64 encoded PNG string.
    This avoids writing to Render's ephemeral filesystem.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Generate Image
    img = qr.make_image(fill_color="#0F172A", back_color="white").convert("RGB")
    
    # Save to BytesIO buffer
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    
    # Encode as Base64
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"
