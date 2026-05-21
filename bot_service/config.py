"""Configuration for the standalone Law Minister WhatsApp Bot."""

import os

# WhatsApp Cloud API
WHATSAPP_CLOUD_TOKEN = os.getenv("WHATSAPP_CLOUD_TOKEN", "")
LAW_MINISTER_PHONE_ID = os.getenv("LAW_MINISTER_PHONE_ID", "1168433719678061")
WABA_ID = os.getenv("LAW_MINISTER_WABA_ID", "2417647228700804")
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "law_minister_bot_verify")

# Database
DB_PATH = os.getenv("DB_PATH", "/data/lm_bot.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lm_bot.db")

# Admin numbers (with country code)
ADMINS = {
    "918796105084": "Ali",
}

# Daily summary recipients (phone -> name)
DAILY_SUMMARY_RECIPIENTS = {}

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
