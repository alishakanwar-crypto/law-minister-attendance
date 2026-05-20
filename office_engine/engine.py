"""Main attendance engine — orchestrates sync, camera capture, and recognition."""

import asyncio
import io
import logging
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
import numpy as np

from office_engine.config import load_config
from office_engine.cloud_sync import CloudSync
from office_engine.camera_reader import CameraReader
from office_engine.face_processor import (
    extract_embedding,
    detect_faces_in_frame,
    match_face,
)

logger = logging.getLogger("office_engine.engine")


class CloudLogHandler(logging.Handler):
    """Buffers log records for periodic pushing to the cloud."""

    def __init__(self, maxlen: int = 500):
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord):
        try:
            self.buffer.append(self.format(record))
        except Exception:
            pass

    def drain(self) -> list[str]:
        """Return and clear all buffered lines."""
        lines = list(self.buffer)
        self.buffer.clear()
        return lines

IST = timezone(timedelta(hours=5, minutes=30))

SNAPSHOTS_DIR = Path("attendance_snapshots")
SNAPSHOTS_DIR.mkdir(exist_ok=True)


class AttendanceEngine:
    """Pull-based attendance engine for the office PC.

    1. Periodically syncs new registrations from cloud
    2. Captures frames from local cameras
    3. Runs face recognition against known embeddings
    4. Pushes attendance results to cloud for WhatsApp notification
    """

    def __init__(self):
        self.cfg = load_config()
        self.face_images_dir = Path(self.cfg["face_images_dir"])
        self.face_images_dir.mkdir(parents=True, exist_ok=True)

        self.cloud = CloudSync(
            cloud_url=self.cfg["cloud_url"],
            face_images_dir=self.face_images_dir,
            embeddings_file=Path(self.cfg["embeddings_file"]),
        )
        self.camera = CameraReader(self.cfg.get("cameras", []))
        self.known_embeddings: dict = {}
        self._daily_marked: dict[str, str] = {}  # key -> date string ("YYYY-MM-DD")
        self._running = False
        self._stats = {
            "frames_processed": 0,
            "faces_detected": 0,
            "matches_found": 0,
            "last_sync": None,
            "last_frame": None,
            "started_at": None,
        }

    @property
    def stats(self) -> dict:
        return {**self._stats, "running": self._running}

    def _ist_now(self) -> datetime:
        return datetime.now(IST)

    def _is_in_window(self) -> bool:
        """Check if current IST time is within the attendance window."""
        now = self._ist_now()
        start = now.replace(
            hour=self.cfg["attendance_start_hour"],
            minute=self.cfg["attendance_start_minute"],
            second=0,
            microsecond=0,
        )
        end = now.replace(
            hour=self.cfg["attendance_end_hour"],
            minute=self.cfg["attendance_end_minute"],
            second=0,
            microsecond=0,
        )
        return start <= now <= end

    def _is_already_marked_today(self, key: str) -> bool:
        """Check if this person has already been marked present today."""
        today = self._ist_now().strftime("%Y-%m-%d")
        marked_date = self._daily_marked.get(key)
        if marked_date != today:
            # New day or never marked — clear stale entries on day change
            if marked_date is not None and marked_date != today:
                self._daily_marked.pop(key, None)
            return False
        return True

    async def sync_registrations(self):
        """Pull new face registrations from cloud and generate embeddings."""
        logger.info("Syncing registrations from cloud...")
        pending = await self.cloud.pull_pending_registrations()

        if not pending:
            logger.info("No pending registrations")
            return

        for reg in pending:
            reg_id = reg["id"]
            name = reg["name"]
            phone = reg.get("phone", "")

            # Download face image
            image_path = await self.cloud.download_face_image(reg_id, name)
            if not image_path:
                logger.error(f"Failed to download image for {name} (reg {reg_id})")
                continue

            # Extract embedding
            embedding = extract_embedding(image_path)
            if embedding is None:
                logger.error(f"Failed to extract embedding for {name}")
                continue

            # Store embedding keyed by reg_id (unique per registration)
            key = str(reg_id)
            self.known_embeddings[key] = {
                "name": name,
                "phone": phone,
                "reg_id": reg_id,
                "embedding": embedding,
            }

            # Mark as synced on cloud
            await self.cloud.mark_synced(reg_id)
            logger.info(f"Synced registration: {name} (phone: {phone})")

        # Save embeddings to disk
        self.cloud.save_embeddings(self.known_embeddings)
        self._stats["last_sync"] = self._ist_now().strftime("%d-%m-%Y %H:%M:%S IST")
        logger.info(
            f"Sync complete. Total known faces: {len(self.known_embeddings)}"
        )

    async def process_frame(self, camera_name: str, frame: np.ndarray):
        """Process a single camera frame for face recognition."""
        self._stats["frames_processed"] += 1
        self._stats["last_frame"] = self._ist_now().strftime("%H:%M:%S IST")

        # Detect faces
        faces = detect_faces_in_frame(frame)
        if not faces:
            return

        self._stats["faces_detected"] += len(faces)

        # Match each detected face
        threshold = self.cfg["recognition_threshold"]
        for face_info in faces:
            matched_key, confidence = match_face(
                face_info["embedding"],
                self.known_embeddings,
                threshold=threshold,
            )

            if matched_key is None:
                continue

            match_data = self.known_embeddings[matched_key]
            name = match_data["name"]

            if self._is_already_marked_today(matched_key):
                continue

            # Attendance match found — mark for today (no repeat notification)
            self._daily_marked[matched_key] = self._ist_now().strftime("%Y-%m-%d")
            self._stats["matches_found"] += 1

            now = self._ist_now()
            date_str = now.strftime("%d-%m-%Y")
            time_str = now.strftime("%I:%M %p IST")

            logger.info(
                f"ATTENDANCE: {name} recognized at {camera_name} "
                f"(confidence: {confidence:.2f}) at {time_str}"
            )

            # Save snapshot
            try:
                snap_name = f"{name.replace(' ', '_')}_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
                snap_path = SNAPSHOTS_DIR / snap_name
                cv2.imwrite(str(snap_path), frame)
            except Exception as e:
                logger.error(f"Snapshot save error: {e}")

            # Push attendance to cloud (triggers WhatsApp notification)
            phone = match_data.get("phone", "")
            if phone:
                await self.cloud.push_attendance(
                    staff_name=name,
                    phone=phone,
                    date=date_str,
                    time=time_str,
                )

    async def run(self):
        """Main engine loop."""
        self._running = True
        self._stats["started_at"] = self._ist_now().strftime(
            "%d-%m-%Y %H:%M:%S IST"
        )

        # Load saved embeddings
        self.known_embeddings = self.cloud.load_embeddings()
        logger.info(f"Loaded {len(self.known_embeddings)} known face(s)")

        # Connect cameras
        self.camera.connect_all()
        logger.info(
            f"Connected to {self.camera.connected_count}/{len(self.camera.cameras)} camera(s)"
        )

        # Initial sync
        await self.sync_registrations()

        sync_interval = self.cfg["sync_interval_seconds"]
        snap_interval = self.cfg["snapshot_interval_seconds"]
        last_sync = time.time()
        last_log_push = time.time()
        log_push_interval = 60  # push logs to cloud every 60 seconds

        # Install cloud log handler on root logger
        cloud_handler = CloudLogHandler(maxlen=500)
        cloud_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(cloud_handler)

        logger.info("=" * 60)
        logger.info("OFFICE ATTENDANCE ENGINE STARTED")
        logger.info(f"Cloud: {self.cfg['cloud_url']}")
        logger.info(f"Cameras: {self.camera.camera_names}")
        logger.info(f"Known faces: {len(self.known_embeddings)}")
        logger.info(f"Sync interval: {sync_interval}s")
        logger.info(f"Recognition threshold: {self.cfg['recognition_threshold']}")
        logger.info("=" * 60)

        _frame_log_counter = 0
        _frame_log_interval = 60  # log stats every N frames

        try:
            while self._running:
                # Periodic sync
                if time.time() - last_sync >= sync_interval:
                    await self.sync_registrations()
                    last_sync = time.time()

                # Only process during attendance window (or always if window is 0-0)
                in_window = self._is_in_window() or (
                    self.cfg["attendance_start_hour"] == 0
                    and self.cfg["attendance_end_hour"] == 0
                )
                if in_window:
                    # Grab frames from all cameras
                    frames = self.camera.grab_all_frames()
                    for camera_name, frame in frames:
                        await self.process_frame(camera_name, frame)

                    _frame_log_counter += 1
                    if _frame_log_counter % _frame_log_interval == 0:
                        logger.info(
                            f"Stats: {self._stats['frames_processed']} frames, "
                            f"{self._stats['faces_detected']} faces detected, "
                            f"{self._stats['matches_found']} matches"
                        )
                elif _frame_log_counter == 0:
                    logger.info(
                        f"Outside attendance window "
                        f"({self.cfg['attendance_start_hour']:02d}:00-"
                        f"{self.cfg['attendance_end_hour']:02d}:00 IST), "
                        f"current: {self._ist_now().strftime('%H:%M IST')}"
                    )
                    _frame_log_counter = 1  # only log once

                # Periodic log push to cloud
                if time.time() - last_log_push >= log_push_interval:
                    lines = cloud_handler.drain()
                    if lines:
                        success = await self.cloud.push_logs(lines)
                        if not success:
                            for line in lines:
                                cloud_handler.buffer.append(line)
                    last_log_push = time.time()

                await asyncio.sleep(snap_interval)

        except asyncio.CancelledError:
            logger.info("Engine cancelled")
        except KeyboardInterrupt:
            logger.info("Engine stopped by user")
        finally:
            self._running = False
            self.camera.release_all()
            root_logger.removeHandler(cloud_handler)
            logger.info("Engine stopped")

    def stop(self):
        """Signal the engine to stop."""
        self._running = False
