"""Camera reader — captures frames from RTSP / IP cameras / webcam."""

import logging
import time

import cv2
import numpy as np

logger = logging.getLogger("office_engine.camera_reader")


class CameraReader:
    """Manages camera connections and frame capture."""

    def __init__(self, cameras: list[dict]):
        self.cameras = [c for c in cameras if c.get("enabled", True)]
        self._captures: dict[str, cv2.VideoCapture] = {}
        self._retry_at: dict[str, float] = {}
        self._retry_delay = 30  # seconds before retry after failure

    def connect_all(self):
        """Connect to all configured cameras."""
        for cam in self.cameras:
            name = cam["name"]
            self._connect_camera(cam)

    def _connect_camera(self, cam: dict) -> bool:
        name = cam["name"]
        cam_type = cam.get("type", "rtsp")
        url = cam.get("url", "")

        if cam_type == "webcam":
            source = cam.get("device_id", 0)
        else:
            source = url

        try:
            cap = cv2.VideoCapture(source)
            if cap.isOpened():
                self._captures[name] = cap
                self._retry_at.pop(name, None)
                logger.info(f"Connected to camera: {name}")
                return True
            else:
                logger.error(f"Failed to open camera: {name} ({source})")
                self._retry_at[name] = time.time() + self._retry_delay
                return False
        except Exception as e:
            logger.error(f"Camera connection error for {name}: {e}")
            self._retry_at[name] = time.time() + self._retry_delay
            return False

    def grab_frame(self, camera_name: str) -> np.ndarray | None:
        """Grab a single frame from a named camera."""
        cap = self._captures.get(camera_name)
        if cap is None:
            # Check if we should retry
            cam = next((c for c in self.cameras if c["name"] == camera_name), None)
            if cam and time.time() >= self._retry_at.get(camera_name, 0):
                if self._connect_camera(cam):
                    cap = self._captures.get(camera_name)
            if cap is None:
                return None

        try:
            ret, frame = cap.read()
            if ret and frame is not None:
                return frame
            else:
                logger.warning(f"Frame grab failed for {camera_name}, reconnecting...")
                cap.release()
                self._captures.pop(camera_name, None)
                cam = next((c for c in self.cameras if c["name"] == camera_name), None)
                if cam:
                    self._retry_at[camera_name] = time.time() + self._retry_delay
                return None
        except Exception as e:
            logger.error(f"Frame grab error for {camera_name}: {e}")
            return None

    def grab_all_frames(self) -> list[tuple[str, np.ndarray]]:
        """Grab one frame from each connected camera.

        Returns list of (camera_name, frame).
        """
        frames = []
        for cam in self.cameras:
            name = cam["name"]
            frame = self.grab_frame(name)
            if frame is not None:
                frames.append((name, frame))
        return frames

    def release_all(self):
        """Release all camera connections."""
        for name, cap in self._captures.items():
            try:
                cap.release()
            except Exception:
                pass
        self._captures.clear()
        logger.info("All cameras released")

    @property
    def connected_count(self) -> int:
        return len(self._captures)

    @property
    def camera_names(self) -> list[str]:
        return [c["name"] for c in self.cameras]
