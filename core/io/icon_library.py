"""
core/io/icon_library.py — she LEARNS icons from you.

OCR reads text; a vision model could name any icon but needs training. Between
those sits the human way: show her an icon once ("remember this as the settings
icon") and she keeps a small picture of it, then finds and clicks it by name
later. Point-and-teach — local, no model, honest.

Storage: data/icons/<slug>.png plus an index.json of name→slug. Override the
directory with env FRIDAY_ICON_DIR (tests pass an explicit root).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.io.icon_library")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _ROOT / "data" / "icons"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "icon"


class IconLibrary:
    """A tiny named store of icon template images."""

    def __init__(self, root=None) -> None:
        env = os.environ.get("FRIDAY_ICON_DIR")
        self.root = Path(root) if root else (Path(env) if env else _DEFAULT_DIR)

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load_index(self) -> dict:
        try:
            return json.loads(self._index_path().read_text("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_index(self, idx: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(idx, indent=2), encoding="utf-8")

    def names(self) -> list:
        return sorted(self._load_index().keys())

    def path_for(self, name: str) -> Optional[str]:
        slug = self._load_index().get((name or "").lower().strip())
        if not slug:
            return None
        p = self.root / f"{slug}.png"
        return str(p) if p.exists() else None

    def save(self, name: str, image) -> str:
        """Persist a PIL image as the template for `name`; returns its path."""
        self.root.mkdir(parents=True, exist_ok=True)
        slug = _slug(name)
        path = self.root / f"{slug}.png"
        image.save(path)
        idx = self._load_index()
        idx[(name or "").lower().strip()] = slug
        self._save_index(idx)
        return str(path)

    def forget(self, name: str) -> bool:
        idx = self._load_index()
        slug = idx.pop((name or "").lower().strip(), None)
        if slug is None:
            return False
        try:
            (self.root / f"{slug}.png").unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            log.debug("forget icon file failed", exc_info=True)
        self._save_index(idx)
        return True
