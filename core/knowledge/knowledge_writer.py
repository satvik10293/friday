"""
core/knowledge/knowledge_writer.py — FRIDAY 4.0 (M8)
Knowledge distillation. Turns raw information into a structured, human-readable
note and stores it as durable knowledge with automatic backlinks.

Note format (Obsidian-friendly):

    # Flask Routing

    ## Concept
    Maps URLs to Python functions.

    ## Example
    @app.route("/")

    ## Related
    - [[Python]]
    - [[Web Development]]

Additive: composes the M7 KnowledgeService (validation, storage, vault, graph).
The structured body is stored as the entry content; `Related` concepts become
`[[backlinks]]` (rendered by the M7 vault) and real graph relations when the
related concepts already exist as knowledge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .knowledge_models import KnowledgeCategory, KnowledgeRelation

_WORD = re.compile(r"[a-z0-9]+")
_SENT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class DistilledNote:
    title: str
    concept: str = ""
    example: str = ""
    related: list = field(default_factory=list)
    category: str = KnowledgeCategory.GENERAL

    def to_markdown(self) -> str:
        parts = [f"# {self.title}", "## Concept", self.concept.strip() or "(none)"]
        if self.example.strip():
            parts += ["## Example", self.example.strip()]
        if self.related:
            parts += ["## Related", "\n".join(f"- [[{r}]]" for r in self.related)]
        return "\n\n".join(parts) + "\n"

    def body(self) -> str:
        """The stored content (Concept + Example sections, without the H1 title)."""
        parts = ["## Concept", self.concept.strip() or "(none)"]
        if self.example.strip():
            parts += ["## Example", self.example.strip()]
        return "\n\n".join(parts)


class KnowledgeWriter:
    def __init__(self, knowledge_service) -> None:
        self._k = knowledge_service

    # ── distillation ───────────────────────────────────────────────────────────
    def distill(self, title: str, raw: str, *,
                example: str = "", related: Optional[list[str]] = None,
                category: str = KnowledgeCategory.GENERAL) -> DistilledNote:
        """Structure raw text into a DistilledNote. The concept is the most
        informative sentence(s); related concepts are explicit or inferred."""
        concept = self._concept(raw)
        rel = list(related) if related else self._infer_related(f"{title} {raw}")
        return DistilledNote(title=title.strip(), concept=concept,
                             example=example.strip(), related=rel, category=category)

    @staticmethod
    def _concept(raw: str) -> str:
        text = re.sub(r"\s+", " ", (raw or "").strip())
        if not text:
            return ""
        sentences = [s.strip() for s in _SENT.split(text) if len(s.strip()) > 12]
        if not sentences:
            return text[:300]
        ranked = sorted(enumerate(sentences), key=lambda it: (-len(it[1]), it[0]))
        keep = sorted(i for i, _ in ranked[:2])
        return " ".join(sentences[i] for i in keep)[:400]

    @staticmethod
    def _infer_related(text: str) -> list[str]:
        t = (text or "").lower()
        catalogue = {
            "Python": ("python", "pip", "numpy"),
            "Flask": ("flask", "jinja", "werkzeug"),
            "FastAPI": ("fastapi", "uvicorn", "pydantic"),
            "SQLite": ("sqlite", "sql"),
            "OpenCV": ("opencv", "cv2"),
            "Web Development": ("route", "http", "url", "request", "endpoint"),
        }
        return [name for name, needles in catalogue.items()
                if any(n in t for n in needles)]

    # ── write path ─────────────────────────────────────────────────────────────
    def write(self, title: str, raw: str, *, example: str = "",
              related: Optional[list[str]] = None,
              category: str = KnowledgeCategory.GENERAL,
              confidence: float = 0.7, source: str = "distilled"):
        """Distil, store (validated, indexed, vaulted), generate backlinks, and
        link to any related concepts that already exist. Returns the stored entry."""
        note = self.distill(title, raw, example=example, related=related,
                            category=category)
        meta = {"links": note.related, "distilled": True, "structured": True}
        entry = self._k.remember_knowledge(
            note.title, note.body(), category=category,
            confidence=confidence, source=source, metadata=meta)
        self._link_related(entry, note.related)
        return entry

    def write_note(self, note: DistilledNote, *, confidence: float = 0.7,
                   source: str = "distilled"):
        meta = {"links": note.related, "distilled": True, "structured": True}
        entry = self._k.remember_knowledge(
            note.title, note.body(), category=note.category,
            confidence=confidence, source=source, metadata=meta)
        self._link_related(entry, note.related)
        return entry

    def _link_related(self, entry, related: list[str]) -> None:
        """Create real graph relations for related concepts that already exist."""
        for name in related or []:
            peer = self._k.store.find_by_title(name)
            if peer is not None and peer.id != entry.id:
                try:
                    self._k.relate(entry.id, peer.id, KnowledgeRelation.RELATED.value)
                except Exception:
                    pass

    def render(self, knowledge_id: str) -> str:
        """Render an existing entry as a structured Markdown note."""
        e = self._k.store.get(knowledge_id)
        if e is None:
            return ""
        related = e.metadata.get("links", [])
        body = e.content
        if body.lstrip().startswith("## Concept"):
            note_body = body
        else:
            note_body = f"## Concept\n\n{body}"
        parts = [f"# {e.title}", note_body]
        if related:
            parts.append("## Related\n\n" + "\n".join(f"- [[{r}]]" for r in related))
        return "\n\n".join(parts) + "\n"
