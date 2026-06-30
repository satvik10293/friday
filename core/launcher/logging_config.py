"""
core/launcher/logging_config.py — FRIDAY V3 (M20)
Structured, rotating logging for production. Configures console + rotating file handlers
(startup / runtime / error streams folded into one rotating file by default), with a
plain console formatter and a richer file formatter. Idempotent and side-effect-free until
called — importing this module configures nothing.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_CONSOLE_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_FILE_FMT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
_configured = False


def configure_logging(*, log_dir: Optional[Path] = None, level: str = "INFO",
                      console: bool = True, max_bytes: int = 5_000_000,
                      backups: int = 5, debug: bool = False) -> dict:
    """Configure root logging with a rotating file handler (+ optional console). Returns a
    small report. Safe to call once at startup; repeat calls are no-ops."""
    global _configured
    root = logging.getLogger()
    lvl = logging.DEBUG if debug else getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(lvl)
    report: dict = {"level": logging.getLevelName(lvl), "handlers": []}

    if _configured:
        return {**report, "already_configured": True}

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(_CONSOLE_FMT))
        ch.setLevel(lvl)
        root.addHandler(ch)
        report["handlers"].append("console")

    if log_dir is not None:
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(Path(log_dir) / "friday.log", maxBytes=max_bytes,
                                     backupCount=backups, encoding="utf-8")
            fh.setFormatter(logging.Formatter(_FILE_FMT))
            fh.setLevel(lvl)
            root.addHandler(fh)
            # a dedicated error log so failures are easy to find
            eh = RotatingFileHandler(Path(log_dir) / "friday-error.log", maxBytes=max_bytes,
                                     backupCount=backups, encoding="utf-8")
            eh.setFormatter(logging.Formatter(_FILE_FMT))
            eh.setLevel(logging.ERROR)
            root.addHandler(eh)
            report["handlers"].extend(["file:friday.log", "file:friday-error.log"])
            report["rotation"] = {"max_bytes": max_bytes, "backups": backups}
        except OSError as e:
            report["file_error"] = str(e)

    _configured = True
    return report
