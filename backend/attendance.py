"""
Attendance processing engine.

Monitors camera feeds, detects faces, matches against registered staff,
and logs attendance with deduplication.
"""

import asyncio
import io
import logging
import time
from datetime import datetime, date
from pathlib import Path

import numpy as np

from backend import database as db
from backend import face_engine
from backend import camera as cam
from backend.config import load_config

logger = logging.getLogger("attendance.engine")

ATTENDANCE_SNAPSHOTS_DIR = Path(__file__).parent.parent / "attendance_snapshots"
ATTENDANCE_SNAPSHOTS_DIR.mkdir(exist_ok=True)


class AttendanceEngine:
    """Monitors camera feeds and marks attendance via face recognition."""

    def __init__(self):
        self.running = False
        self._task: asyncio.Task | None = None
        self._cooldowns: dict[str, float] = {}
        self._stats = {
            "frames_processed": 0,
            "faces_detected": 0,
            "matches_found": 0,
            "started_at": None,
            "last_frame_at": None,
        }

    @property
    def stats(self) -> dict:
        return {**self._stats, "running": self.running}

    def _is_in_window(self) -> bool:
        """Check if current time is within the attendance window."""
        cfg = load_config()
        now = datetime.now()
        start = now.replace(
            hour=cfg["attendance_start_hour"],
            minute=cfg["attendance_start_minute"],
            second=0,
        )
        end = now.replace(
            hour=cfg["attendance_end_hour"],
            minute=cfg["attendance_end_minute"],
            second=0,
        )
        return start <= now <= end

    def _check_cooldown(self, staff_id: str) -> bool:
        """Return True if this staff member is still in cooldown."""
        cfg = load_config()
        cooldown = cfg.get("cooldown_seconds", 300)
        last = self._cooldowns.get(staff_id, 0)
        return (time.time() - last) < cooldown

    def _set_cooldown(self, staff_id: str):
        self._cooldowns[staff_id] = time.time()

    def _process_frame(self, image_bytes: bytes, camera_name: str) -> list[dict]:
        """Process a single frame: detect faces, match, log attendance.

        Returns list of attendance records created.
        """
        cfg = load_config()
        threshold = cfg.get("recognition_threshold", 0.45)

        enhanced = face_engine.preprocess_image(image_bytes)
        detections = face_engine.detect_and_encode(enhanced)
        self._stats["frames_processed"] += 1
        self._stats["last_frame_at"] = datetime.now().isoformat()

        if not detections:
            return []

        self._stats["faces_detected"] += len(detections)
        records = []

        for embedding, cropped_face, bbox in detections:
            match = face_engine.match_face(embedding, threshold=threshold)
            if match is None:
                continue

            staff_id, name, confidence = match

            if self._check_cooldown(staff_id):
                continue

            self._set_cooldown(staff_id)

            ts = int(time.time())
            snap_filename = f"{staff_id}_{ts}.jpg"
            snap_path = ATTENDANCE_SNAPSHOTS_DIR / snap_filename
            with open(snap_path, "wb") as f:
                f.write(cropped_face)

            log_id = db.log_attendance(
                staff_id=staff_id,
                name=name,
                confidence=confidence,
                snapshot_path=str(snap_path),
                camera_source=camera_name,
            )

            self._stats["matches_found"] += 1
            record = {
                "log_id": log_id,
                "staff_id": staff_id,
                "name": name,
                "confidence": round(confidence, 4),
                "camera": camera_name,
                "time": datetime.now().strftime("%H:%M:%S"),
            }
            records.append(record)
            logger.info(
                f"Attendance: {name} ({staff_id}) — "
                f"confidence={confidence:.3f} camera={camera_name}"
            )

        return records

    async def _run_loop(self):
        """Main monitoring loop."""
        logger.info("Attendance engine started")
        self._stats["started_at"] = datetime.now().isoformat()

        while self.running:
            cfg = load_config()
            interval = cfg.get("snapshot_interval_seconds", 5)
            cameras = db.get_cameras(active_only=True)

            if not cameras:
                await asyncio.sleep(interval)
                continue

            if not self._is_in_window():
                await asyncio.sleep(30)
                continue

            for camera_cfg in cameras:
                if not self.running:
                    break
                try:
                    image_bytes = cam.capture_from_camera(camera_cfg)
                    if image_bytes:
                        self._process_frame(image_bytes, camera_cfg["name"])
                except Exception as e:
                    logger.error(f"Error processing camera {camera_cfg['name']}: {e}")

            await asyncio.sleep(interval)

        logger.info("Attendance engine stopped")

    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.get_event_loop().create_task(self._run_loop())
        logger.info("Attendance engine start requested")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Attendance engine stop requested")

    def process_single_image(self, image_bytes: bytes,
                             camera_name: str = "manual") -> list[dict]:
        """Process a single image (for testing / manual check-in)."""
        return self._process_frame(image_bytes, camera_name)


engine = AttendanceEngine()
