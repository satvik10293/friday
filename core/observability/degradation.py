"""
core/observability/degradation.py — FRIDAY's honest record of what isn't working.

FRIDAY degrades gracefully: hundreds of `except Exception` sites keep her alive
when a subsystem misbehaves, and the staged boot continues past a stage that
fails or is skipped. That resilience has a cost — a "green" boot can quietly
hide a subsystem that never came up. A mind you can trust has to *know* what it
can't do and be able to say so.

This is the single place that remembers that. Any subsystem records a
degradation here; boot feeds it every skipped/failed stage automatically; and
`status()` / diagnostics read `report()` so "running degraded" is visible
instead of implicit.

    from core.observability import note_degraded, get_degradation_ledger

    try:
        camera.open()
    except Exception as e:                    # noqa: BLE001
        note_degraded("vision", "camera not found", exc=e)
        ...                                   # still degrade gracefully

    get_degradation_ledger().report()
    # {"healthy": False, "failed": 0, "degraded": 1, "skipped": 0,
    #  "subsystems": {"vision": {...}}, "recent": [...]}

Import is side-effect free. The ledger is process-wide and thread-safe; it never
raises out of `record()` (an observability layer must not be able to break the
thing it observes).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

# Severity ladder. "failed" and "degraded" flip health to False; "skipped" is an
# optional subsystem that is legitimately absent (e.g. an opt-out), surfaced but
# not counted against health on its own.
FAILED = "failed"
DEGRADED = "degraded"
SKIPPED = "skipped"
_SEVERITIES = (FAILED, DEGRADED, SKIPPED)

_RECENT_MAX = 64


@dataclass(frozen=True)
class DegradationEvent:
    subsystem: str
    detail: str
    severity: str
    exc_type: Optional[str]
    ts: float

    def to_dict(self) -> dict:
        return {"subsystem": self.subsystem, "detail": self.detail,
                "severity": self.severity, "exc_type": self.exc_type,
                "ts": round(self.ts, 3)}


class DegradationLedger:
    """Process-wide, thread-safe tally of subsystem degradations."""

    def __init__(self, *, recent_max: int = _RECENT_MAX) -> None:
        self._lock = threading.Lock()
        self._recent: Deque[DegradationEvent] = deque(maxlen=recent_max)
        # subsystem -> {"count", "last_ts", "last_detail", "last_severity",
        #               "last_exc", "by_severity": {sev: n}}
        self._subsystems: Dict[str, dict] = {}

    def record(self, subsystem: str, detail: str = "", *,
               exc: Optional[BaseException] = None,
               severity: str = DEGRADED) -> None:
        """Record that `subsystem` is not fully working. Never raises."""
        try:
            sev = severity if severity in _SEVERITIES else DEGRADED
            name = str(subsystem or "unknown")
            text = str(detail or "")
            exc_type = type(exc).__name__ if exc is not None else None
            if not text and exc is not None:
                text = f"{exc_type}: {exc}"
            ev = DegradationEvent(name, text, sev, exc_type, time.time())
            with self._lock:
                self._recent.append(ev)
                s = self._subsystems.get(name)
                if s is None:
                    s = {"count": 0, "last_ts": 0.0, "last_detail": "",
                         "last_severity": "", "last_exc": None,
                         "by_severity": {}}
                    self._subsystems[name] = s
                s["count"] += 1
                s["last_ts"] = ev.ts
                s["last_detail"] = text
                s["last_severity"] = sev
                s["last_exc"] = exc_type
                s["by_severity"][sev] = s["by_severity"].get(sev, 0) + 1
        except Exception:  # noqa: BLE001 — observability must never break its caller
            pass

    def healthy(self) -> bool:
        """True when nothing is failed or degraded (skipped-only is still healthy)."""
        with self._lock:
            for s in self._subsystems.values():
                bs = s["by_severity"]
                if bs.get(FAILED) or bs.get(DEGRADED):
                    return False
        return True

    def report(self) -> dict:
        """A snapshot for status()/diagnostics: overall health + per-subsystem
        breakdown + the most-recent events (newest first)."""
        with self._lock:
            counts = {FAILED: 0, DEGRADED: 0, SKIPPED: 0}
            subsystems: Dict[str, dict] = {}
            for name, s in self._subsystems.items():
                for sev, n in s["by_severity"].items():
                    counts[sev] = counts.get(sev, 0) + n
                subsystems[name] = {
                    "count": s["count"],
                    "last_severity": s["last_severity"],
                    "last_detail": s["last_detail"],
                    "last_exc": s["last_exc"],
                    "last_ts": round(s["last_ts"], 3),
                    "by_severity": dict(s["by_severity"]),
                }
            recent = [ev.to_dict() for ev in reversed(self._recent)]
        healthy = counts.get(FAILED, 0) == 0 and counts.get(DEGRADED, 0) == 0
        return {
            "healthy": healthy,
            "failed": counts.get(FAILED, 0),
            "degraded": counts.get(DEGRADED, 0),
            "skipped": counts.get(SKIPPED, 0),
            "subsystems": subsystems,
            "recent": recent,
        }

    def summary_line(self) -> str:
        """One-line human summary, e.g. 'all subsystems nominal' or
        '2 failed, 1 degraded, 3 skipped'."""
        r = self.report()
        if r["healthy"] and r["skipped"] == 0:
            return "all subsystems nominal"
        parts = []
        for label in (FAILED, DEGRADED, SKIPPED):
            if r[label]:
                parts.append(f"{r[label]} {label}")
        return ", ".join(parts) if parts else "all subsystems nominal"

    def clear(self) -> None:
        """Reset the ledger (tests, or a fresh boot)."""
        with self._lock:
            self._recent.clear()
            self._subsystems.clear()


_ledger: Optional[DegradationLedger] = None
_ledger_lock = threading.Lock()


def get_degradation_ledger() -> DegradationLedger:
    """The process-wide ledger (lazily created, so import stays side-effect free)."""
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = DegradationLedger()
    return _ledger


def note_degraded(subsystem: str, detail: str = "", *,
                  exc: Optional[BaseException] = None,
                  severity: str = DEGRADED) -> None:
    """Convenience: record a degradation on the process-wide ledger.

    Drop this into an `except` block that swallows-and-continues so the swallow
    stops being silent:

        except Exception as e:            # noqa: BLE001
            note_degraded("voice.tts", "edge-tts unavailable", exc=e)
    """
    get_degradation_ledger().record(subsystem, detail, exc=exc, severity=severity)
