"""Camera reader — captures frames from RTSP / IP cameras / webcam."""

import logging
import os
import re
import time
from urllib.parse import quote, unquote

import cv2
import numpy as np

logger = logging.getLogger("office_engine.camera_reader")

# Force FFmpeg to use TCP for RTSP (more reliable) with a 15-second timeout.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|stimeout;15000000"
)


def _strip_credentials(url: str) -> str:
    """Remove user:pass@ from an RTSP URL (for anonymous access attempt)."""
    return re.sub(r"^(rtsps?://)([^@]+)@", r"\1", url)


def prepare_rtsp_url(url: str) -> str:
    """Encode special characters in the password portion of an RTSP URL.

    Passwords like ``PPIS@123`` contain ``@`` which collides with the
    ``user:pass@host`` delimiter.  This function finds the credentials,
    decodes any existing percent-encoding, then re-encodes so that
    FFmpeg / OpenCV can parse the URL unambiguously.
    """
    m = re.match(
        r"^(rtsps?://)([^:]+):(.+)@(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?.*)$",
        url,
    )
    if not m:
        return url
    scheme, user, raw_pw, rest = m.group(1), m.group(2), m.group(3), m.group(4)
    decoded_pw = unquote(raw_pw)
    encoded_pw = quote(decoded_pw, safe="")
    return f"{scheme}{user}:{encoded_pw}@{rest}"


class CameraReader:
    """Manages camera connections and frame capture."""

    def __init__(self, cameras: list[dict]):
        self.cameras = [c for c in cameras if c.get("enabled", True)]
        self._captures: dict[str, cv2.VideoCapture] = {}
        self._retry_at: dict[str, float] = {}
        self._retry_delay: dict[str, int] = {}
        self._base_retry = 60  # initial retry delay (seconds)
        self._max_retry = 600  # max retry delay (10 minutes)

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
            return self._try_open(name, source)

        # For RTSP cameras, try multiple connection strategies to handle
        # NVRs that have issues with percent-encoded passwords (#→%23).
        if url.startswith("rtsp"):
            strategies = [
                ("with-creds", prepare_rtsp_url(url)),
                ("anonymous", _strip_credentials(url)),
            ]
            for strategy_name, source in strategies:
                logger.info(
                    f"Trying camera {name} ({strategy_name})..."
                )
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    self._captures[name] = cap
                    self._retry_at.pop(name, None)
                    self._retry_delay.pop(name, None)
                    logger.info(
                        f"Connected to camera: {name} ({strategy_name})"
                    )
                    return True
                cap.release()

            delay = self._retry_delay.get(name, self._base_retry)
            logger.error(
                f"Failed to open camera: {name} — all strategies failed, "
                f"retrying in {delay}s"
            )
            self._retry_at[name] = time.time() + delay
            self._retry_delay[name] = min(delay * 2, self._max_retry)
            return False

        return self._try_open(name, url)

    def _try_open(self, name: str, source) -> bool:
        """Attempt to open a single video source."""
        try:
            if isinstance(source, str):
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            else:
                cap = cv2.VideoCapture(source)
            if cap.isOpened():
                self._captures[name] = cap
                self._retry_at.pop(name, None)
                self._retry_delay.pop(name, None)
                logger.info(f"Connected to camera: {name}")
                return True
            else:
                delay = self._retry_delay.get(name, self._base_retry)
                logger.error(
                    f"Failed to open camera: {name} ({source}) — "
                    f"retrying in {delay}s"
                )
                self._retry_at[name] = time.time() + delay
                self._retry_delay[name] = min(delay * 2, self._max_retry)
                return False
        except Exception as e:
            delay = self._retry_delay.get(name, self._base_retry)
            logger.error(f"Camera connection error for {name}: {e}")
            self._retry_at[name] = time.time() + delay
            self._retry_delay[name] = min(delay * 2, self._max_retry)
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
                    self._retry_at[camera_name] = time.time() + self._base_retry
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
