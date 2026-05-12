"""
WhatsApp Bot message templates and behavior rules for the
Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister.

All automated messages follow government-office communication standards.
Supports Hindi, English, and mixed Hindi-English (Hinglish) communication.
"""

import re

# ---------- Bot Identity ----------

BOT_IDENTITY = (
    "Automated Attendance Bot — "
    "Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister"
)

BOT_DESCRIPTION = (
    "This bot manages and monitors employee attendance using "
    "Face Recognition Technology integrated with office cameras."
)

# ---------- Language Detection ----------

# Unicode range for Devanagari script (Hindi)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def detect_language(text: str) -> str:
    """Detect the language of incoming text.

    Returns one of: "hindi", "english", "hinglish".
    """
    has_devanagari = bool(_DEVANAGARI_RE.search(text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))

    if has_devanagari and has_latin:
        return "hinglish"
    if has_devanagari:
        return "hindi"
    return "english"


# ---------- Message Templates (English) ----------

WELCOME_MESSAGE = (
    "Hello / Namashkar,\n\n"
    "I am an automated bot for your office attendance system.\n\n"
    "Kindly share:\n"
    "• 2 clear front-face photographs for face registration with your name\n\n"
    "Please ensure the photographs are recent, clear, and properly visible.\n\n"
    "Thankyou / Dhanyawad"
)

WELCOME_MESSAGE_HI = (
    "नमस्कार,\n\n"
    "मैं आपके कार्यालय उपस्थिति (Attendance) हेतु एक स्वचालित बॉट हूँ।\n\n"
    "कृपया फेस रजिस्ट्रेशन के लिए अपने नाम के साथ "
    "2 स्पष्ट फ्रंट फेस फोटो साझा करें।\n\n"
    "धन्यवाद"
)


def attendance_notification(name: str, date_str: str, time_str: str,
                            status: str = "Present",
                            lang: str = "english") -> str:
    """Format an attendance notification matching the official spec."""
    if lang == "hindi":
        return (
            "उपस्थिति सफलतापूर्वक दर्ज हुई\n\n"
            f"नाम: {name}\n"
            f"दिनांक: {date_str}\n"
            f"समय: {time_str}\n"
            f"स्थिति: उपस्थित\n\n"
            "कार्यालय उपस्थिति प्रणाली द्वारा आपका चेहरा "
            "सफलतापूर्वक पहचाना गया है।\n\n"
            "धन्यवाद"
        )
    return (
        "Attendance Marked Successfully\n\n"
        f"Name: {name}\n"
        f"Date: {date_str}\n"
        f"Time: {time_str}\n"
        f"Status: {status}\n\n"
        "Your face has been successfully recognized by the "
        "office attendance system.\n\n"
        "Thankyou / Dhanyawad"
    )


def registration_success(name: str, lang: str = "english") -> str:
    """Confirmation sent after face registration is complete."""
    if lang == "hindi":
        return (
            "फेस रजिस्ट्रेशन सफल\n\n"
            f"नाम: {name}\n"
            f"स्थिति: पंजीकृत\n\n"
            "आपका चेहरा कार्यालय उपस्थिति प्रणाली में सफलतापूर्वक "
            "पंजीकृत हो गया है। अब कैमरे द्वारा पहचाने जाने पर "
            "आपकी उपस्थिति स्वतः दर्ज होगी।\n\n"
            "धन्यवाद"
        )
    return (
        f"Face Registration Successful\n\n"
        f"Name: {name}\n"
        f"Status: Registered\n\n"
        f"Your face has been successfully registered in the "
        f"office attendance system. You will now be marked "
        f"present automatically when recognized by the camera.\n\n"
        f"Thankyou / Dhanyawad"
    )


def registration_rejected(reason: str, lang: str = "english") -> str:
    """Sent when a submitted photo is rejected."""
    if lang == "hindi":
        return (
            "फेस रजिस्ट्रेशन — फोटो अस्वीकृत\n\n"
            f"कारण: {reason}\n\n"
            "कृपया बिना मास्क, धुंधलापन या रुकावट के एक स्पष्ट, "
            "हाल की, सामने से ली गई फोटो प्रस्तुत करें।\n\n"
            "धन्यवाद"
        )
    return (
        "Face Registration — Photo Rejected\n\n"
        f"Reason: {reason}\n\n"
        "Please submit a clear, recent, front-face photograph "
        "without mask, blur, or obstruction.\n\n"
        "Thankyou / Dhanyawad"
    )


def daily_summary(date_str: str, total: int, present_count: int,
                  absent_count: int, pct: int,
                  present_list: list[dict],
                  absent_names: list[str]) -> str:
    """Daily attendance summary for the office administrator."""
    present_lines = "\n".join(
        f"  • {r['name']} — {r['time']}" for r in present_list
    ) or "  (none)"

    absent_lines = "\n".join(
        f"  • {name}" for name in absent_names
    ) or "  (none)"

    return (
        f"Office Attendance — Daily Summary\n\n"
        f"Date: {date_str}\n"
        f"Total Staff: {total}\n"
        f"Present: {present_count}\n"
        f"Absent: {absent_count}\n"
        f"Attendance: {pct}%\n\n"
        f"Present:\n{present_lines}\n\n"
        f"Absent:\n{absent_lines}\n\n"
        f"Office of Shri Arjun Ram Meghwal Ji\n"
        f"Honourable Law Minister\n"
        f"— Automated Report by LEGIT COMMUNISYS"
    )


