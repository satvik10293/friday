"""
core/intelligence/teacher.py — FRIDAY 5.x (M30)
The temporary teacher: a cloud LLM (Groq) FRIDAY may consult ONLY when her own
local reasoning cannot answer — and every teacher answer is fed back through
the learning gate into her memory, so the next similar question is answered
locally. The teacher is scaffolding, not a brain:

    · consulted after BOTH local passes stay below the confidence threshold
    · config-gated (`teacher.enabled` in friday_config.json) and key-gated
      (GROQ_API_KEY via the gitignored .env) — absent either, FRIDAY gives
      her honest local answer instead
    · every consult is visible in the DecisionLog route ("groq_teacher"),
      keeping the independence metric truthful
    · success is measured by this module becoming unnecessary: as memory
      grows, local confidence rises and teacher_rate falls

Owner-approved exception to the local-only rule (roadmap rule 0: external
LLMs are temporary fallback tools, never the permanent brain).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.infra import friday_secrets  # noqa: F401 — loads .env on import

log = logging.getLogger("friday.intelligence.teacher")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "friday_config.json"
_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_TIMEOUT_S = 12.0

_SYSTEM_PROMPT = (
    "You are the temporary teacher for FRIDAY, a local voice assistant that is "
    "learning to answer on her own. Answer the user's question directly and "
    "accurately in 1-3 short sentences suitable for being spoken aloud. "
    "No markdown, no lists, no preamble.")


@dataclass
class TeacherAnswer:
    ok: bool
    answer: str = ""
    model: str = ""
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class TeacherStats:
    asked: int = 0
    answered: int = 0
    failed: int = 0
    total_latency_ms: float = 0.0

    def snapshot(self) -> dict:
        d = dict(self.__dict__)
        d["avg_latency_ms"] = round(self.total_latency_ms / self.answered, 1) \
            if self.answered else 0.0
        return d


def _teacher_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg.get("teacher") or {}
    except (OSError, ValueError):
        return {}


class GroqTeacher:
    """Thin, guarded client over Groq's OpenAI-compatible chat endpoint."""

    def __init__(self, *, enabled: Optional[bool] = None, model: Optional[str] = None,
                 api_key: Optional[str] = None) -> None:
        cfg = _teacher_config()
        self.enabled = cfg.get("enabled", True) if enabled is None else enabled
        self.model = model or cfg.get("model") or _DEFAULT_MODEL
        self._api_key = os.environ.get("GROQ_API_KEY", "") if api_key is None \
            else api_key
        self.stats = TeacherStats()

    def available(self) -> bool:
        return bool(self.enabled and self._api_key)

    def ask(self, question: str) -> TeacherAnswer:
        """One guarded consult. Never raises — a teacher failure simply means
        FRIDAY falls back to her honest local answer."""
        if not self.available():
            return TeacherAnswer(ok=False, error="teacher unavailable")
        self.stats.asked += 1
        t0 = time.perf_counter()
        try:
            import requests
            resp = requests.post(
                _API_URL,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model,
                      "messages": [{"role": "system", "content": _SYSTEM_PROMPT},
                                   {"role": "user", "content": question}],
                      "temperature": 0.3, "max_tokens": 220},
                timeout=_TIMEOUT_S)
            resp.raise_for_status()
            text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
            latency = (time.perf_counter() - t0) * 1000.0
            if not text:
                self.stats.failed += 1
                return TeacherAnswer(ok=False, error="empty answer",
                                     latency_ms=latency)
            self.stats.answered += 1
            self.stats.total_latency_ms += latency
            return TeacherAnswer(ok=True, answer=text, model=self.model,
                                 latency_ms=latency)
        except Exception as e:  # noqa: BLE001 — the teacher must never break a turn
            self.stats.failed += 1
            log.debug("teacher consult failed", exc_info=True)
            return TeacherAnswer(ok=False, error=str(e),
                                 latency_ms=(time.perf_counter() - t0) * 1000.0)

    def status(self) -> dict:
        return {"enabled": self.enabled, "available": self.available(),
                "model": self.model, **self.stats.snapshot()}


def get_teacher() -> Optional[GroqTeacher]:
    """Build the teacher if it is configured and usable; else None (fully local)."""
    teacher = GroqTeacher()
    return teacher if teacher.available() else None
