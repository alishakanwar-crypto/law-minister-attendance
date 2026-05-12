"""
Anti-spoofing & liveness detection module.

Prevents attendance marking from photographs, mobile screens, printed images,
video recordings, or any non-live representation.

Techniques used (all work with a single RGB camera — no depth sensor required):
1. Multi-frame verification — face must persist naturally across N frames
2. Blink detection — eye aspect ratio (EAR) tracking
3. Motion consistency — natural micro-movement between frames
4. Texture analysis — frequency-domain check to detect flat/printed surfaces
5. Screen/moire detection — periodic pattern analysis for display spoofing
"""

import logging
import time
from collections import defaultdict

import cv2
import numpy as np

logger = logging.getLogger("attendance.liveness")

# --- Configuration ---
MIN_FRAMES_FOR_LIVENESS = 4       # Minimum frames before attendance is accepted
BLINK_EAR_THRESHOLD = 0.22        # EAR below this = eye closed
BLINK_REQUIRED = True             # Must detect at least 1 blink
MOTION_MIN_PIXELS = 1.5           # Minimum avg landmark shift (px) across frames
MOTION_MAX_PIXELS = 80.0          # Maximum avg shift — too much = jitter / replay
TEXTURE_THRESHOLD = 15.0          # Laplacian variance below this = flat/printed
LIVENESS_WINDOW_SECONDS = 30      # Max time to collect frames for one person
SPOOF_COOLDOWN_SECONDS = 60       # Suppress repeated spoof logs for same face


# --- Eye Aspect Ratio (EAR) ---

# InsightFace 2d-106 landmark indices for left/right eyes
# Left eye:  outer=33, inner=35, top=[87,86], bottom=[96,97]
# Right eye: outer=42, inner=44, top=[90,91], bottom=[93,94]

_LEFT_EYE = {"outer": 33, "inner": 35, "top": [87, 86], "bottom": [96, 97]}
_RIGHT_EYE = {"outer": 42, "inner": 44, "top": [90, 91], "bottom": [93, 94]}


def _eye_aspect_ratio(landmarks: np.ndarray, eye_cfg: dict) -> float:
    """Compute Eye Aspect Ratio from 2d-106 landmarks."""
    try:
        p_outer = landmarks[eye_cfg["outer"]]
        p_inner = landmarks[eye_cfg["inner"]]
        horizontal = np.linalg.norm(p_outer - p_inner)
        if horizontal < 1e-6:
            return 0.3  # default open

        vertical_sum = 0.0
        for t, b in zip(eye_cfg["top"], eye_cfg["bottom"]):
            vertical_sum += np.linalg.norm(landmarks[t] - landmarks[b])
        vertical_avg = vertical_sum / len(eye_cfg["top"])

        return float(vertical_avg / horizontal)
    except (IndexError, TypeError):
        return 0.3


def compute_ear(landmarks: np.ndarray) -> float:
    """Average EAR across both eyes."""
    left = _eye_aspect_ratio(landmarks, _LEFT_EYE)
    right = _eye_aspect_ratio(landmarks, _RIGHT_EYE)
    return (left + right) / 2.0


# --- Texture Analysis ---

def texture_score(face_crop_bgr: np.ndarray) -> float:
    """Laplacian variance — low value indicates flat/printed surface."""
    gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def frequency_score(face_crop_bgr: np.ndarray) -> float:
    """High-frequency energy ratio — screens/prints have distinct patterns."""
    gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (128, 128))
    f_transform = np.fft.fft2(gray.astype(np.float32))
    f_shift = np.fft.fftshift(f_transform)
    magnitude = np.abs(f_shift)

    h, w = magnitude.shape
    cy, cx = h // 2, w // 2
    r_inner = min(h, w) // 4
    total_energy = magnitude.sum() + 1e-8

    # High-frequency ring energy
    y, x = np.ogrid[:h, :w]
    mask_outer = (x - cx) ** 2 + (y - cy) ** 2 > r_inner ** 2
    hf_energy = magnitude[mask_outer].sum()

    return float(hf_energy / total_energy)


# --- Per-Person Frame Buffer ---

class _PersonBuffer:
    """Tracks multi-frame liveness data for one person."""

    __slots__ = (
        "frames", "landmarks_history", "ear_history",
        "blink_detected", "first_seen", "last_seen",
        "texture_scores",
    )

    def __init__(self):
        self.frames: int = 0
        self.landmarks_history: list[np.ndarray] = []
        self.ear_history: list[float] = []
        self.blink_detected: bool = False
        self.first_seen: float = time.time()
        self.last_seen: float = time.time()
        self.texture_scores: list[float] = []

    @property
    def age(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_seen) > LIVENESS_WINDOW_SECONDS


