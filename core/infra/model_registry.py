"""
core/infra/model_registry.py — FRIDAY 4.0
Read-only access to the version-controlled model registry under `models/`.

The registry stores model *metadata* in Git (configs, provenance, milestone,
version) — never weights. This module lets FRIDAY (and a future Mission Control)
answer "which models do I use, where do they live, and which milestone introduced
each?" without shelling out to anything. Pure reads; side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.infra.model_registry")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODELS_DIR = _ROOT / "models"


class ModelRegistry:
    def __init__(self, models_dir: Optional[str | Path] = None) -> None:
        self.models_dir = Path(models_dir) if models_dir else _DEFAULT_MODELS_DIR
        self._registry_path = self.models_dir / "registry.json"

    # ── loading ────────────────────────────────────────────────────────────────
    def _load_registry(self) -> dict:
        if not self._registry_path.exists():
            return {"models": []}
        try:
            return json.loads(self._registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("model registry unreadable (%s)", e)
            return {"models": []}

    def list_models(self) -> list[dict]:
        """All registered models (from registry.json), each enriched with the
        on-disk metadata.json if present."""
        out = []
        for entry in self._load_registry().get("models", []):
            meta = self._metadata_for(entry)
            out.append({**entry, **meta} if meta else dict(entry))
        return out

    def _metadata_for(self, entry: dict) -> Optional[dict]:
        rel = entry.get("path")
        if not rel:
            return None
        path = self._resolve(rel) / "metadata.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _resolve(self, rel: str) -> Path:
        """Resolve a registry `path`. Absolute paths win; otherwise try the bases
        that make sense — the repo root (paths like 'models/llm/x'), the models dir
        (paths like 'llm/x'), and the models dir's parent — returning the first that
        exists (or the repo-root candidate as the default)."""
        p = Path(rel)
        if p.is_absolute():
            return p
        candidates = [_ROOT / rel, self.models_dir / rel, self.models_dir.parent / rel]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    # ── queries ────────────────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[dict]:
        for m in self.list_models():
            if m.get("name") == name:
                return m
        return None

    def by_category(self, category: str) -> list[dict]:
        return [m for m in self.list_models() if m.get("category") == category]

    def categories(self) -> list[str]:
        return sorted({m.get("category", "") for m in self.list_models() if m.get("category")})

    def names(self) -> list[str]:
        return [m.get("name", "") for m in self.list_models()]

    def milestone_of(self, name: str) -> Optional[str]:
        m = self.get(name)
        return m.get("milestone_introduced") if m else None

    def weights_excluded(self) -> list[str]:
        """Models whose weights are deliberately NOT in Git."""
        return [m["name"] for m in self.list_models() if not m.get("weights_tracked")]

    def config_path(self, name: str) -> Optional[Path]:
        m = self.get(name)
        if not m or not m.get("path"):
            return None
        path = self._resolve(m["path"]) / "config.yaml"
        return path if path.exists() else None

    # ── diagnostics ────────────────────────────────────────────────────────────
    def health(self) -> dict:
        models = self.list_models()
        by_cat: dict[str, int] = {}
        for m in models:
            by_cat[m.get("category", "?")] = by_cat.get(m.get("category", "?"), 0) + 1
        return {
            "status": "ok" if self._registry_path.exists() else "missing_registry",
            "registry": str(self._registry_path),
            "total": len(models),
            "by_category": by_cat,
            "weights_in_git": sum(1 for m in models if m.get("weights_tracked")),
            "weights_excluded": len(self.weights_excluded()),
        }


def get_model_registry(models_dir: Optional[str | Path] = None) -> ModelRegistry:
    return ModelRegistry(models_dir)
