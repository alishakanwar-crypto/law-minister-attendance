"""Bot message handler — processes incoming WhatsApp messages."""

import logging
import re
import time

from bot_service.config import ADMINS, LAW_MINISTER_PHONE_ID
from bot_service import database as db
from bot_service import whatsapp as wa
from bot_service.reports import generate_summary_excel
from bot_service.face_registration import handle_image_message

logger = logging.getLogger("lm_bot.handler")

# ---------- Language Detection ----------

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def detect_language(text: str) -> str:
    has_devanagari = bool(_DEVANAGARI_RE.search(text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))
    if has_devanagari and has_latin:
        return "hinglish"
    if has_devanagari:
        return "hindi"
    return "english"


# ---------- Greeting Detection ----------

GREETING_KEYWORDS = {
    "hi", "hello", "hey", "namaste", "namashkar", "namaskar",
    "good morning", "good afternoon", "good evening",
    "shubh prabhat", "pranam", "jai hind",
    "नमस्ते", "नमस्कार", "प्रणाम", "शुभ प्रभात",
    "जय हिन्द", "जय हिंद",
}

ALLOWED_TOPICS = {
    "attendance", "registration", "face", "photo", "photograph",
    "present", "absent", "check-in", "checkin", "office", "timing",
    "time", "leave", "help", "register", "status", "camera",
    "name", "report", "summary",
    "उपस्थिति", "रजिस्ट्रेशन", "फोटो", "कार्यालय", "समय",
    "छुट्टी", "मदद", "स्थिति", "रिपोर्ट",
}


def _is_greeting(text: str) -> bool:
    normalised = text.strip().lower()
    if normalised in GREETING_KEYWORDS:
        return True
    for kw in GREETING_KEYWORDS:
        if normalised.startswith(kw):
            return True
    return False


# ---------- Response Templates ----------

GREETING_RESPONSE = (
    "Hello / नमस्कार,\n\n"
    "Welcome to the Face Recognition Attendance System of "
    "Shri Arjun Ram Meghwal Ji.\n"
    "श्री अर्जुन राम मेघवाल जी की फेस रिकग्निशन अटेंडेंस सिस्टम "
    "में आपका स्वागत है।\n\n"
    "I am an automated bot designed only for office attendance "
    "and official work-related communication.\n"
    "मैं एक स्वचालित बॉट हूँ जो केवल कार्यालय उपस्थिति एवं "
    "आधिकारिक कार्य संबंधी संवाद हेतु बनाया गया है।\n\n"
    "Kindly share:\n"
    "• 2 clear front-face photographs for face registration "
    "along with your name.\n"
    "• फेस रजिस्ट्रेशन हेतु 2 स्पष्ट फ्रंट फेस फोटो के साथ "
    "अपना नाम साझा करें।\n\n"
    "Please ensure the photographs are clear, recent, "
    "and properly visible.\n"
    "कृपया सुनिश्चित करें कि फोटो स्पष्ट, हाल की एवं "
    "सही रूप से दिखाई देने वाली हों।\n\n"
    "Thankyou / धन्यवाद"
)

UNRELATED_RESPONSE = (
    "Kindly note that this automated system is restricted to official "
    "office attendance and work-related communication only. / "
    "कृपया ध्यान दें कि यह स्वचालित प्रणाली केवल कार्यालय उपस्थिति "
    "एवं आधिकारिक कार्य संबंधी संवाद हेतु सीमित है।"
)


def _get_auto_response(text: str) -> str | None:
    """Return auto-response for the message, or None for allowed topics."""
    if _is_greeting(text):
        return GREETING_RESPONSE

    normalised = text.strip().lower()
    for topic in ALLOWED_TOPICS:
        if topic in normalised:
            return None  # Allowed topic — no auto-reply needed

    return UNRELATED_RESPONSE


# ---------- Deduplication ----------

_processed_ids: dict[str, float] = {}
_DEDUP_TTL = 300


def _is_duplicate(msg_id: str) -> bool:
    now = time.time()
    expired = [k for k, t in _processed_ids.items() if now - t > _DEDUP_TTL]
    for k in expired:
        del _processed_ids[k]
    if msg_id in _processed_ids:
        return True
    _processed_ids[msg_id] = now
    return False


# ---------- Admin Commands ----------

ADMIN_COMMANDS = {"summary", "report", "excel", "log", "messages", "admin help",
                  "admin", "commands", "staff", "today", "registrations", "regs"}


