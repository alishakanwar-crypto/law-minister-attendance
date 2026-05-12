"""
Camera feed capture module.

Supports multiple camera types:
- RTSP streams (any IP camera)
- Hikvision ISAPI (snapshot-based)
- USB/Webcam (local device)
- Static image URL (for testing)
"""

import io
import logging
import time

import httpx
import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger("attendance.camera")


def capture_rtsp(url: str) -> bytes | None:
    """Capture a single frame from an RTSP stream."""
    if not CV2_AVAILABLE:
        logger.error("OpenCV not available for RTSP capture")
        return None
    try:
        cap = cv2.VideoCapture(url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            logger.warning(f"Failed to capture frame from {url}")
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes()
    except Exception as e:
        logger.error(f"RTSP capture error: {e}")
        return None


def capture_hikvision(ip: str, port: int, username: str, password: str,
                      channel: int = 1) -> bytes | None:
    """Capture a snapshot via Hikvision ISAPI."""
    url = f"http://{ip}:{port}/ISAPI/Streaming/channels/{channel}01/picture"
    try:
        resp = httpx.get(url, auth=(username, password), timeout=10)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        logger.warning(f"Hikvision snapshot failed: HTTP {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"Hikvision capture error: {e}")
        return None


def capture_webcam(device_index: int = 0) -> bytes | None:
    """Capture a frame from a local webcam."""
    if not CV2_AVAILABLE:
        logger.error("OpenCV not available for webcam capture")
        return None
    try:
        cap = cv2.VideoCapture(device_index)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            logger.warning(f"Failed to capture from webcam {device_index}")
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes()
    except Exception as e:
        logger.error(f"Webcam capture error: {e}")
        return None


def capture_url(url: str) -> bytes | None:
    """Capture an image from a URL (for testing)."""
    try:
        resp = httpx.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception as e:
        logger.error(f"URL capture error: {e}")
        return None


def capture_from_camera(camera_config: dict) -> bytes | None:
    """Capture a frame based on camera configuration.

    camera_config keys:
        source_type: 'rtsp' | 'hikvision' | 'webcam' | 'url'
        source_url: URL for rtsp/url types
        ip, port, username, password, channel: for hikvision
    """
    source_type = camera_config.get("source_type", "rtsp")

    if source_type == "rtsp":
        url = camera_config.get("source_url", "")
        if not url:
            ip = camera_config.get("ip", "")
            port = camera_config.get("port", 554)
            username = camera_config.get("username", "")
            password = camera_config.get("password", "")
            channel = camera_config.get("channel", 1)
            if username and password:
                url = f"rtsp://{username}:{password}@{ip}:{port}/Streaming/channels/{channel}01"
            else:
                url = f"rtsp://{ip}:{port}/Streaming/channels/{channel}01"
        return capture_rtsp(url)

    elif source_type == "hikvision":
        return capture_hikvision(
            ip=camera_config.get("ip", ""),
            port=camera_config.get("port", 80),
            username=camera_config.get("username", "admin"),
            password=camera_config.get("password", ""),
            channel=camera_config.get("channel", 1),
        )

    elif source_type == "webcam":
        device = int(camera_config.get("source_url", "0"))
        return capture_webcam(device)

    elif source_type == "url":
        return capture_url(camera_config.get("source_url", ""))

    else:
        logger.error(f"Unknown camera source type: {source_type}")
        return None