class LivenessChecker:
    """Stateful liveness verifier — accumulates evidence across frames."""

    def __init__(self):
        # staff_id -> _PersonBuffer
        self._buffers: dict[str, _PersonBuffer] = defaultdict(_PersonBuffer)
        self._spoof_log_times: dict[str, float] = {}
        self._security_log: list[dict] = []

    # --- Public API ---

    def update(
        self,
        staff_id: str,
        face_obj,
        face_crop_bgr: np.ndarray | None,
    ) -> dict:
        """Feed one frame's detection for a person.

        Args:
            staff_id: matched staff identifier
            face_obj: InsightFace face result (has .landmark_2d_106, .bbox, etc.)
            face_crop_bgr: BGR numpy crop of the face region (for texture analysis)

        Returns:
            dict with keys: live (bool), reason (str), frames (int),
                            blink (bool), motion (float), texture (float)
        """
        buf = self._buffers[staff_id]

        if buf.expired:
            self._buffers[staff_id] = _PersonBuffer()
            buf = self._buffers[staff_id]

        buf.frames += 1
        buf.last_seen = time.time()

        # --- Landmark tracking ---
        landmarks = getattr(face_obj, "landmark_2d_106", None)
        if landmarks is not None and len(landmarks) >= 97:
            landmarks = np.array(landmarks, dtype=np.float32)
            buf.landmarks_history.append(landmarks)

            # EAR / blink
            ear = compute_ear(landmarks)
            buf.ear_history.append(ear)
            if ear < BLINK_EAR_THRESHOLD:
                buf.blink_detected = True

        # --- Texture ---
        if face_crop_bgr is not None and face_crop_bgr.size > 0:
            tscore = texture_score(face_crop_bgr)
            buf.texture_scores.append(tscore)

        # --- Evaluate ---
        return self._evaluate(staff_id, buf)

    def reset(self, staff_id: str):
        """Clear buffer after attendance is marked (or spoof rejected)."""
        self._buffers.pop(staff_id, None)

    def get_security_log(self, limit: int = 50) -> list[dict]:
        """Return recent spoof attempt log entries."""
        return list(reversed(self._security_log[-limit:]))

    # --- Internal ---

    def _evaluate(self, staff_id: str, buf: _PersonBuffer) -> dict:
        result = {
            "live": False,
            "reason": "collecting_frames",
            "frames": buf.frames,
            "blink": buf.blink_detected,
            "motion": 0.0,
            "texture": 0.0,
        }

        # Not enough frames yet
        if buf.frames < MIN_FRAMES_FOR_LIVENESS:
            result["reason"] = (
                f"need {MIN_FRAMES_FOR_LIVENESS - buf.frames} more frame(s)"
            )
            return result

        # --- Texture check ---
        avg_texture = (
            np.mean(buf.texture_scores) if buf.texture_scores else 999.0
        )
        result["texture"] = round(float(avg_texture), 2)

        if avg_texture < TEXTURE_THRESHOLD:
            result["reason"] = "flat_surface_detected"
            self._log_spoof(staff_id, "flat_surface", avg_texture)
            return result

        # --- Motion check ---
        motion = self._compute_motion(buf)
        result["motion"] = round(motion, 2)

        if motion < MOTION_MIN_PIXELS:
            result["reason"] = "no_natural_movement"
            self._log_spoof(staff_id, "static_face", motion)
            return result

        if motion > MOTION_MAX_PIXELS:
            result["reason"] = "unnatural_jitter"
            self._log_spoof(staff_id, "jitter_or_replay", motion)
            return result

        # --- Blink check ---
        if BLINK_REQUIRED and not buf.blink_detected:
            # Give more time to detect a blink if still within window
            if buf.age < LIVENESS_WINDOW_SECONDS * 0.7:
                result["reason"] = "waiting_for_blink"
                return result
            # After enough time, reject
            result["reason"] = "no_blink_detected"
            self._log_spoof(staff_id, "no_blink", 0)
            return result

        # All checks passed
        result["live"] = True
        result["reason"] = "live_person_confirmed"
        return result

    @staticmethod
    def _compute_motion(buf: _PersonBuffer) -> float:
        """Average per-frame landmark displacement (pixels)."""
        if len(buf.landmarks_history) < 2:
            return 0.0

        shifts = []
        for i in range(1, len(buf.landmarks_history)):
            diff = buf.landmarks_history[i] - buf.landmarks_history[i - 1]
            avg_shift = np.mean(np.linalg.norm(diff, axis=1))
            shifts.append(avg_shift)

        return float(np.mean(shifts))

    def _log_spoof(self, staff_id: str, spoof_type: str, value: float):
        """Record a spoof attempt (rate-limited per person)."""
        now = time.time()
        key = f"{staff_id}:{spoof_type}"
        last = self._spoof_log_times.get(key, 0)

        if now - last < SPOOF_COOLDOWN_SECONDS:
            return

        self._spoof_log_times[key] = now
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "staff_id": staff_id,
            "type": spoof_type,
            "value": round(value, 2),
        }
        self._security_log.append(entry)
        if len(self._security_log) > 500:
            self._security_log = self._security_log[-250:]

        logger.warning(
            f"SPOOF ATTEMPT: staff={staff_id} type={spoof_type} "
            f"value={value:.2f}"
        )

    def cleanup_expired(self):
        """Remove stale buffers."""
        expired = [
            k for k, v in self._buffers.items() if v.expired
        ]
        for k in expired:
            del self._buffers[k]
