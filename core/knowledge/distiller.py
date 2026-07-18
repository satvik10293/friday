"""
core/knowledge/distiller.py — FRIDAY 5.x (M55)
The notebook trick: gap-driven knowledge distillation.

Every time FRIDAY had to "phone the tutor" (the cloud answered a substantive,
NON-personal question), that topic is proof of a gap in her own notebook. The
distiller closes the loop:

    cloud answers a turn → note_gap(question) queues the topic
        → later, quietly, ask the teacher to EXPLAIN the topic (not just
          answer it) → distil the explanation into the knowledge base,
          tagged  source="groq-distilled"
        → the next similar question is answered from HER OWN notes, locally
          (the conversation bridge's notebook pass), no cloud call.

Honest scope (as discussed with the owner): this grows her FACTUAL knowledge —
recall gets genuinely better and more questions go local over time. It does
not make the reader smarter: novel reasoning and coding stay with the
deliberate brain + cloud. Facts aren't copyrightable and this is a personal
notebook, not a competing model — but the notes are rewritten explanations
with provenance, never bulk verbatim archives.

Boundaries that do NOT move:
    · personal-shaped questions are NEVER queued — their answers live in local
      memory and must not be sent out as study topics (M43 boundary)
    · dedup at both ends: a topic already queued or already distilled is
      skipped, and the KnowledgeService's validator refines near-duplicates
      instead of stacking twins
    · bounded and quiet: a cycle distils at most `per_cycle` topics, respecting
      the teacher's availability; a failure re-queues nothing loudly — the gap
      simply stays until a later cycle
    · never raises; with no teacher or no knowledge service it is inert

The gap queue persists to data/distiller_queue.json so gaps survive restarts.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.knowledge.distiller")

_ROOT = Path(__file__).resolve().parents[2]
_QUEUE_PATH = _ROOT / "data" / "distiller_queue.json"

_MAX_QUEUE = 200
_WORD = re.compile(r"[a-z0-9']+")
_STOP = {"the", "a", "an", "to", "of", "and", "or", "is", "are", "was", "it",
         "how", "do", "does", "did", "i", "you", "me", "my", "we", "what",
         "whats", "why", "when", "where", "who", "which", "this", "that",
         "with", "for", "in", "on", "at", "can", "could", "would", "should",
         "tell", "about", "please", "friday", "hey", "okay"}

# what we ask the tutor: teach the topic, don't just answer the question —
# the note must serve the NEXT similar question, not only this one
_TEACH_PROMPT = (
    "Teach the following topic for a personal knowledge base. Give the key "
    "facts, how it works, and common misconceptions, in 5-10 plain sentences "
    "of your own words. No markdown, no lists, no preamble.\n\nTopic: {topic}")


def _topic_key(question: str) -> str:
    """A stable, order-insensitive key for a question's topic, for dedup."""
    words = sorted(w for w in _WORD.findall((question or "").lower())
                   if w not in _STOP and len(w) >= 3)
    return " ".join(words[:8])


def _is_personal(question: str) -> bool:
    try:
        from core.memory.learning_gate import _PERSONAL_RE
        return bool(_PERSONAL_RE.search(question or ""))
    except ImportError:
        return True          # can't verify → treat as personal (fail closed)


