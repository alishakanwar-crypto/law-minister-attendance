"""Face registration via WhatsApp — handles image receiving, validation, and storage."""

import io
import logging
import os
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image

from bot_service.config import LAW_MINISTER_PHONE_ID, WHATSAPP_CLOUD_TOKEN
from bot_service import database as db
from bot_service import whatsapp as wa
from bot_service import ist_time

logger = logging.getLogger("lm_bot.face_reg")

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

NO_FACE_RESPONSE = (
    "Inappropriate file sent. Only selfie/face photos are accepted for registration.\n\n"
    "अनुचित फ़ाइल भेजी गई। रजिस्ट्रेशन हेतु केवल सेल्फी/फेस फोटो स्वीकार्य हैं।"
)

FIRST_NAME_MISMATCH_RESPONSE = (
    "A person with the same first name is already registered but the photo does not match.\n"
    "Kindly resend the photo along with your full name (first name and surname) for registration.\n\n"
    "इस पहले नाम से पहले से एक व्यक्ति पंजीकृत है लेकिन फोटो मेल नहीं खाती।\n"
    "कृपया रजिस्ट्रेशन हेतु अपने पूरे नाम (प्रथम नाम और उपनाम) के साथ फोटो दोबारा भेजें।"
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


def detect_face(image_data: bytes) -> bool:
    """Detect if the image contains a human face using OpenCV Haar cascade.

    Returns True if at least one face is found.
    """
    try:
        arr = np.frombuffer(image_data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return False

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(60, 60),
        )

        found = len(faces) > 0
        logger.info(f"Face detection: {len(faces)} face(s) found")
        return found
    except Exception as e:
        logger.error(f"Face detection error: {e}")
        return False


FACE_MATCH_THRESHOLD = 0.55  # histogram correlation threshold


def compare_faces(image_data_a: bytes, image_data_b: bytes) -> bool:
    """Compare two face images using histogram correlation.

    Returns True if the faces are likely the same person.
    """
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        def extract_face_region(data: bytes):
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return None
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60),
            )
            if len(faces) == 0:
                return None
            x, y, w, h = faces[0]
            face_roi = img[y:y + h, x:x + w]
            face_roi = cv2.resize(face_roi, (128, 128))
            return face_roi

        face_a = extract_face_region(image_data_a)
        face_b = extract_face_region(image_data_b)

        if face_a is None or face_b is None:
            return False

        # Compare using histogram correlation on HSV color space
        hsv_a = cv2.cvtColor(face_a, cv2.COLOR_BGR2HSV)
        hsv_b = cv2.cvtColor(face_b, cv2.COLOR_BGR2HSV)

        hist_a = cv2.calcHist([hsv_a], [0, 1], None, [50, 60], [0, 180, 0, 256])
        hist_b = cv2.calcHist([hsv_b], [0, 1], None, [50, 60], [0, 180, 0, 256])

        cv2.normalize(hist_a, hist_a, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(hist_b, hist_b, 0, 1, cv2.NORM_MINMAX)

        score = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
        logger.info(f"Face comparison score: {score:.3f} (threshold: {FACE_MATCH_THRESHOLD})")
        return score >= FACE_MATCH_THRESHOLD
    except Exception as e:
        logger.error(f"Face comparison error: {e}")
        return False


# ---------- Registration Logic ----------

async def handle_image_message(sender: str, media_id: str, caption: str | None,
                               mime_type: str = "image/jpeg") -> dict:
    """Handle an incoming image message for face registration.

    Returns action dict with status and response sent.
    """
    now = ist_time.now()
    timestamp_str = ist_time.now_human()

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

    # Step 3b: Detect face — reject documents, screenshots, non-face images
    has_face = detect_face(image_data)
    if not has_face:
        await wa.send_text(sender, NO_FACE_RESPONSE)
        await db.log_message(
            direction="outgoing",
            sender=LAW_MINISTER_PHONE_ID,
            recipient=sender,
            content="[Face reg: no face detected — rejected as non-face image]",
            category="rejected_file",
        )
        await db.log_face_registration(
            phone=sender,
            name=name,
            status="rejected",
            reason="no_face_detected",
        )
        return {
            "from": sender,
            "type": "image",
            "status": "rejected",
            "reason": "no_face_detected",
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

    # Step 5: Registration with smart name + face matching.
    # Determine if caption is first-name-only (single word, no spaces).
    is_first_name_only = " " not in name

    # 5a: If first-name-only, search ALL registrations for matching first name
    if is_first_name_only:
        matches = await db.find_registrations_by_first_name(name)
        if matches:
            # Found existing person(s) with this first name — compare faces
            matched_person = None
            for match in matches:
                stored_path = match.get("image_path", "")
                if stored_path and Path(stored_path).exists():
                    stored_data = Path(stored_path).read_bytes()
                    if compare_faces(image_data, stored_data):
                        matched_person = match
                        break

            if matched_person:
                # Photos match — same person, update their registration
                use_name = matched_person["name"]
                use_phone = matched_person["phone"]
                await db.update_face_registration(
                    phone=use_phone,
                    name=use_name,
                    image_path=str(image_path),
                )
                response = REGISTRATION_UPDATE_RESPONSE.format(
                    name=use_name,
                    timestamp=timestamp_str,
                )
                await wa.send_text(sender, response)
                await db.log_message(
                    direction="outgoing",
                    sender=LAW_MINISTER_PHONE_ID,
                    recipient=sender,
                    content=f"[Face updated via first-name match: {use_name}]",
                    category="face_registration",
                )
                return {
                    "from": sender,
                    "type": "image",
                    "name": use_name,
                    "status": "registered",
                    "image_path": str(image_path),
                    "response_sent": True,
                }
            else:
                # Photos don't match — different person, ask for full name
                await wa.send_text(sender, FIRST_NAME_MISMATCH_RESPONSE)
                await db.log_message(
                    direction="outgoing",
                    sender=LAW_MINISTER_PHONE_ID,
                    recipient=sender,
                    content=f"[Face reg: first name '{name}' matches existing but photo differs — asked for full name]",
                    category="face_registration",
                )
                return {
                    "from": sender,
                    "type": "image",
                    "status": "rejected",
                    "reason": "first_name_photo_mismatch",
                    "response_sent": True,
                }

    # 5b: Full name or no existing first-name match — standard flow
    existing = await db.get_face_registration_by_phone(phone_clean)

    if existing:
        # Same phone — update registration
        await db.update_face_registration(
            phone=phone_clean,
            name=name,
            image_path=str(image_path),
        )
        await db.add_staff(name=name, phone=phone_clean)
        response = REGISTRATION_UPDATE_RESPONSE.format(
            name=name,
            timestamp=timestamp_str,
        )
    else:
        # Brand new registration
        await db.add_face_registration(
            phone=phone_clean,
            name=name,
            image_path=str(image_path),
        )
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