async def _handle_admin_command(sender: str, text: str) -> bool:
    """Handle admin commands. Returns True if handled."""
    normalised = text.strip().lower()

    if normalised not in ADMIN_COMMANDS:
        return False

    admin_name = ADMINS.get(sender, "Admin")

    # Summary / Report command
    if normalised in ("summary", "report", "excel", "log", "messages"):
        await wa.send_text(sender, f"Generating message summary, {admin_name}... Please wait.")
        filepath = await generate_summary_excel(days=7)
        if filepath:
            from datetime import datetime, timezone, timedelta
            ist = timezone(timedelta(hours=5, minutes=30))
            now_str = datetime.now(ist).strftime("%d/%m/%Y %I:%M %p")
            caption = f"Law Minister Bot — Message Summary\nGenerated: {now_str}\nPeriod: Last 7 days"
            sent = await wa.send_document(sender, filepath, caption, "message_summary.xlsx")
            import os
            try:
                os.unlink(filepath)
            except Exception:
                pass
            if not sent:
                await wa.send_text(sender, "Failed to send the Excel file. Please try again.")
        else:
            await wa.send_text(sender, "No messages found in the last 7 days.")
        return True

    # Staff list
    if normalised == "staff":
        staff = await db.get_staff_list()
        if staff:
            lines = [f"Staff List ({len(staff)} members):\n"]
            for s in staff:
                lines.append(f"• {s['name']} — {s['phone']} ({s['designation'] or 'N/A'})")
            await wa.send_text(sender, "\n".join(lines))
        else:
            await wa.send_text(sender, "No staff members registered yet.")
        return True

    # Today's attendance
    if normalised == "today":
        records = await db.get_attendance_records()
        if records:
            lines = [f"Today's Attendance ({len(records)} check-ins):\n"]
            for r in records:
                lines.append(f"• {r['staff_name']} — {r['time']} ({r['status']})")
            await wa.send_text(sender, "\n".join(lines))
        else:
            await wa.send_text(sender, "No attendance records for today yet.")
        return True

    # Registrations
    if normalised in ("registrations", "regs"):
        stats = await db.get_registration_stats()
        regs = await db.get_all_registrations("registered")
        lines = [
            f"Face Registrations:\n",
            f"Total: {stats['total']} | Registered: {stats['registered']} | "
            f"Rejected: {stats['rejected']}\n",
        ]
        if regs:
            lines.append("Registered Users:")
            for r in regs[:15]:
                lines.append(f"• {r['name']} — {r['phone']}")
            if len(regs) > 15:
                lines.append(f"... and {len(regs) - 15} more")
        else:
            lines.append("No registered users yet.")
        await wa.send_text(sender, "\n".join(lines))
        return True

    # Help
    if normalised in ("admin help", "admin", "commands"):
        help_text = (
            f"Admin Commands ({admin_name}):\n\n"
            "• *summary* / *report* — Excel summary of all messages (7 days)\n"
            "• *staff* — List all registered staff\n"
            "• *today* — Today's attendance records\n"
            "• *registrations* — Face registration status\n"
            "• *admin help* — Show this menu"
        )
        await wa.send_text(sender, help_text)
        return True

    return False


# ---------- Main Handler ----------

async def handle_webhook(body: dict) -> dict:
    """Process incoming webhook payload for the Law Minister phone number."""
    actions = []

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                msg_type = message.get("type", "")
                sender = message.get("from", "")
                msg_id = message.get("id", "")

                if msg_id and _is_duplicate(msg_id):
                    logger.info(f"Duplicate message {msg_id}, skipping.")
                    continue

                # Handle IMAGE messages (face registration)
                if msg_type == "image":
                    image_info = message.get("image", {})
                    media_id = image_info.get("id", "")
                    caption = image_info.get("caption", "")
                    mime_type = image_info.get("mime_type", "image/jpeg")

                    await db.log_message(
                        direction="incoming",
                        sender=sender,
                        recipient=LAW_MINISTER_PHONE_ID,
                        content=f"[Image: {caption or 'no caption'}]",
                        msg_type="image",
                        category="face_registration",
                    )

                    if media_id:
                        result = await handle_image_message(
                            sender=sender,
                            media_id=media_id,
                            caption=caption,
                            mime_type=mime_type,
                        )
                        actions.append(result)
                    continue

                # Handle TEXT messages
                if msg_type != "text":
                    continue

                text = message.get("text", {}).get("body", "")

                # Log incoming message
                await db.log_message(
                    direction="incoming",
                    sender=sender,
                    recipient=LAW_MINISTER_PHONE_ID,
                    content=text,
                    category="incoming",
                )

                # Admin commands
                if sender in ADMINS:
                    handled = await _handle_admin_command(sender, text)
                    if handled:
                        await db.log_message(
                            direction="outgoing",
                            sender=LAW_MINISTER_PHONE_ID,
                            recipient=sender,
                            content=f"[Admin command: {text.strip().lower()}]",
                            category="admin_command",
                        )
                        actions.append({
                            "from": sender,
                            "text": text,
                            "category": "admin_command",
                            "response_sent": True,
                        })
                        continue

                # Auto-response
                auto_reply = _get_auto_response(text)
                if auto_reply:
                    sent = await wa.send_text(sender, auto_reply)
                    lang = detect_language(text)
                    category = "greeting" if _is_greeting(text) else "unrelated"

                    await db.log_message(
                        direction="outgoing",
                        sender=LAW_MINISTER_PHONE_ID,
                        recipient=sender,
                        content=auto_reply[:500],
                        category=category,
                    )

                    actions.append({
                        "from": sender,
                        "text": text,
                        "category": category,
                        "language": lang,
                        "response_sent": sent,
                    })
                    logger.info(f"Auto-replied to {sender} ({category}/{lang})")
                else:
                    actions.append({
                        "from": sender,
                        "text": text,
                        "category": "allowed",
                        "language": detect_language(text),
                        "response_sent": False,
                    })

    return {"status": "ok", "bot": "law_minister", "actions": actions}