class KnowledgeDistiller:
    """Harvests the topics FRIDAY couldn't answer herself into her own
    knowledge base. Inert without a teacher + knowledge service; never raises."""

    def __init__(self, knowledge=None, teacher=None, *,
                 per_cycle: int = 2, min_gap_words: int = 2,
                 queue_path: Optional[Path] = None) -> None:
        self.knowledge = knowledge
        self.teacher = teacher
        self.per_cycle = max(1, int(per_cycle))
        self.min_gap_words = max(1, int(min_gap_words))
        self._queue_path = queue_path if queue_path is not None else _QUEUE_PATH
        self._lock = threading.Lock()
        self._queue: list[dict] = []       # {"topic","question","ts"}
        self._done_keys: set[str] = set()  # distilled this process + loaded
        self.queued = 0
        self.distilled = 0
        self.skipped_personal = 0
        self.failed = 0
        self._load()

    # ── persistence (survives restarts; best-effort) ─────────────────────────────
    def _load(self) -> None:
        try:
            data = json.loads(self._queue_path.read_text(encoding="utf-8"))
            self._queue = list(data.get("queue") or [])[:_MAX_QUEUE]
            self._done_keys = set(data.get("done") or [])
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            self._queue_path.parent.mkdir(parents=True, exist_ok=True)
            self._queue_path.write_text(json.dumps({
                "queue": self._queue[-_MAX_QUEUE:],
                "done": sorted(self._done_keys)[-1000:],
            }, indent=1), encoding="utf-8")
        except OSError:
            log.debug("distiller queue save failed", exc_info=True)

    # ── harvest side: the bridge notes every gap ─────────────────────────────────
    def note_gap(self, question: str, *, deliberate: bool = False) -> bool:
        """A cloud answer just proved a gap. Queue the topic — unless it's
        personal (never leaves as a study topic), trivial, or already
        queued/distilled. `deliberate` marks an owner-directed study request:
        a single strong topic word ("inflation") is enough there, while
        harvested conversation still needs ≥2 to filter chatter. Returns
        whether it was queued. Never raises."""
        try:
            question = (question or "").strip()
            if not question:
                return False
            if _is_personal(question):
                self.skipped_personal += 1
                return False
            key = _topic_key(question)
            min_words = 1 if deliberate else self.min_gap_words
            if len(key.split()) < min_words:
                return False               # too thin to study ("what's up")
            with self._lock:
                if key in self._done_keys or \
                        any(g["topic"] == key for g in self._queue):
                    return False
                self._queue.append({"topic": key, "question": question,
                                    "ts": time.time()})
                self._queue = self._queue[-_MAX_QUEUE:]
                self.queued += 1
                self._save()
            return True
        except Exception:  # noqa: BLE001 — harvesting must never break a turn
            log.debug("note_gap failed", exc_info=True)
            return False

    # ── distil side: quietly close one gap ───────────────────────────────────────
    def distill_once(self) -> bool:
        """Take the oldest gap, ask the teacher to TEACH it, and store the
        explanation as her own note (validated + deduped by the knowledge
        service, provenance kept). Returns whether a note was stored."""
        if self.knowledge is None or self.teacher is None:
            return False
        try:
            if not self.teacher.available():
                return False
        except Exception:  # noqa: BLE001
            return False
        with self._lock:
            if not self._queue:
                return False
            gap = self._queue.pop(0)
            self._save()
        try:
            taught = self.teacher.ask(_TEACH_PROMPT.format(topic=gap["question"]))
            if not getattr(taught, "ok", False) or not (taught.answer or "").strip():
                self.failed += 1
                with self._lock:           # keep the gap; a later cycle retries
                    self._queue.append(gap)
                    self._save()
                return False
            title = gap["question"].strip().rstrip("?")[:120]
            self.knowledge.remember_knowledge(
                title, taught.answer.strip(),
                confidence=0.7, source="groq-distilled",
                metadata={"distilled_from": gap["question"],
                          "teacher_model": getattr(taught, "model", "")})
            with self._lock:
                self._done_keys.add(gap["topic"])
                self._save()
            self.distilled += 1
            log.info("distilled into the notebook: %s", title)
            return True
        except Exception:  # noqa: BLE001 — a bad distil drops quietly
            self.failed += 1
            log.debug("distill_once failed", exc_info=True)
            return False

    def seed(self, topics) -> int:
        """Owner-directed curriculum: queue topics to study deliberately (from
        config `distiller.seed_topics` or a voice command), same dedup and
        personal guards as harvested gaps. Returns how many were queued."""
        queued = 0
        for topic in topics or []:
            if isinstance(topic, str) and self.note_gap(topic, deliberate=True):
                queued += 1
        return queued

    def run_cycle(self) -> int:
        """One scheduled pass: close up to `per_cycle` gaps. Bounded, quiet,
        never raises — the runtime can call this on a timer forever."""
        done = 0
        try:
            for _ in range(self.per_cycle):
                if not self.distill_once():
                    break
                done += 1
        except Exception:  # noqa: BLE001
            log.debug("distiller cycle failed", exc_info=True)
        return done

    def status(self) -> dict:
        with self._lock:
            pending = len(self._queue)
        return {"pending": pending, "queued": self.queued,
                "distilled": self.distilled, "failed": self.failed,
                "skipped_personal": self.skipped_personal,
                "enabled": self.knowledge is not None and self.teacher is not None}


def get_distiller() -> Optional[KnowledgeDistiller]:
    """Build the distiller from config + live services; None (inert) when
    disabled or when either side is missing. Never raises."""
    try:
        cfg_path = _ROOT / "friday_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")).get("distiller") or {}
        if not cfg.get("enabled", True):
            return None
        from core.intelligence.teacher import get_teacher
        from core.knowledge.knowledge_service import get_knowledge_service
        teacher = get_teacher()
        if teacher is None:
            return None
        distiller = KnowledgeDistiller(get_knowledge_service(), teacher,
                                       per_cycle=int(cfg.get("per_cycle", 2)))
        distiller.seed(cfg.get("seed_topics") or [])   # owner's curriculum
        return distiller
    except Exception as e:  # noqa: BLE001 — the notebook is always optional
        log.debug("distiller unavailable: %s", e)
        return None
