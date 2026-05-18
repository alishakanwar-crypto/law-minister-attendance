"""Entry point for the office attendance engine.

Usage:
    python -m office_engine.run              # Run the engine
    python -m office_engine.run --setup      # Create default config
    python -m office_engine.run --status     # Show engine status
    python -m office_engine.run --sync       # One-time sync only
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from office_engine.config import load_config, create_default_config, CONFIG_FILE
from office_engine.engine import AttendanceEngine


def setup_logging(log_file: str = ""):
    """Configure logging to both console and file."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Law Minister Office Attendance Engine"
    )
    parser.add_argument(
        "--setup", action="store_true",
        help="Create default config file with example cameras",
    )
    parser.add_argument(
        "--sync", action="store_true",
        help="Run a one-time sync of registrations from cloud",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Check cloud connection and show status",
    )
    args = parser.parse_args()

    if args.setup:
        cfg = create_default_config()
        print(f"Default config created at: {CONFIG_FILE}")
        print(f"Cloud URL: {cfg['cloud_url']}")
        print(f"Edit {CONFIG_FILE} to add your camera details.")
        return

    # Load config
    if not CONFIG_FILE.exists():
        print(f"No config file found at {CONFIG_FILE}")
        print("Run with --setup to create a default config first.")
        return

    cfg = load_config()
    setup_logging(cfg.get("log_file", ""))

    logger = logging.getLogger("office_engine")

    if args.status:
        import httpx

        print(f"Cloud URL: {cfg['cloud_url']}")
        print(f"Cameras configured: {len(cfg.get('cameras', []))}")
        try:
            resp = httpx.get(f"{cfg['cloud_url']}/health", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"Cloud status: {data.get('status', 'unknown')}")
                print(f"Cloud time: {data.get('timestamp_ist', 'unknown')}")
            else:
                print(f"Cloud error: HTTP {resp.status_code}")
        except Exception as e:
            print(f"Cloud connection failed: {e}")
        return

    if args.sync:
        engine = AttendanceEngine()
        asyncio.run(engine.sync_registrations())
        print(f"Sync complete. Known faces: {len(engine.known_embeddings)}")
        return

    # Run the full engine
    print("=" * 60)
    print("LAW MINISTER OFFICE — AI ATTENDANCE ENGINE")
    print("=" * 60)
    print(f"Cloud: {cfg['cloud_url']}")
    print(f"Cameras: {len(cfg.get('cameras', []))}")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    engine = AttendanceEngine()
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        print("\nEngine stopped.")


if __name__ == "__main__":
    main()
