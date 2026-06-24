"""
core/knowledge_portal/portal_server.py — FRIDAY 4.0 (M8)
The local web server. Wraps the framework-agnostic PortalAPI in Flask and serves
the single-page dashboard. Localhost-only, no cloud dependency, lightweight.

Flask is imported lazily inside `build_app()` so importing this module is
side-effect-free and dependency-light (the API/UI/graph layers don't need Flask).
"""

from __future__ import annotations

import logging
from typing import Optional

from .portal_api import PortalAPI
from .portal_ui import render_dashboard

log = logging.getLogger("friday.portal.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


class PortalServer:
    def __init__(self, knowledge_service, memory_service=None, *,
                 host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._api = PortalAPI(knowledge_service, memory_service)
        self.host = host
        self.port = port
        self._app = None

    @property
    def api(self) -> PortalAPI:
        return self._api

    def build_app(self):
        """Construct (once) and return the Flask app. Raises a clear error if
        Flask is not installed."""
        if self._app is not None:
            return self._app
        try:
            from flask import Flask, jsonify, request
        except ImportError as e:  # pragma: no cover - environment dependent
            raise RuntimeError("Flask is required to run the knowledge portal "
                               "(pip install flask)") from e

        app = Flask("friday_knowledge_portal")
        api = self._api

        @app.get("/")
        def index():
            return render_dashboard()

        @app.get("/health")
        def health():
            return jsonify({"status": "ok"})

        @app.get("/knowledge")
        def list_knowledge():
            return jsonify(api.list_knowledge(
                category=request.args.get("category"),
                status=request.args.get("status", "active"),
                limit=int(request.args.get("limit", 100))))

        @app.get("/knowledge/<kid>")
        def get_knowledge(kid):
            return jsonify(api.get(kid))

        @app.post("/knowledge")
        def create_knowledge():
            return jsonify(api.create(request.get_json(silent=True) or {}))

        @app.put("/knowledge/<kid>")
        def update_knowledge(kid):
            return jsonify(api.update(kid, request.get_json(silent=True) or {}))

        @app.delete("/knowledge/<kid>")
        def delete_knowledge(kid):
            return jsonify(api.delete(kid))

        @app.get("/search")
        def search():
            return jsonify(api.search(
                request.args.get("q", ""),
                k=int(request.args.get("k", 10)),
                allow_external=request.args.get("external") == "1"))

        @app.get("/graph")
        def graph():
            return jsonify(api.graph(status=request.args.get("status", "active")))

        @app.get("/stats")
        def stats():
            return jsonify(api.stats())

        self._app = app
        return app

    def run(self, *, debug: bool = False) -> None:  # pragma: no cover - blocking
        """Start the portal (blocking). Bound to localhost only."""
        app = self.build_app()
        log.info("knowledge portal on http://%s:%d", self.host, self.port)
        app.run(host=self.host, port=self.port, debug=debug)

    def start_background(self):  # pragma: no cover - thread/server
        """Start the portal in a daemon thread; returns the Thread."""
        import threading
        from werkzeug.serving import make_server

        app = self.build_app()
        server = make_server(self.host, self.port, app)
        t = threading.Thread(target=server.serve_forever, daemon=True,
                             name="friday-knowledge-portal")
        t.start()
        self._bg_server = server
        return t


def get_portal_server(knowledge_service=None, **kw) -> PortalServer:
    """Convenience builder using the M7 knowledge singleton when none is given."""
    if knowledge_service is None:
        from core.knowledge.knowledge_service import get_knowledge_service
        knowledge_service = get_knowledge_service()
    return PortalServer(knowledge_service, **kw)
