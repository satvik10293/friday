"""
core/mission_control/server.py — FRIDAY 4.0 (M10)
The Mission Control web server. Serves the single-screen HUD and a read API for the
cockpit, and a small set of **authenticated** write/admin endpoints. Every response
carries the M10 security headers; every write requires authentication + origin
validation via core.security.auth (no write without auth).

Flask is imported lazily inside `build_app()`, so importing this module is
side-effect-free and dependency-light. Localhost-only.
"""

from __future__ import annotations

import logging

from core.security.auth import security_headers
from .ui import render_hud

log = logging.getLogger("friday.mission_control.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050


class MissionControlServer:
    def __init__(self, mission_control, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT) -> None:
        self._mc = mission_control
        self.host = host
        self.port = port
        self._app = None

    def build_app(self):
        if self._app is not None:
            return self._app
        try:
            from flask import Flask, jsonify, request
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Flask required for Mission Control server") from e

        app = Flask("friday_mission_control")
        mc = self._mc
        auth = mc.authenticator

        def _auth(required_scope=None):
            """Authenticate the current request; returns AuthResult."""
            return auth.authenticate(
                http_method=request.method,
                api_token=request.headers.get("X-API-Token"),
                session_token=request.headers.get("X-Session-Token")
                or request.cookies.get("fmc_session"),
                origin=request.headers.get("Origin"),
                required_scope=required_scope,
                action=f"{request.method} {request.path}")

        @app.after_request
        def _secure(resp):
            for k, v in security_headers().items():
                resp.headers[k] = v
            return resp

        # ── HUD + read API (open reads; flip mc to protect_reads to lock down) ──
        @app.get("/")
        def index():
            return render_hud()

        @app.get("/static/three.module.js")
        def three_js():
            # Vendored offline; if absent we 404 and the HUD uses its 2D fallback.
            from flask import send_file
            import os
            path = os.path.join(os.path.dirname(__file__), "static", "three.module.js")
            if os.path.exists(path):
                return send_file(path, mimetype="text/javascript")
            return ("// three.js not vendored; HUD uses 2D fallback\n", 404,
                    {"Content-Type": "text/javascript"})

        @app.get("/api/state")
        def state():
            res = _auth()
            if not res.ok:
                return jsonify({"error": "unauthorized", "reason": res.reason}), 401
            return jsonify(mc.state())

        @app.get("/api/panels/<name>")
        def panel(name):
            res = _auth()
            if not res.ok:
                return jsonify({"error": "unauthorized"}), 401
            return jsonify(mc.panel(name))

        @app.get("/api/events")
        def events():
            return jsonify(mc.events.recent(int(request.args.get("limit", 100))))

        @app.get("/api/health")
        def health():
            return jsonify(mc.health())

        # ── authenticated writes/admin ─────────────────────────────────────────
        @app.post("/api/event")
        def push_event():
            res = _auth(required_scope="admin")
            if not res.ok:
                return jsonify({"error": "unauthorized", "reason": res.reason}), 401
            body = request.get_json(silent=True) or {}
            ev = mc.events.push(body.get("kind", "manual"), data=body.get("data", {}),
                                source=res.actor, level=body.get("level", "info"))
            return jsonify({"pushed": ev})

        @app.post("/api/auth/login")
        def login():
            # demo session login; in production gate behind a real credential check
            sess = auth.login(actor="operator")
            return jsonify({"session_token": sess.token, "expires_at": sess.expires_at})

        self._app = app
        return app

    def run(self, *, debug: bool = False) -> None:  # pragma: no cover - blocking
        app = self.build_app()
        log.info("Mission Control on http://%s:%d", self.host, self.port)
        app.run(host=self.host, port=self.port, debug=debug)
