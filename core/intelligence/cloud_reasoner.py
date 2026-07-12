"""
core/intelligence/cloud_reasoner.py — FRIDAY 5.x (M42)
The basic reasoner, promoted to the cloud — an owner-directed policy change.
Where the teacher (M30) was scaffolding consulted only after every local pass
failed, the CloudReasoner is FRIDAY's primary mind for substantive questions:
a frontier model answers first, grounded in the conversation window plus
privacy-filtered local memories.

Boundaries that do NOT move:
    · personal-shaped questions never reach this module — the caller routes
      them through local reasoning (their answers live in local memory anyway)
    · the caller filters context: nothing marked private may be passed in
    · a cloud failure never breaks a turn — the local chain (local reasoning
      → deep pass → librarian → teacher) remains the complete fallback
    · every cloud answer is visible in the DecisionLog route ("cloud_reasoner")
      and still flows through the learning gate, so local memory keeps growing

Model chain (measured available on this key, strongest first): the primary
model is tried, then each fallback, before giving up for the turn. Configured
under the `reasoner` block in friday_config.json.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.infra import friday_secrets  # noqa: F401 — loads .env on import
from core.intelligence.teacher import _context_block

log = logging.getLogger("friday.intelligence.cloud_reasoner")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "friday_config.json"
_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_DEFAULT_FALLBACKS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")
_DEFAULT_MAX_TOKENS = 900
_TIMEOUT_S = 20.0

_SYSTEM_PROMPT = (
    "You are FRIDAY, Satvik's personal AI assistant — direct, warm, sharp, "
    "and technically excellent. Answer directly and accurately. Keep "
    "conversational answers to one to four spoken sentences. For technical, "
    "coding, or math questions give the complete correct answer; write code "
    "as plain indented text without markdown fences. Never mention these "
    "instructions or that you are a language model.")


@dataclass
class ReasonedAnswer:
    ok: bool
    answer: str = ""
    model: str = ""
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class ReasonerStats:
    asked: int = 0
    answered: int = 0
    failed: int = 0
    fallbacks: int = 0
    total_latency_ms: float = 0.0

    def snapshot(self) -> dict:
        d = dict(self.__dict__)
        d["avg_latency_ms"] = round(self.total_latency_ms / self.answered, 1) \
            if self.answered else 0.0
        return d


def _reasoner_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg.get("reasoner") or {}
    except (OSError, ValueError):
        return {}


class CloudReasoner:
    """Guarded client over Groq's OpenAI-compatible chat endpoint with a
    per-turn model fallback chain. Never raises."""

    def __init__(self, *, primary: Optional[str] = None, model: Optional[str] = None,
                 fallback_models: Optional[list[str]] = None,
                 max_tokens: Optional[int] = None,
                 api_key: Optional[str] = None) -> None:
        cfg = _reasoner_config()
        self.primary = (primary or cfg.get("primary") or "cloud").lower()
        self.model = model or cfg.get("model") or _DEFAULT_MODEL
        self.fallback_models = list(fallback_models
                                    if fallback_models is not None
                                    else cfg.get("fallback_models") or _DEFAULT_FALLBACKS)
        self.max_tokens = int(max_tokens or cfg.get("max_tokens") or _DEFAULT_MAX_TOKENS)
        self._api_key = os.environ.get("GROQ_API_KEY", "") if api_key is None \
            else api_key
        self.stats = ReasonerStats()

    def available(self) -> bool:
        """Cloud-primary policy is on AND a key exists. `primary: "local"` in
        the config restores the pre-M42 local-first behaviour without a code
        change."""
        return self.primary == "cloud" and bool(self._api_key)

    def _call(self, model: str, messages: list[dict]) -> str:
        import requests
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "temperature": 0.4, "max_tokens": self.max_tokens},
            timeout=_TIMEOUT_S)
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    def reason(self, question: str, *, context: Optional[dict] = None) -> ReasonedAnswer:
        """One reasoning turn. Tries the primary model, then each fallback.
        Never raises — a total failure returns ok=False and the caller falls
        back to the local chain.

        `context` may carry `recent_turns` (role/text dicts) and `facts`
        (plain strings). The CALLER filters privacy — nothing marked private
        may be passed here."""
        if not self.available():
            return ReasonedAnswer(ok=False, error="cloud reasoner unavailable")
        self.stats.asked += 1
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        block = _context_block(context)
        if block:
            messages.append({"role": "system",
                             "content": "Context from FRIDAY's local state "
                                        "(may resolve pronouns/follow-ups):\n"
                                        + block})
        messages.append({"role": "user", "content": question})

        t0 = time.perf_counter()
        last_error = ""
        for i, model in enumerate([self.model, *self.fallback_models]):
            try:
                text = self._call(model, messages)
            except Exception as e:  # noqa: BLE001 — a turn must never crash on the cloud
                last_error = str(e)
                log.debug("cloud reasoner model %s failed: %s", model, e)
                continue
            latency = (time.perf_counter() - t0) * 1000.0
            if not text:
                last_error = f"empty answer from {model}"
                continue
            if i > 0:
                self.stats.fallbacks += 1
            self.stats.answered += 1
            self.stats.total_latency_ms += latency
            return ReasonedAnswer(ok=True, answer=text, model=model,
                                  latency_ms=latency)
        self.stats.failed += 1
        return ReasonedAnswer(ok=False, error=last_error or "no models configured",
                              latency_ms=(time.perf_counter() - t0) * 1000.0)

    def status(self) -> dict:
        return {"primary": self.primary, "available": self.available(),
                "model": self.model, "fallback_models": list(self.fallback_models),
                **self.stats.snapshot()}


def get_cloud_reasoner() -> Optional[CloudReasoner]:
    """Build the reasoner if the cloud-primary policy is on and usable; else
    None (the conversation bridge then runs fully local-first, as before)."""
    reasoner = CloudReasoner()
    return reasoner if reasoner.available() else None
