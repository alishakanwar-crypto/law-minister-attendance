"""Face processing — embedding generation and matching using InsightFace."""

import io
import logging
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

logger = logging.getLogger("office_engine.face_processor")

_insight_app = None


def get_insightface_app():
    """Lazily initialize InsightFace."""
    global _insight_app
    if not INSIGHTFACE_AVAILABLE:
        logger.error(
            "InsightFace is not installed. Run: pip install insightface onnxruntime"
        )
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
    """Enhance image for better face recognition."""
    if Image is None or ImageEnhance is None:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        min_dim = 1280
        if img.width < min_dim and img.height < min_dim:
            scale = min_dim / min(img.width, img.height)
            img = img.resize(
                (int(img.width * scale), int(img.height * scale)), Image.LANCZOS
            )
        img = ImageEnhance.Contrast(img).enhance(1.3)
        img = ImageEnhance.Sharpness(img).enhance(1.5)
        img = ImageEnhance.Brightness(img).enhance(1.1)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    except Exception:
        return image_bytes


def extract_embedding(image_path: Path) -> np.ndarray | None:
    """Extract a 512-d ArcFace embedding from an image file."""
    app = get_insightface_app()
    if app is None:
        return None

    try:
        raw = image_path.read_bytes()
        enhanced = preprocess_image(raw)
        img = Image.open(io.BytesIO(enhanced)).convert("RGB")
        img_array = np.array(img)
        img_array = img_array[:, :, ::-1]  # RGB to BGR for InsightFace

        faces = app.get(img_array)
        if not faces:
            logger.warning(f"No face found in {image_path.name}")
            return None

        # Use the largest face
        best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        embedding = best.embedding / np.linalg.norm(best.embedding)
        logger.info(f"Extracted embedding from {image_path.name}")
        return embedding
    except Exception as e:
        logger.error(f"Embedding extraction failed for {image_path.name}: {e}")
        return None


def match_face(
    frame_embedding: np.ndarray,
    known_embeddings: dict,
    threshold: float = 0.45,
) -> tuple[str | None, float]:
    """Match a face embedding against known embeddings.

    known_embeddings is keyed by reg_id (str).
    Returns (reg_id_key, confidence) or (None, 0.0) if no match.
    """
    best_key = None
    best_score = 0.0

    for key, data in known_embeddings.items():
        known_emb = data["embedding"]
        if isinstance(known_emb, list):
            known_emb = np.array(known_emb, dtype=np.float32)
        score = float(np.dot(frame_embedding, known_emb))
        if score > best_score:
            best_score = score
            best_key = key

    if best_score >= threshold:
        return best_key, best_score
    return None, 0.0


def detect_faces_in_frame(frame: np.ndarray) -> list[dict]:
    """Detect all faces in a camera frame and return their embeddings.

    Returns list of {bbox, embedding, det_score}.
    """
    app = get_insightface_app()
    if app is None:
        return []

    try:
        faces = app.get(frame)
        results = []
        for face in faces:
            if face.det_score < 0.5:
                continue
            emb = face.embedding / np.linalg.norm(face.embedding)
            results.append({
                "bbox": face.bbox.tolist(),
                "embedding": emb,
                "det_score": float(face.det_score),
            })
        return results
    except Exception as e:
        logger.error(f"Face detection error: {e}")
        return []
