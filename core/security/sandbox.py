"""
core/security/sandbox.py — FRIDAY 4.0
Sandbox framework. Minimal today (thread-isolated execution with a time budget),
but a stable seam for future resource limits and container isolation. The executor
sandboxes HIGH/CRITICAL-risk skills; SAFE/low-risk skills run inline for speed.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from core.skills.exceptions import SandboxTimeout

log = logging.getLogger("friday.security.sandbox")


class Sandbox(ABC):
    @abstractmethod
    def run_sync(self, fn: Callable[[], Any], timeout: Optional[float] = None) -> Any:
        ...


class NullSandbox(Sandbox):
    """No isolation — runs inline. Used for trusted/low-risk skills."""

    def run_sync(self, fn: Callable[[], Any], timeout: Optional[float] = None) -> Any:
        return fn()


class ThreadSandbox(Sandbox):
    """Runs the callable in a worker thread with a hard wall-clock timeout.

    Note: Python cannot forcibly kill a thread, so a timed-out skill's thread may
    linger (daemon) until it returns; we surface SandboxTimeout immediately. This
    is the seam where process/container isolation and resource caps will land.
    """

    def run_sync(self, fn: Callable[[], Any], timeout: Optional[float] = None) -> Any:
        box: dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["value"] = fn()
            except Exception as e:  # propagate to caller after join
                box["error"] = e

        t = threading.Thread(target=_worker, daemon=True, name="friday-sandbox")
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise SandboxTimeout(f"skill exceeded {timeout}s sandbox budget")
        if "error" in box:
            raise box["error"]
        return box.get("value")
