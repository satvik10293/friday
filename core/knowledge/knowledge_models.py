"""
core/knowledge/knowledge_models.py — FRIDAY 4.0 (M7)
Knowledge data model. A KnowledgeEntry is one piece of *distilled understanding*
(a concept, fact, coding pattern, lesson, or summary) — distinct from a raw
memory (an experience). Pure data, no I/O, fully serializable.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class KnowledgeCategory:
    """Free-text categories, with the common ones named for consistency."""
    PYTHON = "Python"
    FLASK = "Flask"
    FASTAPI = "FastAPI"
    SQLITE = "SQLite"
    OPENCV = "OpenCV"
    AI = "AI"
    AUTOMATION = "Automation"
    LESSON = "Lessons"
    PROJECT = "Projects"
    SUMMARY = "Summaries"
    GENERAL = "General"


class KnowledgeRelation(str, Enum):
    PARENT = "parent"
    CHILD = "child"
    RELATED = "related"


class KnowledgeStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").strip()).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:80] or "untitled"


@dataclass
class KnowledgeEntry:
    id: str
    title: str
    category: str = KnowledgeCategory.GENERAL
    content: str = ""
    confidence: float = 0.5
    source: str = "system"
    created_at: float = 0.0
    updated_at: float = 0.0
    usage_count: int = 0
    status: str = KnowledgeStatus.ACTIVE.value
    embed_id: Optional[int] = None
    vault_path: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def slug(self) -> str:
        return slugify(self.title)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    def to_row(self) -> tuple:
        import json
        return (
            self.id, self.title, self.category, self.content, self.confidence,
            self.source, self.created_at, self.updated_at, self.usage_count,
            self.status, self.embed_id, self.vault_path, json.dumps(self.metadata),
        )

    @staticmethod
    def from_row(r) -> "KnowledgeEntry":
        import json
        try:
            meta = json.loads(r["metadata"])
        except (TypeError, ValueError):
            meta = {}
        return KnowledgeEntry(
            id=r["id"], title=r["title"], category=r["category"], content=r["content"],
            confidence=r["confidence"], source=r["source"], created_at=r["created_at"],
            updated_at=r["updated_at"], usage_count=r["usage_count"], status=r["status"],
            embed_id=r["embed_id"], vault_path=r["vault_path"], metadata=meta,
        )

    @staticmethod
    def from_dict(d: dict) -> "KnowledgeEntry":
        return KnowledgeEntry(
            id=d.get("id") or uuid.uuid4().hex[:12],
            title=d["title"], category=d.get("category", KnowledgeCategory.GENERAL),
            content=d.get("content", ""), confidence=d.get("confidence", 0.5),
            source=d.get("source", "system"), created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0), usage_count=d.get("usage_count", 0),
            status=d.get("status", KnowledgeStatus.ACTIVE.value),
            embed_id=d.get("embed_id"), vault_path=d.get("vault_path"),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class KnowledgeLink:
    source_id: str
    target_id: str
    relation: str = KnowledgeRelation.RELATED.value
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ValidationReport:
    ok: bool = True
    duplicates: list = field(default_factory=list)       # ids of duplicate entries
    contradictions: list = field(default_factory=list)   # list[dict]
    outdated: list = field(default_factory=list)         # ids
    low_confidence: bool = False
    recommendation: str = "store"                        # store | update | reject
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ConsolidationResult:
    summaries_created: int = 0
    archived: int = 0
    summary_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def new_knowledge(title: str, content: str = "", *, category: str = KnowledgeCategory.GENERAL,
                  confidence: float = 0.5, source: str = "system",
                  metadata: Optional[dict] = None) -> KnowledgeEntry:
    now = time.time()
    return KnowledgeEntry(
        id=uuid.uuid4().hex[:12], title=title.strip(), category=category,
        content=content, confidence=max(0.0, min(1.0, confidence)), source=source,
        created_at=now, updated_at=now, metadata=dict(metadata or {}),
    )
