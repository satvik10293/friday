"""
core/observability/logging_setup.py — FRIDAY 4.0
Structured logging. Optional JSON formatter that injects the current trace id,
so every log line can be correlated with a Decision Log row.

Call configure() once at boot (it is NOT called on import — side-effect free).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional, TextIO

from .tracing import get_trace_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        tid = get_trace_id()
        if tid:
            payload["trace"] = tid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(level: int = logging.INFO, json_format: bool = False,
              stream: Optional[TextIO] = None) -> logging.Logger:
    """Configure root logging. Replaces existing handlers (idempotent-ish)."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        JsonFormatter() if json_format
        else logging.Formatter("%(levelname)s [%(name)s] %(message)s")
    )
    root.addHandler(handler)
    return root
