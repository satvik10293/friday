"""
core/knowledge_portal/portal_graph.py — FRIDAY 4.0 (M8)
Builds the graph payload (nodes + edges) the portal renders as an interactive,
Obsidian-style graph view. Pure data assembly over the M7 KnowledgeStore — the
interactivity (zoom/pan/select) lives client-side in the embedded UI.
"""

from __future__ import annotations

from typing import Optional

# A small, stable palette keyed by category so the UI can colour nodes.
_CATEGORY_COLOR = {
    "Python": "#3572A5", "Flask": "#000000", "FastAPI": "#009688",
    "SQLite": "#003B57", "OpenCV": "#5C3EE8", "AI": "#FF6F00",
    "Automation": "#795548", "Lessons": "#9C27B0", "Projects": "#2E7D32",
    "Summaries": "#607D8B", "General": "#9E9E9E",
}


def _color(category: str) -> str:
    return _CATEGORY_COLOR.get(category, "#9E9E9E")


def build_graph(store, *, status: Optional[str] = "active",
                limit: int = 2000) -> dict:
    """Return {nodes: [...], edges: [...]} for the knowledge graph.

    nodes: {id, label, category, color, confidence, usage, size}
    edges: {source, target, relation}
    Only edges whose endpoints are both present as nodes are included.
    """
    entries = store.all_entries(status=status) if status else store.all_entries()
    entries = entries[:limit]
    node_ids = {e.id for e in entries}

    nodes = []
    for e in entries:
        nodes.append({
            "id": e.id,
            "label": e.title,
            "category": e.category,
            "color": _color(e.category),
            "confidence": round(e.confidence, 3),
            "usage": e.usage_count,
            "size": 6 + min(e.usage_count, 20),
        })

    edges = []
    seen = set()
    for link in store.all_links():
        if link.source_id not in node_ids or link.target_id not in node_ids:
            continue
        # collapse the symmetric `related` pair into one undirected edge
        key = tuple(sorted((link.source_id, link.target_id))) + (link.relation,)
        if link.relation == "related":
            key = tuple(sorted((link.source_id, link.target_id))) + ("related",)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": link.source_id, "target": link.target_id,
                      "relation": link.relation})

    return {"nodes": nodes, "edges": edges,
            "stats": {"nodes": len(nodes), "edges": len(edges)}}
