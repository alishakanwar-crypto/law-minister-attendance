"""Cloud sync — pulls registrations from cloud, pushes attendance results back."""

import json
import logging
from pathlib import Path

import httpx
import numpy as np

logger = logging.getLogger("office_engine.cloud_sync")


class CloudSync:
    """Handles all communication with the cloud bot API."""

    def __init__(self, cloud_url: str, face_images_dir: Path, embeddings_file: Path):
        self.cloud_url = cloud_url.rstrip("/")
        self.face_images_dir = face_images_dir
        self.embeddings_file = embeddings_file
        self.face_images_dir.mkdir(parents=True, exist_ok=True)

    async def pull_pending_registrations(self) -> list[dict]:
        """Fetch registrations that haven't been synced yet."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.cloud_url}/api/registrations/pending-sync"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    pending = data.get("pending", [])
                    if pending:
                        logger.info(f"Found {len(pending)} pending registration(s)")
                    return pending
                else:
                    logger.error(f"Failed to fetch pending: {resp.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Cloud sync pull error: {e}")
            return []

    async def download_face_image(self, reg_id: int, name: str) -> Path | None:
        """Download a face image from the cloud by registration ID."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.cloud_url}/api/registrations/image/{reg_id}"
                )
                if resp.status_code == 200:
                    safe_name = "".join(
                        c if c.isalnum() or c in " _-" else "_" for c in name
                    ).strip()
                    filename = f"{reg_id}_{safe_name}.jpg"
                    filepath = self.face_images_dir / filename
                    filepath.write_bytes(resp.content)
                    logger.info(f"Downloaded face image: {filepath}")
                    return filepath
                else:
                    logger.error(
                        f"Image download failed for reg {reg_id}: {resp.status_code}"
                    )
                    return None
        except Exception as e:
            logger.error(f"Image download error for reg {reg_id}: {e}")
            return None

    async def mark_synced(self, reg_id: int) -> bool:
        """Mark a registration as synced on the cloud."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/registrations/mark-synced",
                    json={"id": reg_id},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Mark synced error for reg {reg_id}: {e}")
            return False

    async def push_attendance(
        self, staff_name: str, phone: str, date: str = "", time: str = ""
    ) -> bool:
        """Push an attendance result to the cloud for WhatsApp notification."""
        payload = {"staff_name": staff_name, "phone": phone}
        if date:
            payload["date"] = date
        if time:
            payload["time"] = time

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/notify-attendance",
                    json=payload,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    logger.info(
                        f"Attendance pushed: {staff_name} — sent={result.get('sent')}"
                    )
                    return result.get("sent", False)
                else:
                    logger.error(f"Attendance push failed: {resp.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Attendance push error: {e}")
            return False

    def save_embeddings(self, embeddings: dict):
        """Save face embeddings to local file.

        embeddings: {name: {"phone": str, "embedding": list[float], "reg_id": int}}
        """
        serializable = {}
        for name, data in embeddings.items():
            serializable[name] = {
                "phone": data["phone"],
                "reg_id": data.get("reg_id", 0),
                "embedding": (
                    data["embedding"].tolist()
                    if isinstance(data["embedding"], np.ndarray)
                    else data["embedding"]
                ),
            }
        with open(self.embeddings_file, "w") as f:
            json.dump(serializable, f, indent=2)
        logger.info(f"Saved {len(embeddings)} embedding(s) to {self.embeddings_file}")

    def load_embeddings(self) -> dict:
        """Load face embeddings from local file."""
        if not self.embeddings_file.exists():
            return {}
        try:
            with open(self.embeddings_file) as f:
                data = json.load(f)
            embeddings = {}
            for name, info in data.items():
                embeddings[name] = {
                    "phone": info["phone"],
                    "reg_id": info.get("reg_id", 0),
                    "embedding": np.array(info["embedding"], dtype=np.float32),
                }
            logger.info(f"Loaded {len(embeddings)} embedding(s)")
            return embeddings
        except Exception as e:
            logger.error(f"Failed to load embeddings: {e}")
            return {}
