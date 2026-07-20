"""
core/knowledge/curiosity.py — FRIDAY 5.x (M62)
Constant learning: a curiosity drive that keeps her studying on her own.

The distiller (M55) only learns REACTIVELY — from gaps the owner's questions
expose. When no one is asking, her queue empties and she stops growing. The
curiosity engine fixes that: whenever the study queue runs low it refills it
autonomously, so she is always learning something. Two sources, in order:

    1. BRANCH — follow-up sub-topics off what she just learned (asked of the
       teacher), so her knowledge grows outward like a real curious mind:
       learn photosynthesis → next study chlorophyll, the light reactions, C4
       plants …
    2. CURRICULUM — a broad foundational syllabus she works through so she
       builds general knowledge even from a cold start (configurable).

Sustainable by construction: it only tops the queue up to a small threshold,
and a per-day budget caps how many new topics enter learning so the teacher
(Groq) quota is never surprised. Personal topics are never queued (the M55
boundary holds — curiosity inherits the distiller's guards). Never raises.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.knowledge.curiosity")

_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = _ROOT / "data" / "curiosity_state.json"

# a PRACTICAL syllabus — knowledge that makes her a better assistant to her
# owner (a builder: software, AI, systems, finance), not encyclopedia trivia.
# She works through it over time; owners fully override it via config
# learning.curriculum, and it branches off whatever they actually ask about.
_DEFAULT_CURRICULUM = [
    # software engineering — she helps write & reason about code
    "Python best practices for clean, maintainable code",
    "how to debug a program systematically",
    "common data structures and when to use each one",
    "time and space complexity (Big-O) and how to reason about it",
    "how to write effective unit tests",
    "how Git version control and branching work",
    "how to read and diagnose an error stack trace",
    "how HTTP and REST APIs work",
    "how recursion works and when to use it",
    "how asynchronous programming and concurrency work",
    "SQL basics and how database indexes speed up queries",
    "how to design a small software system before building it",
    "regular expressions and what they can and can't do",
    "how memory management and garbage collection work",
    "common security mistakes and how to avoid them",
    # AI / ML — her own domain
    "how neural networks learn from data",
    "how large language models generate text",
    "how model training, validation, and overfitting work",
    "how embeddings and vector search work",
    "how retrieval-augmented generation (RAG) works",
    # systems & tools — she controls a computer
    "how operating systems schedule processes and manage memory",
    "how DNS resolves a domain name to a server",
    "how public-key encryption and TLS secure a connection",
    "how caching improves performance at different layers",
    "how the command line and shell scripting work",
    # reasoning, finance, communication — general usefulness
    "how to break a large problem into solvable steps",
    "common cognitive biases and how to avoid them in decisions",
    "how compound interest and long-term investing work",
    "how to assess risk and expected value in a decision",
    "how to evaluate whether a source is reliable",
    "how to write a clear, concise technical explanation",
    "how to give precise step-by-step instructions",
    "the basics of budgeting and personal finance",
    "how supply and demand set prices in a market",
    "how to structure a persuasive, well-reasoned argument",
]

_BRANCH_PROMPT = (
    "A curious learner just studied: \"{topic}\". List 3 specific, distinct "
    "follow-up topics they should learn next to go deeper — each a short "
    "phrase, one per line, no numbering, no explanation.")
_LINE = re.compile(r"^[\s\-*\d.)]+")


class CuriosityEngine:
    """Keeps the distiller's study queue fed so learning never stalls. Inert
    without a distiller; never raises."""

    def __init__(self, distiller, *, knowledge=None, curriculum=None,
                 min_queue: int = 3, per_refill: int = 4,
                 max_per_day: int = 48, state_path: Optional[Path] = None) -> None:
        self.distiller = distiller
        self.knowledge = knowledge
        self.curriculum = list(curriculum or _DEFAULT_CURRICULUM)
        self.min_queue = max(1, int(min_queue))
        self.per_refill = max(1, int(per_refill))
        self.max_per_day = max(0, int(max_per_day))
        self._state_path = Path(state_path) if state_path else _STATE_PATH
        self._cur_idx = 0
        self._day = ""
        self._today = 0
        self.refills = 0
        self.proposed = 0
        self._load()

    # ── persistence (curriculum position + daily budget survive restarts) ────────
    def _load(self) -> None:
        try:
            s = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._cur_idx = int(s.get("cur_idx", 0)) % max(1, len(self.curriculum))
            self._day = s.get("day", "")
            self._today = int(s.get("today", 0))
            self.proposed = int(s.get("proposed", 0))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "cur_idx": self._cur_idx, "day": self._day,
                "today": self._today, "proposed": self.proposed}), encoding="utf-8")
        except OSError:
            log.debug("curiosity state save failed", exc_info=True)

    def _budget_left(self) -> int:
        today = time.strftime("%Y-%m-%d")
        if today != self._day:                 # new day → reset the budget
            self._day, self._today = today, 0
        return max(0, self.max_per_day - self._today)

    # ── the drive ────────────────────────────────────────────────────────────────
    def refill(self) -> int:
        """Top the study queue up when it runs low. Returns how many new topics
        were queued. Bounded by per_refill and the daily budget. Never raises."""
        try:
            if self.distiller is None:
                return 0
            pending = self.distiller.status().get("pending", 0)
            if pending >= self.min_queue:
                return 0
            budget = self._budget_left()
            if budget <= 0:
                return 0
            want = min(self.per_refill, budget, self.min_queue - pending + 1)
            topics = self._branch_topics(1) + self._curriculum_topics(want)
            queued = self.distiller.seed(topics[:want])
            if queued:
                self._today += queued
                self.proposed += queued
                self.refills += 1
                self._save()
                log.info("curiosity queued %d new topics to learn", queued)
            return queued
        except Exception:  # noqa: BLE001 — the learning drive never breaks a cycle
            log.debug("curiosity refill failed", exc_info=True)
            return 0

    def _curriculum_topics(self, n: int) -> list:
        """The next n foundational topics, rotating; skip ones already known."""
        out: list = []
        tries = 0
        while len(out) < n and tries < len(self.curriculum):
            topic = self.curriculum[self._cur_idx % len(self.curriculum)]
            self._cur_idx = (self._cur_idx + 1) % len(self.curriculum)
            tries += 1
            if not self._already_known(topic):
                out.append(topic)
        return out

    def _branch_topics(self, n: int) -> list:
        """Follow-ups off what she recently learned — knowledge that grows
        outward. Best-effort: needs the teacher; empty if unavailable."""
        teacher = getattr(self.distiller, "teacher", None)
        if teacher is None or self.knowledge is None:
            return []
        try:
            if not teacher.available():
                return []
            recent = self._recent_learned_title()
            if not recent:
                return []
            taught = teacher.ask(_BRANCH_PROMPT.format(topic=recent))
            if not getattr(taught, "ok", False):
                return []
            lines = [_LINE.sub("", ln).strip()
                     for ln in (taught.answer or "").splitlines()]
            return [ln for ln in lines if 3 <= len(ln) <= 90][:n]
        except Exception:  # noqa: BLE001
            log.debug("branch topics failed", exc_info=True)
            return []

    def _recent_learned_title(self) -> str:
        try:
            entries = self.knowledge.search_knowledge("", k=1) \
                if hasattr(self.knowledge, "search_knowledge") else []
            for e in entries or []:
                if getattr(e, "source", "") == "groq-distilled":
                    return getattr(e, "title", "") or ""
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _already_known(self, topic: str) -> bool:
        if self.knowledge is None:
            return False
        try:
            hits = self.knowledge.search_knowledge(topic, k=2)
            kws = {w for w in re.findall(r"[a-z]+", topic.lower()) if len(w) >= 4}
            for e in hits or []:
                title = (getattr(e, "title", "") or "").lower()
                if kws and kws <= set(re.findall(r"[a-z]+", title)):
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def status(self) -> dict:
        return {"refills": self.refills, "proposed": self.proposed,
                "today": self._today, "max_per_day": self.max_per_day,
                "curriculum_size": len(self.curriculum),
                "curriculum_pos": self._cur_idx}
