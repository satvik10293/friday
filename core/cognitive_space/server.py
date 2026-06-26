"""
core/cognitive_space/server.py — FRIDAY 4.0 (M11)
Serves the interactive cognitive universe + its read API and authenticated
controls. Reuses the M10 auth layer (no write without auth) and security headers,
and the Three.js asset vendored under Mission Control. Localhost-only; Flask is
imported lazily so this module stays side-effect-free.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from core.security.auth import security_headers
from .ui import render_cognitive_ui

log = logging.getLogger("friday.cognitive_space.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5060
_THREE = os.path.join(os.path.dirname(__file__), "..", "mission_control", "static",
                      "three.module.js")


class CognitiveSpaceServer:
    def __init__(self, cognitive_space, *, simulation_service=None, authenticator=None,
                 host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._space = cognitive_space
        self._sims = simulation_service
        if authenticator is None:
            from core.security.auth import Authenticator
            authenticator = Authenticator()
        self._auth = authenticator
        self.host = host
        self.port = port
        self._app = None

    @property
    def authenticator(self):
        return self._auth

    def build_app(self):
        if self._app is not None:
            return self._app
        try:
            from flask import Flask, jsonify, request, send_file
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Flask required for the cognitive space server") from e

        app = Flask("friday_cognitive_space")
        space, sims, auth = self._space, self._sims, self._auth

        def _auth_write(scope=None):
            return auth.authenticate(
                http_method=request.method,
                api_token=request.headers.get("X-API-Token"),
                session_token=request.headers.get("X-Session-Token"),
                origin=request.headers.get("Origin"),
                required_scope=scope, action=f"{request.method} {request.path}")

        @app.after_request
        def _secure(resp):
            for k, v in security_headers().items():
                resp.headers[k] = v
            return resp

        @app.get("/")
        def index():
            return render_cognitive_ui()

        @app.get("/static/three.module.js")
        def three():
            if os.path.exists(_THREE):
                return send_file(_THREE, mimetype="text/javascript")
            return ("// three.js not vendored; 2D fallback\n", 404,
                    {"Content-Type": "text/javascript"})

        @app.get("/api/space")
        def space_at():
            return jsonify(space.build(int(request.args.get("level", 1)),
                                       focus=request.args.get("focus")))

        @app.get("/api/space/levels")
        def levels():
            return jsonify({"levels": space.zoom_levels(),
                            "visual_language": space.visual_language()})

        @app.get("/api/space/search")
        def search():
            return jsonify(space.search(request.args.get("q", "")))

        @app.get("/api/space/health")
        def health():
            return jsonify(space.health())

        if sims is not None:
            @app.get("/api/sim/<sid>/timeline")
            def sim_timeline(sid):
                sim = sims.get(sid)
                if sim is None:
                    return jsonify({"error": "not_found"}), 404
                return jsonify(sims.timeline(sim).view())

            @app.post("/api/sim/<sid>/<action>")
            def sim_control(sid, action):
                res = _auth_write()           # controls mutate playback → require auth
                if not res.ok:
                    return jsonify({"error": "unauthorized", "reason": res.reason}), 401
                sim = sims.get(sid)
                if sim is None:
                    return jsonify({"error": "not_found"}), 404
                c = sims.controls(sim)
                if action == "replay":
                    c.replay()
                elif action == "ff":
                    c.fast_forward(1)
                elif action == "pause":
                    c.pause()
                elif action == "resume":
                    c.resume()
                return jsonify(c.state())

        self._app = app
        return app

    def run(self, *, debug: bool = False) -> None:  # pragma: no cover
        app = self.build_app()
        log.info("Cognitive Universe on http://%s:%d", self.host, self.port)
        app.run(host=self.host, port=self.port, debug=debug)
