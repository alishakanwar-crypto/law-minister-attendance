"""
Face recognition engine using InsightFace (512-d ArcFace embeddings).

Handles:
- Face detection and encoding from images
- Face matching against registered staff
- Confidence scoring with cosine similarity
"""

import io
import logging
import time
from pathlib import Path

import numpy as np

try:
    from PIL import Image, ImageEnhance
except ImportError:
    Image = None
    ImageEnhance = None

try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    FaceAnalysis = None
    INSIGHTFACE_AVAILABLE = False

from backend import database as db

logger = logging.getLogger("attendance.face_engine")

FACE_IMAGES_DIR = Path(__file__).parent.parent / "face_images"
FACE_IMAGES_DIR.mkdir(exist_ok=True)

_insight_app = None


def get_insightface_app():
    """Lazily initialize and return a shared InsightFace FaceAnalysis instance."""
    global _insight_app
    if not INSIGHTFACE_AVAILABLE:
        logger.error("InsightFace is not installed")
        return None
    if _insight_app is None:
        try:
            app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
            _insight_app = app
            logger.info("InsightFace engine initialized (buffalo_l, CPU)")
        except Exception as e:
            logger.error(f"InsightFace init failed: {e}")
            return None
    return _insight_app


def preprocess_image(image_bytes: bytes) -> bytes:
    """Enhance image quality for better face recognition."""
    if Image is None or ImageEnhance is None:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        min_dim = 1280
        if img.width < min_dim and img.height < min_dim:
            scale = min_dim / min(img.width, img.height)
            new_w = int(img.width * scale)
            new_h = int(img.height * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.5)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.1)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    except Exception:
        return image_bytes


def detect_and_encode(image_bytes: bytes) -> list[tuple[np.ndarray, bytes, list[int]]]:
    """Detect all faces in an image and return their embeddings.

    Returns list of (embedding_512d, cropped_face_jpeg, bbox_xyxy).
    """
    app = get_insightface_app()
    if app is None:
        return []

    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.asarray(pil_img, dtype=np.uint8)
        if img_array.ndim != 3 or img_array.shape[2] != 3:
            logger.error(f"Bad image shape: {img_array.shape}")
            return []
        img_bgr = img_array[:, :, ::-1].copy()
    except Exception as e:
        logger.error(f"Failed to load image: {e}")
        return []

    faces = app.get(img_bgr)
    if not faces:
        return []

    results = []
    for face in faces:
        embedding = face.normed_embedding
        bbox = face.bbox.astype(int).tolist()
        x1, y1, x2, y2 = bbox

        h, w = img_array.shape[:2]
        pad_x = int((x2 - x1) * 0.3)
        pad_y = int((y2 - y1) * 0.3)
        cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
        cx2, cy2 = min(w, x2 + pad_x), min(h, y2 + pad_y)

        face_crop = img_array[cy1:cy2, cx1:cx2]
        pil_crop = Image.fromarray(face_crop)
        buf = io.BytesIO()
        pil_crop.save(buf, format="JPEG", quality=85)
        cropped_bytes = buf.getvalue()

        results.append((embedding, cropped_bytes, bbox))

    return results


def encode_single_face(image_bytes: bytes) -> tuple[np.ndarray, bytes] | None:
    """Detect a single face (largest) and return its embedding.

    Returns (embedding_512d, cropped_face_jpeg) or None.
    """
    results = detect_and_encode(image_bytes)
    if not results:
        return None

    if len(results) > 1:
        logger.info(f"Multiple faces ({len(results)}), using largest")
        results.sort(
            key=lambda r: (r[2][2] - r[2][0]) * (r[2][3] - r[2][1]),
            reverse=True,
        )

    return results[0][0], results[0][1]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two embeddings."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def match_face(embedding: np.ndarray, threshold: float = 0.45) -> tuple[str, str, float] | None:
    """Match an embedding against registered staff faces.

    Returns (staff_id, name, confidence) or None if no match above threshold.
    """
    rows = db.get_face_encodings(encoding_type="insightface_512d")
    if not rows:
        return None

    best_match = None
    best_score = -1.0

    for row in rows:
        stored = np.frombuffer(row["encoding"], dtype=np.float32)
        if stored.shape[0] != 512:
            continue
        score = cosine_similarity(embedding, stored)
        if score > best_score:
            best_score = score
            best_match = row

    if best_match is not None and best_score >= threshold:
        return best_match["staff_id"], best_match["name"], best_score

    return None


def register_staff_face(staff_id: str, image_bytes: bytes,
                        angle: str = "front") -> dict:
    """Register a face for a staff member.

    Returns dict with registration result.
    """
    result = encode_single_face(image_bytes)
    if result is None:
        return {"success": False, "error": "No face detected in image"}

    embedding, cropped_face = result

    ts = int(time.time())
    filename = f"{staff_id}_{angle}_{ts}.jpg"
    filepath = FACE_IMAGES_DIR / filename
    with open(filepath, "wb") as f:
        f.write(cropped_face)

    encoding_bytes = embedding.astype(np.float32).tobytes()
    fid = db.save_face_encoding(
        staff_id=staff_id,
        angle=angle,
        encoding_bytes=encoding_bytes,
        image_path=str(filepath),
        encoding_type="insightface_512d",
    )

    logger.info(f"Registered face for {staff_id} (angle={angle}), id={fid}")
    return {
        "success": True,
        "face_id": fid,
        "staff_id": staff_id,
        "angle": angle,
        "image_file": filename,
    }


def load_known_faces() -> dict[str, dict]:
    """Load all registered face encodings into memory.

    Returns dict: staff_id -> {name, designation, encodings: [np.array, ...]}.
    """
    rows = db.get_face_encodings(encoding_type="insightface_512d")
    persons: dict = {}

    for row in rows:
        sid = row["staff_id"]
        encoding = np.frombuffer(row["encoding"], dtype=np.float32)

        if sid not in persons:
            persons[sid] = {
                "name": row["name"],
                "designation": row.get("designation", ""),
                "encodings": [],
            }
        persons[sid]["encodings"].append(encoding)

    return persons
