"""
M26 — security hardening (pre-release hole check).

The vision transport server is the one network-facing surface that could accept
camera frames. It must default to localhost, refuse LAN binding unless explicitly
allowed, never expose the Werkzeug debugger, and restrict socket CORS to the
self-served origin. Also asserts every other Flask server defaults to localhost.
"""

from __future__ import annotations

import logging

from core.vision.transport.server import (DEFAULT_HOST, VisionTransportServer,
                                          _is_localhost)


class _Manager:
    def start(self):
        pass

    def register(self, *a, **k):
        return "cam-1"

    def health(self):
        return {}


def test_default_bind_is_localhost():
    assert DEFAULT_HOST == "127.0.0.1"
    server = VisionTransportServer(_Manager())
    assert server.host == "127.0.0.1"
    assert server._lan is False


def test_lan_binding_requires_explicit_optin(caplog):
    with caplog.at_level(logging.WARNING):
        server = VisionTransportServer(_Manager(), host="0.0.0.0")
    assert server.host == "127.0.0.1"                 # refused, fell back
    assert any("allow_lan" in r.message for r in caplog.records)


def test_lan_binding_allowed_when_opted_in(caplog):
    with caplog.at_level(logging.WARNING):
        server = VisionTransportServer(_Manager(), host="0.0.0.0", allow_lan=True)
    assert server.host == "0.0.0.0"
    assert server._lan is True
    assert any("local network" in r.message for r in caplog.records)


def test_cors_origins_are_same_origin_only_on_localhost():
    server = VisionTransportServer(_Manager())
    origins = server._allowed_origins()
    assert all("127.0.0.1" in o or "localhost" in o for o in origins)
    assert "*" not in origins


def test_cors_adds_the_lan_origin_only_when_lan():
    server = VisionTransportServer(_Manager(), host="0.0.0.0", allow_lan=True)
    assert any("0.0.0.0" in o for o in server._allowed_origins())


def test_is_localhost_helper():
    assert _is_localhost("127.0.0.1") and _is_localhost("localhost")
    assert not _is_localhost("0.0.0.0") and not _is_localhost("192.168.1.5")


def test_all_flask_servers_default_to_localhost():
    from core.cognitive_space import server as cs
    from core.knowledge_portal import portal_server as kp
    from core.mission_control import server as mc
    assert mc.DEFAULT_HOST == "127.0.0.1"
    assert cs.DEFAULT_HOST == "127.0.0.1"
    assert kp.DEFAULT_HOST == "127.0.0.1"


def test_math_worker_rejects_code_execution():
    from core.society.worker_tasks import math_solve
    assert math_solve("2 + 3 * 4")["value"] == 14
    for evil in ("__import__('os').system('echo hi')", "open('x')", "x", "1+len([1])"):
        try:
            math_solve(evil)
        except (ValueError, SyntaxError, NameError):
            continue
        raise AssertionError(f"math_solve accepted unsafe input: {evil!r}")
