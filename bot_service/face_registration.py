"""Face registration via WhatsApp — handles image receiving, validation, and storage."""

import io
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from PIL import Image

from bot_service.config import LAW_MINISTER_PHONE_ID, WHATSAPP_CLOUD_TOKEN
from bot_service import database as db
from bot_service import whatsapp as wa

logger = logging.getLogger("lm_bot.face_reg")

IST = timezone(timedelta(hours=5, minutes=30))

# Directory for storing face images
FACE_IMAGES_DIR = Path(os.getenv("FACE_IMAGES_DIR", "/data/face_images"))
FACE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Image quality thresholds
MIN_IMAGE_SIZE = 50 * 1024  # 50KB minimum
MIN_RESOLUTION = 200  # 200px minimum dimension
BLUR_THRESHOLD = 50.0  # Laplacian variance threshold


# ---------- Response Messages ----------

NO_CAPTION_RESPONSE = (
    "Kindly resend the photo along with your full name for face registration.\n\n"
    "कृपया फेस रजिस्ट्रेशन हेतु अपने पूरे नाम के साथ फोटो दोबारा भेजें।"
)

BLURRY_IMAGE_RESPONSE = (
    "Image received is unclear or blurry. Kindly resend a clear front-facing "
    "photo/selfie along with your full name for successful face registration.\n\n"
    "प्राप्त छवि अस्पष्ट या धुंधली है। कृपया सफल फेस रजिस्ट्रेशन हेतु "
    "एक स्पष्ट फ्रंट-फेसिंग फोटो/सेल्फी अपने पूरे नाम के साथ पुनः भेजें।"
)

REGISTRATION_SUCCESS_RESPONSE = (
    "Thank you. Your face has been successfully registered for AI attendance.\n\n"
    "धन्यवाद। AI उपस्थिति हेतु आपका चेहरा सफलतापूर्वक पंजीकृत हो गया है।\n\n"
    "Name: {name}\n"
    "Phone: {phone}\n"
    "Registered: {timestamp}"
)

REGISTRATION_UPDATE_RESPONSE = (
    "Your face registration has been updated with the new photo.\n\n"
    "आपके फेस रजिस्ट्रेशन को नई फोटो के साथ अपडेट किया गया है।\n\n"
    "Name: {name}\n"
    "Updated: {timestamp}"
)

LOW_QUALITY_RESPONSE = (
    "The image resolution is too low for face registration. "
    "Please send a higher quality photo/selfie.\n\n"
    "फेस रजिस्ट्रेशन हेतु छवि का रिज़ॉल्यूशन बहुत कम है। "
    "कृपया उच्च गुणवत्ता वाली फोटो/सेल्फी भेजें।"
)


# ---------- Image Download ----------

