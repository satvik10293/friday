"""
core/vision/memory/face_memory.py — she learns and names faces (M64)

The vision stack already has a FaceRecognitionProcessor that matches face crops
against a gallery by cosine similarity — it just needs an EMBEDDER and a gallery.
This provides both, with no extra install:

  · simple_embedding — a grayscale, CLAHE-equalised, L2-normalised 64x64 face
    template. Honest about what it is: solid for telling a few enrolled people
    apart in similar lighting/pose; it is NOT production face-ID.
  · FaceGallery — the enrolled faces, persisted to data/vision/faces.json
    (small + git-syncable, like the object catalog). Enrolment is deferred: the
    UI asks to learn a name, and the eyes loop captures the next clear face.

Vectors live in the JSON so a learned face survives restarts and syncs across
machines.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _ROOT / "data" / "vision" / "faces.json"

_SIZE = 64                                    # face template is 64x64


def simple_embedding(crop) -> np.ndarray:
    """Face crop (BGR or gray ndarray) → a normalised template vector. No model
    download — this is deliberately simple. Never raises."""
    try:
        import cv2
        if crop is None or getattr(crop, "size", 0) == 0:
            return np.zeros(_SIZE * _SIZE, np.float32)
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        g = cv2.resize(g, (_SIZE, _SIZE))
        try:
            g = cv2.createCLAHE(2.0, (8, 8)).apply(g)
        except Exception:  # noqa: BLE001
            pass
        v = g.astype(np.float32).ravel()
        v -= v.mean()
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-6 else v
    except Exception:  # noqa: BLE001
        return np.zeros(_SIZE * _SIZE, np.float32)


class FaceGallery:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._faces: dict = {}                # name -> {vector, enrolled_at, sightings}
        self._pending: Optional[str] = None   # a name awaiting the next clear face
        self._load()

    def _load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self._faces = d.get("faces", {}) or {}
        except (OSError, ValueError):
            self._faces = {}

    def _save_locked(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"faces": self._faces}, indent=2),
                                 encoding="utf-8")
        except OSError:
            pass

    # ── enrolment ────────────────────────────────────────────────────────────────
    def enroll(self, name: str, vector) -> None:
        name = (name or "").strip()
        if not name:
            return
        with self._lock:
            prev = self._faces.get(name, {})
            self._faces[name] = {
                "vector": [float(x) for x in np.asarray(vector, np.float32).ravel()],
                "enrolled_at": prev.get("enrolled_at", time.time()),
                "sightings": int(prev.get("sightings", 0)),
                "last_seen": prev.get("last_seen", 0.0)}
            self._save_locked()

    def request_enroll(self, name: str) -> None:
        with self._lock:
            nm = (name or "").strip()
            self._pending = (nm, time.time()) if nm else None

    def take_pending(self) -> Optional[str]:
        # a queued enrolment that never finds a face within 20s is dropped, so a
        # stale request never latches onto the wrong person later.
        with self._lock:
            p, self._pending = self._pending, None
            if not p:
                return None
            name, ts = p
            return name if (time.time() - ts) <= 20.0 else None

    def note_seen(self, name: str) -> None:
        with self._lock:
            f = self._faces.get(name)
            if f is not None:
                f["sightings"] = int(f.get("sightings", 0)) + 1
                f["last_seen"] = time.time()

    # ── reads ────────────────────────────────────────────────────────────────────
    def vectors(self) -> dict:
        with self._lock:
            return {n: np.asarray(f["vector"], np.float32)
                    for n, f in self._faces.items() if f.get("vector")}

    def names(self) -> list:
        with self._lock:
            return list(self._faces.keys())

    def all(self) -> list:
        with self._lock:
            out = []
            for n, f in self._faces.items():
                out.append({"name": n, "sightings": int(f.get("sightings", 0)),
                            "enrolled_at": f.get("enrolled_at", 0),
                            "last_seen": f.get("last_seen", 0)})
            return out

    def count(self) -> int:
        with self._lock:
            return len(self._faces)


_gallery: Optional[FaceGallery] = None
_glock = threading.Lock()


def get_face_gallery() -> FaceGallery:
    global _gallery
    with _glock:
        if _gallery is None:
            _gallery = FaceGallery()
    return _gallery
