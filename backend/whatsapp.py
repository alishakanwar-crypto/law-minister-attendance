"""
WhatsApp Cloud API integration for attendance notifications.

Uses Meta Cloud API exclusively (no Green API per org policy).
Bot for the Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister.
Sends check-in alerts when staff are recognized by the face recognition engine.
"""

import logging
import os
import threading
from datetime import datetime

import httpx

from backend import bot_messages as msgs

logger = logging.getLogger("attendance.whatsapp")

GRAPH_API = "https://graph.facebook.com/v21.0"


def _get_token() -> str | None:
    return os.environ.get("WHATSAPP_CLOUD_TOKEN")


def _get_phone_id(cfg: dict) -> str:
    return cfg.get("whatsapp_phone_id", "")


def _format_phone(number: str) -> str:
    """Normalise a phone number to international format."""
    number = number.strip().replace(" ", "")
    if not number.startswith("+"):
        if number.startswith("91"):
            number = "+" + number
        else:
            number = "+91" + number
    return number


def is_configured(cfg: dict) -> bool:
    """Check if WhatsApp notifications are properly configured."""
    token = _get_token()
    phone_id = _get_phone_id(cfg)
    recipient = cfg.get("whatsapp_recipient", "")
    enabled = cfg.get("whatsapp_enabled", False)
    return bool(token and phone_id and recipient and enabled)


def send_text_message(cfg: dict, to: str, body: str) -> bool:
    """Send a plain text WhatsApp message via Meta Cloud API."""
    token = _get_token()
    phone_id = _get_phone_id(cfg)

    if not token or not phone_id:
        logger.warning("WhatsApp not configured (missing token or phone_id)")
        return False

    to = _format_phone(to)

    url = f"{GRAPH_API}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            logger.info(f"WhatsApp sent to {to}: {body[:50]}...")
            return True
        else:
            logger.error(f"WhatsApp API error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")
        return False


def send_template_message(cfg: dict, to: str, template_name: str,
                          parameters: list[str] | None = None,
                          language: str = "en") -> bool:
    """Send a pre-approved template message via Meta Cloud API.

    Template messages bypass the 24-hour opt-in window.
    """
    token = _get_token()
    phone_id = _get_phone_id(cfg)

    if not token or not phone_id:
        logger.warning("WhatsApp not configured (missing token or phone_id)")
        return False

    to = _format_phone(to)

    url = f"{GRAPH_API}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    template_obj: dict = {
        "name": template_name,
        "language": {"code": language},
    }
    if parameters:
        template_obj["components"] = [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": p} for p in parameters
            ],
        }]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template_obj,
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            logger.info(
                f"WhatsApp template '{template_name}' sent to {to}")
            return True
        else:
            logger.error(f"WhatsApp template error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp template send failed: {e}")
        return False


# ---------- High-level notification helpers ----------

def send_welcome_message(cfg: dict, to: str) -> bool:
    """Send the first automated message requesting face registration photos."""
    return send_text_message(cfg, to, msgs.WELCOME_MESSAGE)


def send_registration_success(cfg: dict, to: str, name: str) -> bool:
    """Confirm successful face registration."""
    return send_text_message(cfg, to, msgs.registration_success(name))


def send_registration_rejected(cfg: dict, to: str, reason: str) -> bool:
    """Notify that a submitted photo was rejected."""
    return send_text_message(cfg, to, msgs.registration_rejected(reason))


def notify_checkin(cfg: dict, staff_name: str, staff_id: str,
                   confidence: float, camera: str):
    """Send attendance notification matching the official format.

    Uses the government-office spec:
      Attendance Marked Successfully
      Name / Date / Time / Status: Present
    """
    if not is_configured(cfg):
        return

    recipient = cfg.get("whatsapp_recipient", "")
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%d/%m/%Y")

    body = msgs.attendance_notification(
        name=staff_name,
        date_str=date_str,
        time_str=time_str,
        status="Present",
    )

    threading.Thread(
        target=send_text_message,
        args=(cfg, recipient, body),
        daemon=True,
    ).start()


def send_daily_summary(cfg: dict, summary: dict):
    """Send end-of-day attendance summary via WhatsApp."""
    if not is_configured(cfg):
        return

    recipient = cfg.get("whatsapp_recipient", "")
    today = datetime.now().strftime("%d/%m/%Y")

    body = msgs.daily_summary(
        date_str=today,
        total=summary.get("total", 0),
        present_count=summary.get("present_count", 0),
        absent_count=summary.get("absent_count", 0),
        pct=summary.get("pct", 0),
        present_list=summary.get("present", []),
        absent_names=summary.get("absent", []),
    )

    threading.Thread(
        target=send_text_message,
        args=(cfg, recipient, body),
        daemon=True,
    ).start()