async def download_whatsapp_image(media_id: str) -> bytes | None:
    """Download an image from WhatsApp Cloud API using media ID."""
    token = os.getenv("WHATSAPP_CLOUD_TOKEN", WHATSAPP_CLOUD_TOKEN)
    if not token:
        logger.error("No WhatsApp token for image download")
        return None

    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Get media URL
            resp = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers=headers,
            )
            if resp.status_code != 200:
                logger.error(f"Media URL fetch failed: {resp.status_code} {resp.text}")
                return None

            media_url = resp.json().get("url")
            if not media_url:
                logger.error("No URL in media response")
                return None

            # Step 2: Download image data
            resp = await client.get(media_url, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Image download failed: {resp.status_code}")
                return None

            return resp.content
    except Exception as e:
        logger.error(f"Image download error: {e}")
        return None


# ---------- Image Validation ----------

def validate_image_quality(image_data: bytes) -> tuple[bool, str]:
    """Validate image quality for face registration.

    Returns (is_valid, reason).
    """
    # Check minimum file size
    if len(image_data) < MIN_IMAGE_SIZE:
        return False, "low_quality"

    try:
        img = Image.open(io.BytesIO(image_data))
        width, height = img.size

        # Check minimum resolution
        if width < MIN_RESOLUTION or height < MIN_RESOLUTION:
            return False, "low_resolution"

        # Check blur using Laplacian variance (via Pillow edge detection)
        grayscale = img.convert("L")
        # Simple blur detection: check edge intensity
        from PIL import ImageFilter
        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        edge_data = list(edges.getdata())
        if not edge_data:
            return False, "blurry"

        # Calculate variance of edge intensities
        mean_edge = sum(edge_data) / len(edge_data)
        variance = sum((x - mean_edge) ** 2 for x in edge_data) / len(edge_data)

        if variance < BLUR_THRESHOLD:
            return False, "blurry"

        return True, "ok"

    except Exception as e:
        logger.error(f"Image validation error: {e}")
        return False, "invalid_image"


# ---------- Registration Logic ----------

async def handle_image_message(sender: str, media_id: str, caption: str | None,
                               mime_type: str = "image/jpeg") -> dict:
    """Handle an incoming image message for face registration.

    Returns action dict with status and response sent.
    """
    now = datetime.now(IST)
    timestamp_str = now.strftime("%d/%m/%Y %I:%M %p IST")

    # Step 1: Check if caption (name) is provided
    if not caption or not caption.strip():
        await wa.send_text(sender, NO_CAPTION_RESPONSE)
        await db.log_message(
            direction="outgoing",
            sender=LAW_MINISTER_PHONE_ID,
            recipient=sender,
            content="[Face reg: no caption — asked for name]",
            category="face_registration",
        )
        return {
            "from": sender,
            "type": "image",
            "status": "rejected",
            "reason": "no_caption",
            "response_sent": True,
        }

    name = caption.strip()

    # Step 2: Download the image
    image_data = await download_whatsapp_image(media_id)
    if not image_data:
        await wa.send_text(sender, "Failed to process the image. Please try again.")
        return {
            "from": sender,
            "type": "image",
            "status": "error",
            "reason": "download_failed",
            "response_sent": True,
        }

    # Step 3: Validate image quality
    is_valid, reason = validate_image_quality(image_data)
    if not is_valid:
        if reason == "blurry":
            await wa.send_text(sender, BLURRY_IMAGE_RESPONSE)
        elif reason in ("low_quality", "low_resolution"):
            await wa.send_text(sender, LOW_QUALITY_RESPONSE)
        else:
            await wa.send_text(sender, BLURRY_IMAGE_RESPONSE)

        await db.log_message(
            direction="outgoing",
            sender=LAW_MINISTER_PHONE_ID,
            recipient=sender,
            content=f"[Face reg: image rejected — {reason}]",
            category="face_registration",
        )

        # Log the rejected registration
        await db.log_face_registration(
            phone=sender,
            name=name,
            status="rejected",
            reason=reason,
        )

        return {
            "from": sender,
            "type": "image",
            "status": "rejected",
            "reason": reason,
            "response_sent": True,
        }

    # Step 4: Save the image
    phone_clean = sender.replace("+", "").replace(" ", "")
    image_filename = f"{phone_clean}_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
    image_path = FACE_IMAGES_DIR / image_filename

    try:
        with open(image_path, "wb") as f:
            f.write(image_data)
        logger.info(f"Saved face image: {image_path}")
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        await wa.send_text(sender, "Failed to save the image. Please try again.")
        return {
            "from": sender,
            "type": "image",
            "status": "error",
            "reason": "save_failed",
            "response_sent": True,
        }

    # Step 5: Check if this is new registration or update
    existing = await db.get_face_registration_by_phone(phone_clean)

    if existing:
        # Update existing registration
        await db.update_face_registration(
            phone=phone_clean,
            name=name,
            image_path=str(image_path),
        )
        response = REGISTRATION_UPDATE_RESPONSE.format(
            name=name,
            timestamp=timestamp_str,
        )
    else:
        # New registration
        await db.add_face_registration(
            phone=phone_clean,
            name=name,
            image_path=str(image_path),
        )
        # Also add to staff table
        await db.add_staff(name=name, phone=phone_clean)
        response = REGISTRATION_SUCCESS_RESPONSE.format(
            name=name,
            phone=phone_clean,
            timestamp=timestamp_str,
        )

    await wa.send_text(sender, response)

    await db.log_message(
        direction="outgoing",
        sender=LAW_MINISTER_PHONE_ID,
        recipient=sender,
        content=f"[Face registered: {name}]",
        category="face_registration",
    )

    return {
        "from": sender,
        "type": "image",
        "name": name,
        "status": "registered",
        "image_path": str(image_path),
        "response_sent": True,
    }
