"""
core/services/executive_service.py — FRIDAY V3 (M16)
ExecutiveService — one-way notification seam to the Executive Brain. Spatial cognition
reports salient happenings (a person entered, an object the user cares about moved); the
Executive decides what to do. Spatial never deliberates. Duck-typed + guarded; a no-op
when no executive is wired.
"""

from __future__ import annotations

import logging

log = logging.getLogger("friday.services.executive")


class ExecutiveService:
    name = "executive"

    def __init__(self, executive=None) -> None:
        self._exec = executive
        self._sent = 0

    def notify(self, payload: dict) -> None:
        if self._exec is None:
            return
        for method in ("on_spatial_event", "on_event", "notify", "observe", "think"):
            fn = getattr(self._exec, method, None)
            if callable(fn):
                try:
                    fn(payload)
                    self._sent += 1
                except Exception:  # noqa: BLE001 — never let executive failures break spatial
                    log.debug("executive notify via %s failed", method, exc_info=True)
                return

    def health(self) -> dict:
        return {"status": "ok", "attached": self._exec is not None, "notifications": self._sent}
