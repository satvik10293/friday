"""
core/knowledge_portal/portal_api.py — FRIDAY 4.0 (M8)
Framework-agnostic REST logic for the knowledge portal. Every method returns
plain JSON-serialisable dicts/lists, so it is fully testable without a web server
and can be wrapped by Flask (portal_server) or driven directly by FRIDAY.

Maps to:
    GET    /knowledge            → list_knowledge
    GET    /knowledge/{id}       → get
    POST   /knowledge            → create
    PUT    /knowledge/{id}       → update
    DELETE /knowledge/{id}       → delete   (soft: archive)
    GET    /search?q=            → search
    GET    /graph                → graph
    GET    /stats                → stats
"""

from __future__ import annotations

from typing import Optional

from core.knowledge.knowledge_models import KnowledgeCategory
from core.knowledge.knowledge_search import KnowledgeSearch

from .portal_graph import build_graph


class PortalAPI:
    def __init__(self, knowledge_service, memory_service=None) -> None:
        self._k = knowledge_service
        self._search = KnowledgeSearch(knowledge_service, memory_service)

    # ── reads ──────────────────────────────────────────────────────────────────
    def list_knowledge(self, *, category: Optional[str] = None,
                       status: str = "active", limit: int = 100) -> dict:
        entries = self._k.store.list(category=category, status=status, limit=limit)
        return {"count": len(entries), "items": [e.to_dict() for e in entries]}

    def get(self, knowledge_id: str) -> dict:
        e = self._k.get(knowledge_id)
        if e is None:
            return {"error": "not_found", "id": knowledge_id}
        related = []
        for nid in self._k.graph.neighbors(knowledge_id):
            peer = self._k.store.get(nid)
            if peer is not None:
                related.append({"id": peer.id, "title": peer.title,
                                "category": peer.category})
        return {"item": e.to_dict(), "related": related}

    def search(self, query: str, *, k: int = 10, allow_external: bool = False) -> dict:
        result = self._search.search(query, k=k, allow_external=allow_external)
        return result.to_dict()

    def graph(self, *, status: str = "active") -> dict:
        return build_graph(self._k.store, status=status)

    def stats(self) -> dict:
        stats = self._k.stats()
        recent = self._k.store.list(status="active", limit=10)
        most_used = sorted(self._k.store.all_entries(status="active"),
                           key=lambda e: e.usage_count, reverse=True)[:10]
        return {
            "totals": {"total": stats.get("total"), "active": stats.get("active"),
                       "archived": stats.get("archived"), "links": stats.get("links")},
            "by_category": stats.get("by_category", {}),
            "index": stats.get("index", {}),
            "vault": stats.get("vault", {}),
            "recent": [{"id": e.id, "title": e.title, "category": e.category,
                        "updated_at": e.updated_at} for e in recent],
            "most_used": [{"id": e.id, "title": e.title, "usage": e.usage_count}
                          for e in most_used if e.usage_count > 0],
            "health": self._k.health(),
        }

    # ── writes ─────────────────────────────────────────────────────────────────
    def create(self, payload: dict) -> dict:
        title = (payload or {}).get("title", "").strip()
        if not title:
            return {"error": "title_required"}
        entry = self._k.remember_knowledge(
            title, payload.get("content", ""),
            category=payload.get("category", KnowledgeCategory.GENERAL),
            confidence=float(payload.get("confidence", 0.7)),
            source=payload.get("source", "portal"),
            validate=bool(payload.get("validate", True)))
        return {"item": entry.to_dict()}

    def update(self, knowledge_id: str, payload: dict) -> dict:
        entry = self._k.update_knowledge(
            knowledge_id,
            title=(payload or {}).get("title"),
            content=(payload or {}).get("content"),
            confidence=(payload or {}).get("confidence"))
        if entry is None:
            return {"error": "not_found", "id": knowledge_id}
        return {"item": entry.to_dict()}

    def delete(self, knowledge_id: str) -> dict:
        """Soft delete: archive (the vault keeps the note; nothing is destroyed)."""
        if self._k.get(knowledge_id) is None:
            return {"error": "not_found", "id": knowledge_id}
        self._k.archive(knowledge_id)
        return {"archived": knowledge_id}