# ---------- Greeting Response (multilingual) ----------

GREETING_RESPONSE_EN = (
    "Hello,\n\n"
    "Welcome to the Office Attendance Assistance System of "
    "Shri Arjun Ram Meghwal Ji.\n\n"
    "I am an automated attendance bot designed only for office "
    "attendance and work-related communication.\n\n"
    "For face registration, kindly share:\n"
    "• 2 clear front-face photographs with name\n\n"
    "Thankyou"
)

GREETING_RESPONSE_HI = (
    "नमस्कार,\n\n"
    "श्री अर्जुन राम मेघवाल जी के कार्यालय उपस्थिति सहायता प्रणाली "
    "में आपका स्वागत है।\n\n"
    "मैं आपके कार्यालय उपस्थिति (Attendance) हेतु एक स्वचालित बॉट हूँ।\n\n"
    "कृपया फेस रजिस्ट्रेशन के लिए अपने नाम के साथ "
    "2 स्पष्ट फ्रंट फेस फोटो साझा करें।\n\n"
    "धन्यवाद"
)

GREETING_RESPONSE_MIXED = (
    "Hello / Namashkar,\n\n"
    "Welcome to the Office Attendance Assistance System of "
    "Shri Arjun Ram Meghwal Ji.\n\n"
    "I am an automated attendance bot designed only for office "
    "attendance and work-related communication.\n\n"
    "For face registration, kindly share:\n"
    "• 2 clear front-face photographs with name\n\n"
    "Thankyou / Dhanyawad"
)

# Kept for backward compatibility
GREETING_RESPONSE = GREETING_RESPONSE_MIXED

# Words / phrases that trigger the greeting response
GREETING_KEYWORDS_EN = {
    "hi", "hello", "hey", "good morning", "good afternoon",
    "good evening", "greetings",
}

GREETING_KEYWORDS_HI = {
    "namaste", "namashkar", "namaskar", "pranam",
    "shubh prabhat", "jai hind",
    "नमस्ते", "नमस्कार", "प्रणाम", "शुभ प्रभात",
    "जय हिन्द", "जय हिंद",
}

GREETING_KEYWORDS = GREETING_KEYWORDS_EN | GREETING_KEYWORDS_HI


def is_greeting(text: str) -> bool:
    """Check if the incoming message is a greeting."""
    normalised = text.strip().lower()
    if normalised in GREETING_KEYWORDS:
        return True
    for kw in GREETING_KEYWORDS:
        if normalised.startswith(kw):
            return True
    return False


def get_greeting_response(lang: str) -> str:
    """Return the greeting response in the appropriate language."""
    if lang == "hindi":
        return GREETING_RESPONSE_HI
    if lang == "hinglish":
        return GREETING_RESPONSE_MIXED
    return GREETING_RESPONSE_EN


# ---------- Bot Behavior Rules ----------

UNRELATED_RESPONSE_EN = (
    "Kindly note that this automated system is restricted to official "
    "office attendance and work-related communication only."
)

UNRELATED_RESPONSE_HI = (
    "यह स्वचालित प्रणाली केवल कार्यालय उपस्थिति एवं "
    "आधिकारिक कार्य संबंधी संवाद हेतु सीमित है।"
)

UNRELATED_RESPONSE_MIXED = (
    "यह स्वचालित प्रणाली केवल कार्यालय उपस्थिति एवं "
    "आधिकारिक कार्य संबंधी संवाद हेतु सीमित है। / "
    "This automated system is restricted to official office "
    "attendance and work-related communication only."
)

# Kept for backward compatibility
UNRELATED_RESPONSE = UNRELATED_RESPONSE_MIXED


def get_unrelated_response(lang: str) -> str:
    """Return the restriction message in the appropriate language."""
    if lang == "hindi":
        return UNRELATED_RESPONSE_HI
    if lang == "hinglish":
        return UNRELATED_RESPONSE_MIXED
    return UNRELATED_RESPONSE_EN


# Topics the bot is allowed to respond to
ALLOWED_TOPICS = {
    "attendance", "registration", "face", "photo", "photograph",
    "present", "absent", "check-in", "checkin", "office", "timing",
    "time", "leave", "help", "register", "status", "camera",
    "name", "report", "summary",
    # Hindi topic keywords
    "उपस्थिति", "रजिस्ट्रेशन", "फोटो", "कार्यालय", "समय",
    "छुट्टी", "मदद", "स्थिति", "रिपोर्ट",
}


def classify_message(text: str) -> str:
    """Classify an incoming message into a response category.

    Returns one of: "greeting", "allowed", "unrelated".
    """
    if is_greeting(text):
        return "greeting"

    normalised = text.strip().lower()
    for topic in ALLOWED_TOPICS:
        if topic in normalised:
            return "allowed"

    return "unrelated"


def get_auto_response(text: str) -> str | None:
    """Return an automatic response for the given message, or None
    if the message is an allowed office topic that needs further
    processing by the system.
    """
    lang = detect_language(text)
    category = classify_message(text)

    if category == "greeting":
        return get_greeting_response(lang)
    if category == "unrelated":
        return get_unrelated_response(lang)
    return None
