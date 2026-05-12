"""
WhatsApp Bot message templates and behavior rules for the
Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister.

All automated messages follow government-office communication standards.
"""

# ---------- Bot Identity ----------

BOT_IDENTITY = (
    "Automated Attendance Bot — "
    "Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister"
)

BOT_DESCRIPTION = (
    "This bot manages and monitors employee attendance using "
    "Face Recognition Technology integrated with office cameras."
)

# ---------- Message Templates ----------

WELCOME_MESSAGE = (
    "Hello / Namashkar,\n\n"
    "I am an automated bot for your office attendance system.\n\n"
    "Kindly share:\n"
    "• 2 clear front-face photographs for face registration with your name\n\n"
    "Please ensure the photographs are recent, clear, and properly visible.\n\n"
    "Thankyou / Dhanyawad"
)


def attendance_notification(name: str, date_str: str, time_str: str,
                            status: str = "Present") -> str:
    """Format an attendance notification matching the official spec."""
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


def registration_success(name: str) -> str:
    """Confirmation sent after face registration is complete."""
    return (
        f"Face Registration Successful\n\n"
        f"Name: {name}\n"
        f"Status: Registered\n\n"
        f"Your face has been successfully registered in the "
        f"office attendance system. You will now be marked "
        f"present automatically when recognized by the camera.\n\n"
        f"Thankyou / Dhanyawad"
    )


def registration_rejected(reason: str) -> str:
    """Sent when a submitted photo is rejected."""
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


# ---------- Bot Behavior Rules ----------

UNRELATED_RESPONSE = (
    "This is an automated attendance bot for the "
    "Office of Shri Arjun Ram Meghwal Ji, Honourable Law Minister.\n\n"
    "I can only assist with:\n"
    "• Attendance queries\n"
    "• Face registration\n"
    "• Office timings\n\n"
    "For other matters, please contact the office administration.\n\n"
    "Thankyou / Dhanyawad"
)

# Topics the bot is allowed to respond to
ALLOWED_TOPICS = {
    "attendance", "registration", "face", "photo", "photograph",
    "present", "absent", "check-in", "office", "timing", "time",
    "leave", "help", "hi", "hello", "namashkar", "namaskar",
    "register", "status",
}
