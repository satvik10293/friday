"""
core/services/learning_service.py — FRIDAY V3 (M16 → completed)

LearningService records raw experience AND consolidates recurring experience into
durable, persisted **lessons** — closing the flywheel the Learning Brain used to
leave open (it noticed patterns but nothing was kept or reusable).

    record()/samples()  — the raw experience buffer (unchanged API)
    learn()/lessons()   — the flywheel: a pattern seen enough times becomes a
                          lesson that survives restarts and can be recalled to
                          inform future behaviour

Lessons persist to a small JSON file (data/learning_lessons.json by default;
inject `path` for tests). Every method is side-effect-safe and never raises on
the hot path — a coordinator tick must never fail because learning stumbled.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.services.learning")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STORE = _ROOT / "data" / "learning_lessons.json"


class LearningService:
    name = "learning"

    def __init__(self, *, buffer: int = 2000, path: Optional[Path] = None,
                 persist: bool = True) -> None:
        self._buffer: deque = deque(maxlen=buffer)
        self._lock = threading.Lock()
        self._path: Optional[Path] = ((Path(path) if path is not None else _DEFAULT_STORE)
                                      if persist else None)
        self._lessons: dict = {}
        self._load()

    # ── raw experience (unchanged API) ─────────────────────────────────────────
    def record(self, kind: str, data) -> None:
        self._buffer.append({"kind": kind, "data": data, "ts": time.time()})

    def samples(self, *, kind: str = "", limit: int = 100) -> list:
        items = [s for s in self._buffer if not kind or s["kind"] == kind]
        return items[-limit:][::-1]

    # ── the flywheel: recurring experience → durable, recallable lessons ───────
    def learn(self, pattern: str, *, kind: str = "", category: str = "",
              meta: Optional[dict] = None) -> dict:
        """Record or reinforce the lesson for `pattern`. Returns the lesson dict
        with an extra `new` flag (True the first time this pattern is learned).
        Persists immediately. Never raises."""
        now = time.time()
        with self._lock:
            lesson = self._lessons.get(pattern)
            new = lesson is None
            if new:
                lesson = {"pattern": pattern, "kind": kind, "category": category,
                          "reinforcement": 0, "first_learned": now,
                          "last_reinforced": now, "meta": {}}
                self._lessons[pattern] = lesson
            lesson["reinforcement"] += 1
            lesson["last_reinforced"] = now
            if meta:
                lesson["meta"].update(meta)
            self._save()
            out = dict(lesson)
        out["new"] = new
        return out

    def lessons(self, *, min_reinforcement: int = 1, limit: int = 100) -> list:
        """Learned lessons, strongest first — the recallable output of learning."""
        with self._lock:
            items = [dict(v) for v in self._lessons.values()
                     if v.get("reinforcement", 0) >= min_reinforcement]
        items.sort(key=lambda lesson: (lesson["reinforcement"], lesson["last_reinforced"]),
                   reverse=True)
        return items[:limit]

    def health(self) -> dict:
        return {"status": "ok", "buffered": len(self._buffer),
                "lessons": len(self._lessons)}

    # ── persistence (never raises) ─────────────────────────────────────────────
    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._lessons = {str(k): v for k, v in data.items()
                                 if isinstance(v, dict)}
        except (OSError, ValueError):
            log.debug("learning store unreadable at %s — starting empty", self._path)

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._lessons, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.debug("learning store not writable at %s — lessons stay in memory",
                      self._path)
