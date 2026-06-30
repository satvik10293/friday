"""
core/services/configuration_service.py — FRIDAY V3 (M16)
ConfigurationService — the single source of configuration. Nothing else hardcodes
values: callers read them here by dotted path (e.g. `get("spatial.confidence_threshold")`)
or by section. Backed by a plain dict (a slice of friday_config.json), so it is portable,
testable, and has no I/O or hardcoded paths.
"""

from __future__ import annotations

from typing import Any


class ConfigurationService:
    name = "configuration"

    def __init__(self, config: Any = None) -> None:
        self._config: dict = dict(config or {})

    def get(self, path: str, default: Any = None) -> Any:
        """Resolve a dotted path (`a.b.c`) or return `default` if absent."""
        node: Any = self._config
        for part in (path or "").split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def section(self, name: str) -> dict:
        sec = self._config.get(name)
        return dict(sec) if isinstance(sec, dict) else {}

    def set(self, path: str, value: Any) -> None:
        parts = (path or "").split(".")
        node = self._config
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if parts:
            node[parts[-1]] = value

    def all(self) -> dict:
        return dict(self._config)

    def health(self) -> dict:
        return {"status": "ok", "sections": sorted(self._config.keys())}
