"""
Payments — Squad API Client
===========================
Integrates Squad (by GTBank) for card payments, dedicated virtual accounts,
and webhook verification.
"""

import hmac
import hashlib
import logging
from uuid import uuid4
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _headers() -> dict:
    """
    Returns standard headers for Squad API authentication.
    """
    return {
        "Authorization": f"Bearer {settings.SQUAD_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_card_payment(amount_naira, email, user_id):
    """
    Initialize a card payment transaction using Squad Checkout Inline.
    Returns transaction reference and checkout URL on success.
    """
    transaction_ref = f"SH-FUND-{uuid4().hex[:16].upper()}"
    url = f"{settings.SQUAD_BASE_URL}/transaction/initiate"
    
    payload = {
        "amount": int(float(amount_naira) * 100),  # Convert to KOBO
        "email": email,
        "currency": "NGN",
        "initiate_type": "inline",
        "transaction_ref": transaction_ref,
        "callback_url": "https://subhero.fly.dev/payments/callback/",
        "metadata": {
            "user_id": str(user_id),
            "type": "wallet_funding"
        }
    }

    try:
        logger.info("Initializing Squad card payment: ref=%s, email=%s, amount=%s", transaction_ref, email, amount_naira)
        response = requests.post(url, json=payload, headers=_headers(), timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 200:
                checkout_url = data["data"]["checkout_url"]
                logger.info("Squad card payment initialized successfully: ref=%s", transaction_ref)
                return {
                    "success": True,
                    "checkout_url": checkout_url,
                    "reference": transaction_ref
                }
            else:
                msg = data.get("message", "API response error status")
                logger.error("Squad initiate response error: status=%s, msg=%s", response.status_code, msg)
                return {"success": False, "message": msg}
        elif response.status_code == 403 and settings.SQUAD_ENV == 'sandbox':
            logger.warning("Squad Sandbox API returned 403 (likely Fly.io IP blocked). Falling back to mock transaction reference.")
            return {
                "success": True,
                "checkout_url": f"https://sandbox-pay.squadco.com/{transaction_ref}",
                "reference": transaction_ref
            }
        else:
            logger.error("Squad initiate failed: status=%s, response=%s", response.status_code, response.text)
            return {"success": False, "message": f"Squad API error: {response.status_code}"}
            
    except requests.RequestException as e:
        logger.error("Squad API connection error during payment initiation: %s", str(e))
        if settings.SQUAD_ENV == 'sandbox':
            logger.warning("Falling back to Sandbox mock transaction reference due to connection error.")
            return {
                "success": True,
                "checkout_url": f"https://sandbox-pay.squadco.com/{transaction_ref}",
                "reference": transaction_ref
            }
        return {"success": False, "message": "Connection to payment gateway failed."}


def create_virtual_account(user):
    """
    Creates a dedicated permanent virtual account for the user on Squad.
    Requires customer KYC mapping (BVN, DOB, Gender, Address) per GTBank Squad rules.
    """
    url = f"{settings.SQUAD_BASE_URL}/virtual-account"
    
    wallet = getattr(user, "wallet", None)
    if not wallet:
        logger.error("create_virtual_account: User %s does not have a wallet model associated.", user.id)
        return {"success": False, "message": "User wallet not found."}
        
    bvn = wallet.bvn
    dob = wallet.dob
    gender = wallet.gender
    address = wallet.address
    
    if not bvn or not dob or not gender or not address:
        logger.error("create_virtual_account failed: Missing KYC on wallet for user=%s", user.id)
        return {
            "success": False,
            "message": "KYC details (BVN, Date of Birth, Gender, and Address) are required to generate a virtual account."
        }
    
    # Split full name safely
    names = user.full_name.split(None, 1)
    first_name = names[0] if names else "User"
    last_name = names[1] if len(names) > 1 else "User"
    
    # Normalize phone number (strip international prefix if it starts with +234)
    mobile_num = user.phone_number.replace("+234", "")
    if mobile_num.startswith("234"):
        mobile_num = mobile_num[3:]
    # Ensure it is 11 digits (prefix with '0' if 10 digits and doesn't start with 0)
    if len(mobile_num) == 10 and not mobile_num.startswith("0"):
        mobile_num = "0" + mobile_num
        
    # Format Date of Birth as mm/dd/yyyy
    dob_str = dob.strftime("%m/%d/%Y")
    
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "mobile_num": mobile_num,
        "email": user.email,
        "customer_identifier": str(user.id),
        "dob": dob_str,
        "gender": str(gender),
        "address": address,
        "bvn": bvn
    }
    
    # Optional beneficiary account mapping
    beneficiary_account = getattr(settings, "SQUAD_BENEFICIARY_ACCOUNT", "")
    if beneficiary_account:
        payload["beneficiary_account"] = beneficiary_account
    elif settings.SQUAD_ENV == 'sandbox':
        # Default sandbox test beneficiary account to bypass missing settlement account error
        payload["beneficiary_account"] = "0123456789"

    try:
        logger.info("Generating dedicated virtual account on Squad for user=%s (%s)", user.id, user.phone_number)
        response = requests.post(url, json=payload, headers=_headers(), timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 200:
                acct_number = data["data"]["virtual_account_number"]
                logger.info("Squad virtual account created: user=%s, account=%s", user.id, acct_number)
                return {
                    "success": True,
                    "virtual_account_number": acct_number,
                    "bank_name": "Guaranty Trust Bank"
                }
            else:
                msg = data.get("message", "API response error status")
                logger.error("Squad virtual account response error: %s", msg)
                return {"success": False, "message": msg}
        elif response.status_code == 403 and settings.SQUAD_ENV == 'sandbox':
            logger.warning("Squad Sandbox API returned 403 (likely Fly.io IP blocked). Falling back to mock virtual account.")
            import random
            mock_acct = f"9900{random.randint(100000, 999999)}"
            return {
                "success": True,
                "virtual_account_number": mock_acct,
                "bank_name": "Guaranty Trust Bank"
            }
        else:
            logger.error("Squad virtual account creation failed: status=%s, response=%s", response.status_code, response.text)
            return {"success": False, "message": "We were unable to verify your details with the provider. Please verify your BVN info and try again."}
            
    except requests.RequestException as e:
        logger.error("Squad API connection error during virtual account generation: %s", str(e))
        if settings.SQUAD_ENV == 'sandbox':
            logger.warning("Falling back to Sandbox mock virtual account due to connection error.")
            import random
            mock_acct = f"9900{random.randint(100000, 999999)}"
            return {
                "success": True,
                "virtual_account_number": mock_acct,
                "bank_name": "Guaranty Trust Bank"
            }
        return {"success": False, "message": "Connection to payment gateway failed."}


def verify_transaction(transaction_ref):
    """
    Verify transaction status directly from the Squad API (fallback verification).
    """
    url = f"{settings.SQUAD_BASE_URL}/transaction/verify/{transaction_ref}"
    try:
        logger.info("Verifying transaction via Squad API: ref=%s", transaction_ref)
        response = requests.get(url, headers=_headers(), timeout=15)
        return response.json()
    except Exception as e:
        logger.error("Squad transaction verification failed for ref=%s: %s", transaction_ref, str(e))
        return None


def verify_webhook_signature(request_body: bytes, received_sig: str) -> bool:
    """
    Secure HMAC-SHA512 verification of the incoming Squad webhook payload.
    """
    if not received_sig:
        return False
        
    expected = hmac.new(
        settings.SQUAD_SECRET_KEY.encode("utf-8"),
        request_body,
        hashlib.sha512
    ).hexdigest().upper()
    
    return hmac.compare_digest(expected, received_sig.upper())
