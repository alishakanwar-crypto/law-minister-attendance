"""
Configuration management for the attendance system.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("attendance.config")

CONFIG_FILE = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG = {
    "office_name": "Law Minister's Office",
    "cameras": [],
    "attendance_start_hour": 9,
    "attendance_start_minute": 0,
    "attendance_end_hour": 11,
    "attendance_end_minute": 0,
    "recognition_threshold": 0.45,
    "cooldown_seconds": 300,
    "snapshot_interval_seconds": 5,
    "local_port": 8900,
    "whatsapp_enabled": False,
    "whatsapp_phone_id": "1168433719678061",
    "whatsapp_recipient": "",
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        merged = {**DEFAULT_CONFIG, **cfg}
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    logger.info("Configuration saved")
