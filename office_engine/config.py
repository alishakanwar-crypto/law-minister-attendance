"""Configuration for the office engine."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("office_engine.config")

CONFIG_FILE = Path(__file__).parent.parent / "office_config.json"

DEFAULT_CONFIG = {
    "cloud_url": "https://law-minister-bot.fly.dev",
    "sync_interval_seconds": 60,
    "snapshot_interval_seconds": 5,
    "recognition_threshold": 0.45,
    "cooldown_seconds": 300,
    "attendance_start_hour": 9,
    "attendance_start_minute": 0,
    "attendance_end_hour": 18,
    "attendance_end_minute": 0,
    "cameras": [],
    "face_images_dir": "face_images",
    "snapshots_dir": "attendance_snapshots",
    "embeddings_file": "face_embeddings.json",
    "log_file": "office_engine.log",
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    logger.info("Configuration saved")


def create_default_config():
    """Create a default config file with example cameras."""
    example = {
        **DEFAULT_CONFIG,
        "cameras": [
            {
                "name": "Main Entry Gate",
                "type": "rtsp",
                "url": "rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101",
                "enabled": True,
            },
            {
                "name": "Reception",
                "type": "rtsp",
                "url": "rtsp://admin:password@192.168.1.101:554/Streaming/Channels/101",
                "enabled": True,
            },
        ],
    }
    save_config(example)
    logger.info(f"Default config created at {CONFIG_FILE}")
    return example
