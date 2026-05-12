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
from backend import whatsapp as wa
from backend.config import load_config
from backend.liveness import LivenessChecker, texture_score, TEXTURE_THRESHOLD

logger = logging.getLogger("attendance.engine")

ATTENDANCE_SNAPSHOTS_DIR = Path(__file__).parent.parent / "attendance_snapshots"
ATTENDANCE_SNAPSHOTS_DIR.mkdir(exist_ok=True)


class AttendanceEngine:
    """Monitors camera feeds and marks attendance via face recognition."""

    def __init__(self):
        self.running = False
        self._task: asyncio.Task | None = None
        self._cooldowns: dict[str, float] = {}
        self._liveness = LivenessChecker()
        self._stats = {
            "frames_processed": 0,
            "faces_detected": 0,
            "matches_found": 0,
            "spoofs_rejected": 0,
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

    def _process_frame(
        self,
        image_bytes: bytes,
        camera_name: str,
        single_frame: bool = False,
    ) -> list[dict]:
        """Process a single frame: detect faces, match, log attendance.

        Args:
            single_frame: when True, skip multi-frame checks (blink, motion)
                but still run single-frame texture analysis to reject flat
                surfaces (printed photos, screens).

        Returns list of attendance records created.
        """
        cfg = load_config()
        threshold = cfg.get("recognition_threshold", 0.45)

        enhanced = face_engine.preprocess_image(image_bytes)
        detections = face_engine.detect_and_encode(
            enhanced, return_face_objects=True,
        )
        self._stats["frames_processed"] += 1
        self._stats["last_frame_at"] = datetime.now().isoformat()

        if not detections:
            return []

        self._stats["faces_detected"] += len(detections)
        records = []

        for embedding, cropped_face, bbox, face_obj, face_crop_bgr in detections:
            match = face_engine.match_face(embedding, threshold=threshold)
            if match is None:
                continue

            staff_id, name, confidence = match

            if self._check_cooldown(staff_id):
                continue

            # --- Anti-spoofing liveness check ---
            if single_frame:
                # Single-image mode: run texture analysis only
                tscore = 999.0
                if face_crop_bgr is not None and face_crop_bgr.size > 0:
                    tscore = texture_score(face_crop_bgr)
                if tscore < TEXTURE_THRESHOLD:
                    self._stats["spoofs_rejected"] += 1
                    logger.warning(
                        f"SPOOF REJECTED (manual): {name} ({staff_id}) — "
                        f"flat_surface texture={tscore:.1f}"
                    )
                    self._liveness._log_spoof(staff_id, "flat_surface_manual", tscore)
                    continue
                liveness = {"live": True, "reason": "single_frame_texture_ok",
                            "motion": 0.0, "texture": round(tscore, 2),
                            "blink": False}
            else:
                liveness = self._liveness.update(
                    staff_id=staff_id,
                    face_obj=face_obj,
                    face_crop_bgr=face_crop_bgr,
                )

                if not liveness["live"]:
                    reason = liveness["reason"]
                    if reason not in ("collecting_frames", "waiting_for_blink",
                                      "need 1 more frame(s)",
                                      "need 2 more frame(s)",
                                      "need 3 more frame(s)"):
                        # Definite spoof — reject and log
                        if not reason.startswith("need"):
                            self._stats["spoofs_rejected"] += 1
                            logger.warning(
                                f"SPOOF REJECTED: {name} ({staff_id}) — "
                                f"reason={reason} motion={liveness['motion']} "
                                f"texture={liveness['texture']}"
                            )
                            self._liveness.reset(staff_id)
                    # Still collecting evidence or waiting — skip this frame
                    continue

                # Liveness confirmed via camera monitoring
                self._liveness.reset(staff_id)

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
                "liveness": {
                    "motion": liveness["motion"],
                    "texture": liveness["texture"],
                    "blink": liveness["blink"],
                },
            }
            records.append(record)
            logger.info(
                f"Attendance: {name} ({staff_id}) — "
                f"confidence={confidence:.3f} camera={camera_name} "
                f"liveness=OK motion={liveness['motion']} "
                f"texture={liveness['texture']}"
            )
            wa.notify_checkin(
                cfg, staff_name=name, staff_id=staff_id,
                confidence=confidence, camera=camera_name,
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

            loop = asyncio.get_running_loop()
            for camera_cfg in cameras:
                if not self.running:
                    break
                try:
                    image_bytes = await loop.run_in_executor(
                        None, cam.capture_from_camera, camera_cfg)
                    if image_bytes:
                        await loop.run_in_executor(
                            None, self._process_frame, image_bytes,
                            camera_cfg["name"])
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
        """Process a single image (for testing / manual check-in).

        Multi-frame checks (blink, motion) are skipped because a single
        image cannot satisfy them.  Texture analysis is still performed
        to reject flat surfaces (printed photos, screens).
        """
        return self._process_frame(image_bytes, camera_name, single_frame=True)


engine = AttendanceEngine()
