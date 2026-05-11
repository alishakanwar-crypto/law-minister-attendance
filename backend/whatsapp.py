"""
WhatsApp Cloud API integration for attendance notifications.

Uses Meta Cloud API exclusively (no Green API per org policy).
Sends check-in alerts when staff are recognized by the face recognition engine.
"""

import logging
import os
import threading
from datetime import datetime

import httpx

logger = logging.getLogger("attendance.whatsapp")

GRAPH_API = "https://graph.facebook.com/v21.0"


def _get_token() -> str | None:
    return os.environ.get("WHATSAPP_CLOUD_TOKEN")


def _get_phone_id(cfg: dict) -> str:
    return cfg.get("whatsapp_phone_id", "")


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

    # Ensure recipient is in international format
    to = to.strip().replace(" ", "")
    if not to.startswith("+"):
        if to.startswith("91"):
            to = "+" + to
        else:
            to = "+91" + to

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


def notify_checkin(cfg: dict, staff_name: str, staff_id: str,
                   confidence: float, camera: str):
    """Send a check-in notification via WhatsApp (runs in background thread)."""
    if not is_configured(cfg):
        return

    recipient = cfg.get("whatsapp_recipient", "")
    office_name = cfg.get("office_name", "Law Minister's Office")
    now = datetime.now().strftime("%I:%M %p")
    today = datetime.now().strftime("%d %B %Y")

    body = (
        f"*{office_name} — Attendance Alert*\n\n"
        f"Staff: *{staff_name}* ({staff_id})\n"
        f"Time: {now}\n"
        f"Date: {today}\n"
        f"Camera: {camera}\n"
        f"Confidence: {confidence:.1%}\n\n"
        f"_Automated notification by LEGIT COMMUNISYS_"
    )

    # Send in background thread to avoid blocking the engine
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
    office_name = cfg.get("office_name", "Law Minister's Office")
    today = datetime.now().strftime("%d %B %Y")

    present_list = "\n".join(
        f"  - {r['name']} ({r['time']})"
        for r in summary.get("present", [])
    ) or "  (none)"

    absent_list = "\n".join(
        f"  - {name}"
        for name in summary.get("absent", [])
    ) or "  (none)"

    body = (
        f"*{office_name} — Daily Summary*\n"
        f"Date: {today}\n\n"
        f"Total Staff: {summary.get('total', 0)}\n"
        f"Present: {summary.get('present_count', 0)}\n"
        f"Absent: {summary.get('absent_count', 0)}\n"
        f"Attendance: {summary.get('pct', 0)}%\n\n"
        f"*Present:*\n{present_list}\n\n"
        f"*Absent:*\n{absent_list}\n\n"
        f"_LEGIT COMMUNISYS — Automated Report_"
    )

    threading.Thread(
        target=send_text_message,
        args=(cfg, recipient, body),
        daemon=True,
    ).start()
