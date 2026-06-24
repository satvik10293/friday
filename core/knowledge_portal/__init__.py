"""
core/knowledge_portal/ — FRIDAY 4.0 (M8)
Local web interface for viewing, searching, exploring, and managing FRIDAY's
knowledge. The portal is a visualisation/management layer ONLY — SQLite (the M7
KnowledgeStore) remains the source of truth.

Side-effect-free to import: no server is started and no web framework is imported
at module import time. Build the app explicitly via `PortalServer.build_app()`.
"""

from __future__ import annotations

from .portal_api import PortalAPI
from .portal_graph import build_graph
from .portal_sync import PortalSync

__all__ = ["PortalAPI", "build_graph", "PortalSync", "PortalServer"]


def __getattr__(name):
    # Lazy export so importing the package never pulls in Flask.
    if name == "PortalServer":
        from .portal_server import PortalServer
        return PortalServer
    raise AttributeError(name)
