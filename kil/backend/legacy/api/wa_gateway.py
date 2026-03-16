"""
WhatsApp Gateway Client
========================
Shared WA messaging client used by MOM and Attendance modules.
Supports multiple gateway providers: Fonnte, Wablas, or Meta official.

Config via env vars:
    WA_GATEWAY_TYPE  = fonnte | wablas | meta  (default: fonnte)
    WA_GATEWAY_URL   = gateway endpoint
    WA_API_KEY       = API key/token
"""

import os
import logging

import httpx

log = logging.getLogger(__name__)

WA_GATEWAY_TYPE = os.environ.get("WA_GATEWAY_TYPE", "fonnte")
WA_GATEWAY_URL = os.environ.get("WA_GATEWAY_URL", "https://api.fonnte.com/send")
WA_API_KEY = os.environ.get("WA_API_KEY", "")


def send_whatsapp(phone: str, message: str) -> dict:
    """
    Send a WhatsApp message via configured gateway.

    Args:
        phone: Recipient phone number (with country code, e.g. 6281234567890)
        message: Message text (supports WhatsApp formatting: *bold*, _italic_)

    Returns:
        dict with keys: success (bool), detail (str), raw_response (dict)
    """
    if not WA_API_KEY:
        log.warning("WA_API_KEY not configured, skipping send")
        return {"success": False, "detail": "WA_API_KEY not configured", "raw_response": {}}

    # Normalize phone
    phone = phone.strip().replace("+", "").replace("-", "").replace(" ", "")
    if phone.startswith("08"):
        phone = "62" + phone[1:]

    try:
        if WA_GATEWAY_TYPE == "fonnte":
            return _send_fonnte(phone, message)
        elif WA_GATEWAY_TYPE == "wablas":
            return _send_wablas(phone, message)
        elif WA_GATEWAY_TYPE == "meta":
            return _send_meta(phone, message)
        else:
            return {"success": False, "detail": f"Unknown gateway type: {WA_GATEWAY_TYPE}", "raw_response": {}}
    except Exception as e:
        log.error(f"WA send error: {e}")
        return {"success": False, "detail": str(e), "raw_response": {}}


def _send_fonnte(phone: str, message: str) -> dict:
    """Send via Fonnte.com API."""
    resp = httpx.post(
        WA_GATEWAY_URL,
        headers={"Authorization": WA_API_KEY},
        data={"target": phone, "message": message},
        timeout=30,
    )
    data = resp.json() if resp.status_code == 200 else {}
    ok = resp.status_code == 200 and data.get("status", False)
    return {"success": ok, "detail": data.get("reason", resp.text[:200]), "raw_response": data}


def _send_wablas(phone: str, message: str) -> dict:
    """Send via Wablas API."""
    resp = httpx.post(
        WA_GATEWAY_URL,
        headers={"Authorization": WA_API_KEY, "Content-Type": "application/json"},
        json={"phone": phone, "message": message},
        timeout=30,
    )
    data = resp.json() if resp.status_code == 200 else {}
    ok = resp.status_code == 200
    return {"success": ok, "detail": data.get("message", resp.text[:200]), "raw_response": data}


def _send_meta(phone: str, message: str) -> dict:
    """Send via official Meta WhatsApp Business API."""
    resp = httpx.post(
        WA_GATEWAY_URL,
        headers={"Authorization": f"Bearer {WA_API_KEY}", "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": message},
        },
        timeout=30,
    )
    data = resp.json() if resp.status_code in (200, 201) else {}
    ok = resp.status_code in (200, 201)
    return {"success": ok, "detail": data.get("messages", [{}])[0].get("id", resp.text[:200]) if ok else resp.text[:200], "raw_response": data}
