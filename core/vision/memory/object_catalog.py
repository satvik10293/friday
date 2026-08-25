"""
core/vision/memory/object_catalog.py — FRIDAY's remembered objects (M64)

She shouldn't "recognise" the same laptop a thousand times a minute — she should
TAG it once and REMEMBER it. This is a small, git-syncable catalog (a JSON file,
not the machine-local SQLite visual memory) so the things she has seen can be
committed and synced across machines.

  · dedup by label — one entry per kind of object she has recognised;
  · a stable TAG per object (OBJ-0001, …) assigned on first sighting;
  · first_seen / last_seen / sightings — and "sightings" is DEBOUNCED: staring
    at the same object counts once, not once per frame (re-seeing it after a gap
    is what counts as a new sighting);
  · plain JSON at data/vision/object_catalog.json — small, diffable, syncable.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _ROOT / "data" / "vision" / "object_catalog.json"

# Re-seeing an object after this gap (seconds) counts as a fresh sighting; within
# the gap it's "still the same object", so the count doesn't run away.
_SIGHTING_GAP = 8.0
_SAVE_EVERY = 4.0                     # debounce disk writes


class ObjectCatalog:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._objects: dict = {}      # label -> record
        self._seq = 0
        self._dirty = False
        self._last_save = 0.0
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._objects = data.get("objects", {}) or {}
            self._seq = int(data.get("seq", len(self._objects)))
        except (OSError, ValueError):
            self._objects, self._seq = {}, 0

    def observe(self, label: str, confidence: float = 0.0,
                kind: str = "object") -> str:
        """Record a detection. Returns 'new' the first time she tags an object,
        'sighting' when a debounced re-sighting is counted, else 'seen'."""
        label = (label or "").strip()
        if not label:
            return "seen"
        now = time.time()
        result = "seen"
        with self._lock:
            o = self._objects.get(label)
            if o is None:
                self._seq += 1
                o = {"tag": f"OBJ-{self._seq:04d}", "label": label, "kind": kind,
                     "first_seen": now, "last_seen": now, "sightings": 1,
                     "best_confidence": round(float(confidence), 3)}
                self._objects[label] = o
                self._dirty = True
                result = "new"
            else:
                if now - o.get("last_seen", 0) >= _SIGHTING_GAP:
                    o["sightings"] = int(o.get("sightings", 0)) + 1
                    self._dirty = True
                    result = "sighting"
                o["last_seen"] = now
                if float(confidence) > o.get("best_confidence", 0):
                    o["best_confidence"] = round(float(confidence), 3)
                    self._dirty = True
            self._maybe_save(now)
        return result

    def _maybe_save(self, now: float) -> None:
        if self._dirty and now - self._last_save >= _SAVE_EVERY:
            self._save_locked()

    def _save_locked(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"seq": self._seq, "updated": time.time(),
                       "objects": self._objects}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._dirty = False
            self._last_save = time.time()
        except OSError:
            pass

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._save_locked()

    def all(self) -> list:
        """Every remembered object, newest sighting first."""
        with self._lock:
            return sorted((dict(o) for o in self._objects.values()),
                          key=lambda o: o.get("last_seen", 0), reverse=True)

    def count(self) -> int:
        with self._lock:
            return len(self._objects)


_catalog: Optional[ObjectCatalog] = None
_lock = threading.Lock()


def get_object_catalog() -> ObjectCatalog:
    global _catalog
    with _lock:
        if _catalog is None:
            _catalog = ObjectCatalog()
    return _catalog
