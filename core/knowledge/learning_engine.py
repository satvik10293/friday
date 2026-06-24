"""
core/knowledge/learning_engine.py — FRIDAY 4.0 (M7)
Turns *experience* into *knowledge*. Memories and reflections record what
happened; the learning engine distils the durable lesson and proposes a
KnowledgeEntry for storage.

Example: many memories say "Flask raised TemplateNotFound until I put the file
under templates/". The lesson FRIDAY keeps is:

    Title:   Flask looks for templates in the templates/ folder
    Content: Place Jinja templates under templates/ (or set template_folder);
             a bare render_template path raises TemplateNotFound.

The engine only *extracts and proposes*; the KnowledgeService decides whether to
store (after validation). No cloud — pattern extraction is local and rule-based.
"""

from __future__ import annotations

import re
from typing import Optional

from .knowledge_models import (KnowledgeCategory, KnowledgeEntry, new_knowledge)

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "to", "of", "and", "or", "in", "on", "is", "it", "i",
    "you", "was", "were", "be", "this", "that", "with", "for", "my", "me",
    "until", "when", "then", "but", "so", "had", "has", "have", "did", "do",
}


def _keywords(text: str, k: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for w in _WORD.findall((text or "").lower()):
        if w in _STOP or len(w) < 3:
            continue
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def _guess_category(text: str) -> str:
    t = (text or "").lower()
    table = [
        ("flask", KnowledgeCategory.FLASK),
        ("fastapi", KnowledgeCategory.FASTAPI),
        ("sqlite", KnowledgeCategory.SQLITE),
        ("opencv", KnowledgeCategory.OPENCV),
        ("cv2", KnowledgeCategory.OPENCV),
        ("numpy", KnowledgeCategory.PYTHON),
        ("python", KnowledgeCategory.PYTHON),
    ]
    for needle, cat in table:
        if needle in t:
            return cat
    return KnowledgeCategory.LESSON


class LearningEngine:
    def __init__(self, store=None) -> None:
        self._store = store

    # ── extraction ───────────────────────────────────────────────────────────────
    def extract_lesson(self, text: str, *, title: Optional[str] = None,
                       category: Optional[str] = None, confidence: float = 0.6,
                       source: str = "experience") -> Optional[KnowledgeEntry]:
        """Distil a single lesson from a blob of experience text. Returns a
        proposed (unstored) KnowledgeEntry, or None if nothing substantive."""
        content = (text or "").strip()
        if len(content) < 12:
            return None
        if title is None:
            kws = _keywords(content, 6)
            if not kws:
                return None
            title = " ".join(kws[:5]).capitalize()
        return new_knowledge(
            title=title.strip()[:120],
            content=content,
            category=category or _guess_category(content),
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            metadata={"learned": True},
        )

    def learn_from_memories(self, memories: list[dict], *, topic: Optional[str] = None,
                            confidence: float = 0.55) -> Optional[KnowledgeEntry]:
        """Fold a cluster of related memories into one candidate lesson. Memories
        are M2/M3-style dicts with a `content` field."""
        texts = [m.get("content", "") for m in (memories or []) if m.get("content")]
        if not texts:
            return None
        blob = " ".join(texts)
        title = topic or None
        entry = self.extract_lesson(blob, title=title, confidence=confidence,
                                    source="memory")
        if entry is not None:
            entry.metadata["from_memories"] = [m.get("id") for m in memories if m.get("id")]
        return entry

    def promote_memory(self, memory: dict, *, confidence: float = 0.6) -> Optional[KnowledgeEntry]:
        """Promote a single high-value memory into a knowledge candidate."""
        content = memory.get("content", "")
        if not content:
            return None
        entry = self.extract_lesson(
            content, title=memory.get("topic") or None,
            confidence=confidence, source="memory")
        if entry is not None and memory.get("id") is not None:
            entry.metadata["from_memory"] = memory["id"]
        return entry

    def promote_reflection(self, reflection: dict, *, confidence: float = 0.7
                           ) -> Optional[KnowledgeEntry]:
        """Promote a goal reflection's lesson into knowledge. Accepts a
        ReflectionRecord.to_dict() or any dict with a `lesson`/`summary`."""
        lesson = (reflection.get("lesson") or "").strip()
        summary = (reflection.get("summary") or "").strip()
        body = lesson or summary
        if not body:
            return None
        title = lesson[:80] if lesson else (summary[:80] or "Goal lesson")
        entry = new_knowledge(
            title=title, content=body, category=KnowledgeCategory.LESSON,
            confidence=confidence, source="reflection",
            metadata={"learned": True, "goal_id": reflection.get("goal_id")},
        )
        return entry
