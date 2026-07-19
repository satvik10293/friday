"""
core/reasoning/native.py — FRIDAY 5.x (M56)
The NativeMind: SHE is the reasoning model.

No external model, no weights, no generation. The NativeMind is FRIDAY's own
language faculty implemented as an algorithm over HER OWN accumulated
knowledge: it reads her notes and memories, ranks her own sentences against
the question, and composes an answer from them — with provenance-shaped
confidence (coverage of the question's concepts by her own material).

Why this is the path (owner-directed): every answer traces to something she
learned; nothing is hallucinated because nothing is generated. When her notes
don't cover a question she says so at low confidence — the turn escalates,
the distiller (M55) studies the topic, and the NEXT time the NativeMind covers
it herself. The flywheel doesn't just grow a notebook; it grows HER.

The engine (engine.py) uses her through the structured interface — plan /
solve_step / synthesize — so the deliberate loop (decompose → exact tools →
retrieval → synthesis) runs entirely on her own faculties. The generate()
method exists only to satisfy the Substrate protocol (used for code asks,
which she honestly cannot write natively → empty → the turn defers).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger("friday.reasoning.native")

_WORD = re.compile(r"[a-z0-9']+")
_SENT = re.compile(r"(?<=[.!?])\s+")
_STOP = {"the", "a", "an", "to", "of", "and", "or", "is", "are", "was", "were",
         "it", "how", "do", "does", "did", "i", "you", "me", "my", "we",
         "what", "whats", "why", "when", "where", "who", "which", "this",
         "that", "with", "for", "in", "on", "at", "can", "could", "would",
         "should", "tell", "about", "please", "friday", "hey", "okay", "be",
         "has", "have", "had", "her", "his", "their", "its", "into", "from"}
# steps that split on these become her native decomposition
_SPLIT = re.compile(r"\s+(?:and then|then|and also|; and|;)\s+", re.I)


def _keywords(text: str, k: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for w in _WORD.findall((text or "").lower()):
        if w in _STOP or len(w) < 3:
            continue
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


class NativeMind:
    """Her own reasoning model: extractive composition over her knowledge and
    memory. Substrate-compatible; never raises; never invents."""

    base_confidence = 0.6            # protocol attr; real trust is per-answer
    min_coverage = 0.5               # below this her notes don't cover it → defer

    def __init__(self, knowledge=None, memory=None, *,
                 max_sentences: int = 3) -> None:
        self.knowledge = knowledge
        self.memory = memory
        self.max_sentences = max(1, int(max_sentences))
        # the engine reads this right after an op: honest, per-answer trust
        self.last_confidence: Optional[float] = None
        self.extractions = 0
        self.deferrals = 0

    def available(self) -> bool:
        return self.knowledge is not None or self.memory is not None

    # ── her own material ─────────────────────────────────────────────────────────
    def _material(self, query: str) -> list[str]:
        """Everything SHE knows that might bear on the query (cleaned of vault
        metadata). Local-only by construction — both stores live on the box."""
        texts: list[str] = []
        if self.knowledge is not None:
            try:
                for e in self.knowledge.search_knowledge(query, k=4) or []:
                    body = getattr(e, "content", "") or ""
                    title = getattr(e, "title", "") or ""
                    if body:
                        texts.append(f"{title}. {body}" if title else body)
            except Exception:  # noqa: BLE001 — a store fault means less material
                log.debug("knowledge search failed", exc_info=True)
        if self.memory is not None:
            try:
                for m in self.memory.recall(query, k=4) or []:
                    if isinstance(m, dict) and (m.get("content") or "").strip():
                        texts.append(m["content"])
            except Exception:  # noqa: BLE001
                log.debug("memory recall failed", exc_info=True)
        try:
            from core.intelligence.mini_brains import clean_snippet
            texts = [clean_snippet(t) for t in texts]
        except Exception:  # noqa: BLE001 — cleaning is best-effort
            pass
        return [t for t in texts if t]

    def _extract(self, query: str) -> tuple[str, float]:
        """Rank HER OWN sentences against the query; compose the best few.
        Returns (composition, coverage-of-query-concepts)."""
        kws = set(_keywords(query))
        if not kws:
            return "", 0.0
        try:
            from core.intelligence.mini_brains import is_answer_sentence
        except Exception:  # noqa: BLE001
            def is_answer_sentence(_s):  # pragma: no cover
                return True
        scored: list[tuple[float, str]] = []
        seen: set[str] = set()
        for text in self._material(query):
            for sentence in _SENT.split(text):
                s = sentence.strip()
                if len(s) < 15 or s.lower() in seen:
                    continue
                seen.add(s.lower())
                # never recite a stored QUESTION or reminder as an answer —
                # that is the parroting bug (capital-of-France -> a stored
                # "what is the capital of Japan?")
                if not is_answer_sentence(s):
                    continue
                hit = kws & set(_keywords(s, k=14))
                # require a DISTINCTIVE overlap (a word of real length) — a
                # match on only a short common word ("all", "one") recites
                # off-topic notes; that is the parroting bug's second face
                if hit and any(len(w) >= 4 for w in hit):
                    # relevance, with a mild brevity preference
                    scored.append((len(hit) - 0.001 * len(s), s))
        if not scored:
            return "", 0.0
        scored.sort(key=lambda t: -t[0])
        chosen = [s for _, s in scored[:self.max_sentences]]
        covered = set()
        for s in chosen:
            covered |= kws & set(_keywords(s, k=14))
        coverage = len(covered) / len(kws)
        return " ".join(chosen)[:600], coverage

    # ── the structured interface the engine prefers ──────────────────────────────
    def plan(self, question: str) -> list[str]:
        """Native decomposition: conjunction/sequence splitting. No model —
        multi-part questions become their parts, everything else is one step."""
        parts = [p.strip(" ?.") for p in _SPLIT.split(question or "") if p.strip()]
        if len(parts) >= 2:
            return parts[:4]
        return [question]

    def solve_step(self, step: str, question: str, prior: list[str]) -> str:
        """A step is solved by reading her own notes about it."""
        text, coverage = self._extract(step if len(step) > 8 else question)
        if coverage < self.min_coverage:
            return ""
        self.extractions += 1
        return text

    def synthesize(self, question: str, worked: list[str]) -> str:
        """Compose the final answer from the worked steps (or directly from
        her notes). Sets last_confidence from real coverage — the engine reads
        it right after. Below min_coverage she declines, and the turn defers."""
        if worked:
            results = [w.split(" -> ", 1)[-1].strip() for w in worked]
            results = [r for r in results if r]
            if results:
                self.last_confidence = 0.65
                return " ".join(dict.fromkeys(results))[:700]
        text, coverage = self._extract(question)
        if not text or coverage < self.min_coverage:
            self.deferrals += 1
            self.last_confidence = 0.2
            return ""
        self.extractions += 1
        self.last_confidence = round(0.35 + 0.45 * coverage, 3)
        return text

    # ── Substrate protocol (fallback path; code asks land here) ──────────────────
    def generate(self, prompt: str, *, context: Optional[dict] = None,
                 temperature: float = 0.3) -> str:
        """She does not generate. For free-form prompts she can only read her
        notes; a code ask honestly returns nothing (→ the turn defers)."""
        text, coverage = self._extract(prompt)
        return text if coverage >= self.min_coverage else ""

    def status(self) -> dict:
        return {"native": True, "available": self.available(),
                "extractions": self.extractions, "deferrals": self.deferrals}
