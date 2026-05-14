"""
WhatsApp Cloud API integration for attendance notifications.

Uses Meta Cloud API exclusively (no Green API per org policy).
Bot for the Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister.
Sends check-in alerts when staff are recognized by the face recognition engine.
Handles incoming webhook messages and auto-responds based on bot rules.
"""

import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import httpx

from backend import bot_messages as msgs

logger = logging.getLogger("attendance.whatsapp")

WEBHOOK_VERIFY_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "law_minister_attendance_bot")

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


def upload_media(cfg: dict, image_path: str) -> str | None:
    """Upload an image to Meta Cloud API and return the media ID.

    The media ID can then be used in send_image_message().
    """
    token = _get_token()
    phone_id = _get_phone_id(cfg)

    if not token or not phone_id:
        logger.warning("WhatsApp not configured (missing token or phone_id)")
        return None

    path = Path(image_path)
    if not path.exists():
        logger.error(f"Snapshot file not found: {image_path}")
        return None

    url = f"{GRAPH_API}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with open(path, "rb") as f:
            files = {
                "file": (path.name, f, "image/jpeg"),
            }
            data = {
                "messaging_product": "whatsapp",
                "type": "image/jpeg",
            }
            resp = httpx.post(url, headers=headers, files=files, data=data, timeout=30)

        if resp.status_code == 200:
            media_id = resp.json().get("id")
            logger.info(f"Media uploaded: {path.name} → media_id={media_id}")
            return media_id
        else:
            logger.error(f"Media upload error {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Media upload failed: {e}")
        return None


def send_image_message(cfg: dict, to: str, media_id: str,
                       caption: str = "") -> bool:
    """Send an image message via Meta Cloud API using a previously uploaded media ID."""
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
    image_obj: dict = {"id": media_id}
    if caption:
        image_obj["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image_obj,
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            logger.info(f"WhatsApp image sent to {to}")
            return True
        else:
            logger.error(f"WhatsApp image send error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp image send failed: {e}")
        return False


def send_template_message(cfg: dict, to: str, template_name: str,
                          parameters: list[str] | None = None,
                          language: str = "en",
                          header_media_id: str | None = None) -> bool:
    """Send a pre-approved template message via Meta Cloud API.

    Template messages bypass the 24-hour opt-in window.
    If header_media_id is provided, the template header is set to that image.
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

    components = []
    if header_media_id:
        components.append({
            "type": "header",
            "parameters": [{
                "type": "image",
                "image": {"id": header_media_id},
            }],
        })
    if parameters:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": p} for p in parameters
            ],
        })
    if components:
        template_obj["components"] = components

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


ATTENDANCE_TEMPLATE = "office_attendance"


def _send_checkin_with_snapshot(cfg: dict, recipient: str,
                                staff_name: str, date_str: str,
                                time_str: str,
                                snapshot_path: str | None):
    """Send attendance notification using the Meta-approved template.

    Priority chain:
    1. Template message with image header (works outside 24h window)
    2. Image message with caption (fallback if template fails)
    3. Text-only message (final fallback)
    """
    media_id = None
    if snapshot_path:
        media_id = upload_media(cfg, snapshot_path)

    # Try template message first (bypasses 24h opt-in window)
    sent = send_template_message(
        cfg, recipient, ATTENDANCE_TEMPLATE,
        parameters=[staff_name, date_str, time_str],
        header_media_id=media_id,
    )
    if sent:
        return

    logger.warning("Template send failed, falling back to image+caption")

    # Fallback: image with caption
    body = msgs.attendance_notification(
        name=staff_name, date_str=date_str, time_str=time_str, status="Present",
    )
    if media_id:
        sent = send_image_message(cfg, recipient, media_id, caption=body)
        if sent:
            return
        logger.warning("Image send failed, falling back to text-only")

    # Final fallback: text-only
    send_text_message(cfg, recipient, body)


def notify_checkin(cfg: dict, staff_name: str, staff_id: str,
                   confidence: float, camera: str,
                   snapshot_path: str | None = None):
    """Send attendance notification with snapshot via Meta template.

    Uses the approved 'office_attendance' template with:
      Header: Face snapshot image
      Body: employee_name, date, time

    Falls back to image+caption, then text-only if template fails.
    """
    if not is_configured(cfg):
        return

    recipient = cfg.get("whatsapp_recipient", "")
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%d/%m/%Y")

    threading.Thread(
        target=_send_checkin_with_snapshot,
        args=(cfg, recipient, staff_name, date_str, time_str, snapshot_path),
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


# ---------- Webhook Handling ----------

def verify_webhook(mode: str, token: str, challenge: str) -> str | None:
    """Verify Meta webhook subscription request.

    Returns the challenge string if valid, None otherwise.
    """
    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge
    logger.warning(f"Webhook verification failed: mode={mode}")
    return None


def _extract_text_messages(payload: dict) -> list[dict]:
    """Extract text messages from a Meta webhook payload.

    Returns a list of dicts with keys: from_number, text, message_id, timestamp.
    """
    results = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") == "text":
                    results.append({
                        "from_number": message.get("from", ""),
                        "text": message.get("text", {}).get("body", ""),
                        "message_id": message.get("id", ""),
                        "timestamp": message.get("timestamp", ""),
                    })
    return results


def handle_incoming_webhook(cfg: dict, payload: dict) -> list[dict]:
    """Process an incoming webhook payload and send auto-responses.

    Returns a list of actions taken (for logging/API response).
    """
    messages = _extract_text_messages(payload)
    actions = []

    for msg in messages:
        text = msg["text"]
        from_number = msg["from_number"]
        auto_reply = msgs.get_auto_response(text)

        if auto_reply:
            sent = send_text_message(cfg, from_number, auto_reply)
            category = msgs.classify_message(text)
            lang = msgs.detect_language(text)
            actions.append({
                "from": from_number,
                "text": text,
                "category": category,
                "language": lang,
                "response_sent": sent,
            })
            logger.info(
                f"Auto-replied to {from_number} "
                f"({category}/{lang}): {text[:40]}"
            )
        else:
            actions.append({
                "from": from_number,
                "text": text,
                "category": "allowed",
                "language": msgs.detect_language(text),
                "response_sent": False,
                "note": "Office topic — requires further processing",
            })
            logger.info(
                f"Allowed topic from {from_number}: {text[:40]}"
            )

    return actions
