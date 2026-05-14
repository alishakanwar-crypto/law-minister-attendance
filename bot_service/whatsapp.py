"""WhatsApp Cloud API client for the standalone Law Minister Bot."""

import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from bot_service.config import WHATSAPP_CLOUD_TOKEN, LAW_MINISTER_PHONE_ID, WABA_ID

logger = logging.getLogger("lm_bot.whatsapp")

GRAPH_API = "https://graph.facebook.com/v21.0"


def _get_token() -> str:
    return os.getenv("WHATSAPP_CLOUD_TOKEN", WHATSAPP_CLOUD_TOKEN)


async def send_text(to: str, body: str) -> bool:
    """Send a text message from the Law Minister phone number."""
    token = _get_token()
    if not token:
        logger.error("WHATSAPP_CLOUD_TOKEN not set")
        return False

    recipient = to.split("@")[0] if "@" in to else to
    if len(recipient) == 10:
        recipient = "91" + recipient

    url = f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": body},
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                logger.info(f"Sent to {recipient}: {body[:50]}...")
                return True
            logger.error(f"Send error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Send failed: {e}")
        return False


async def send_document(to: str, filepath: str, caption: str,
                        filename: str = "report.xlsx") -> bool:
    """Upload and send a document (e.g. Excel) via WhatsApp."""
    token = _get_token()
    if not token:
        return False

    recipient = to.split("@")[0] if "@" in to else to
    if len(recipient) == 10:
        recipient = "91" + recipient

    headers = {"Authorization": f"Bearer {token}"}
    upload_url = f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/media"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Upload file
            with open(filepath, "rb") as f:
                resp = await client.post(
                    upload_url,
                    headers=headers,
                    data={"messaging_product": "whatsapp",
                          "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                    files={"file": (filename, f,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                )
            if resp.status_code != 200:
                logger.error(f"Media upload failed: {resp.status_code} {resp.text}")
                return False
            media_id = resp.json().get("id")

            # Send document message
            msg_url = f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "document",
                "document": {
                    "id": media_id,
                    "caption": caption,
                    "filename": filename,
                },
            }
            resp = await client.post(
                msg_url,
                json=payload,
                headers={**headers, "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                logger.info(f"Document sent to {recipient}: {filename}")
                return True
            logger.error(f"Document send failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Send document error: {e}")
        return False


async def send_image(to: str, image_path: str, caption: str = "") -> bool:
    """Upload and send an image via WhatsApp."""
    token = _get_token()
    if not token:
        return False

    recipient = to.split("@")[0] if "@" in to else to
    if len(recipient) == 10:
        recipient = "91" + recipient

    headers = {"Authorization": f"Bearer {token}"}
    upload_url = f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/media"

    try:
        path = Path(image_path)
        if not path.exists():
            logger.error(f"Image not found: {image_path}")
            return False

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(path, "rb") as f:
                resp = await client.post(
                    upload_url,
                    headers=headers,
                    data={"messaging_product": "whatsapp", "type": "image/jpeg"},
                    files={"file": (path.name, f, "image/jpeg")},
                )
            if resp.status_code != 200:
                logger.error(f"Image upload failed: {resp.status_code} {resp.text}")
                return False
            media_id = resp.json().get("id")

            msg_url = f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "image",
                "image": {"id": media_id, "caption": caption},
            }
            resp = await client.post(
                msg_url,
                json=payload,
                headers={**headers, "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                logger.info(f"Image sent to {recipient}")
                return True
            logger.error(f"Image send failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Send image error: {e}")
        return False


async def send_template(to: str, template_name: str, parameters: list[str],
                        header_media_id: str | None = None,
                        language: str = "en") -> bool:
    """Send a template message via WhatsApp Cloud API."""
    token = _get_token()
    if not token:
        return False

    recipient = to.split("@")[0] if "@" in to else to
    if len(recipient) == 10:
        recipient = "91" + recipient

    url = f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    components = []
    if header_media_id:
        components.append({
            "type": "header",
            "parameters": [{"type": "image", "image": {"id": header_media_id}}],
        })
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters],
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": components,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                logger.info(f"Template '{template_name}' sent to {recipient}")
                return True
            logger.error(f"Template send error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Template send failed: {e}")
        return False


async def ensure_webhook_registration() -> dict:
    """Register the Law Minister phone number and subscribe WABA."""
    token = _get_token()
    if not token:
        logger.error("WHATSAPP_CLOUD_TOKEN not set — skipping registration")
        return {"error": "no_token"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    results = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{GRAPH_API}/{LAW_MINISTER_PHONE_ID}/register",
                json={"messaging_product": "whatsapp", "pin": "123456"},
                headers=headers,
            )
            results["register"] = resp.json()
            logger.info(f"Registration: {resp.status_code}: {resp.text}")
        except Exception as e:
            results["register"] = {"error": str(e)}

        try:
            resp = await client.post(
                f"{GRAPH_API}/{WABA_ID}/subscribed_apps",
                headers=headers,
            )
            results["subscribe"] = resp.json()
            logger.info(f"WABA subscribe: {resp.status_code}: {resp.text}")
        except Exception as e:
            results["subscribe"] = {"error": str(e)}

    return results
