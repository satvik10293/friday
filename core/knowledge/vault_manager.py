"""
core/knowledge/vault_manager.py — FRIDAY 4.0 (M8)
Obsidian vault organisation layer. Sits on top of the M7 ObsidianVault adapter and
gives the vault a coherent, navigable structure plus integrity checks.

Recommended structure:

    Vault/
      Programming/
      Projects/
      Goals/
      Reflections/
      Knowledge/
      Daily/

Additive: composes M7's ObsidianVault (render/parse/write/scan); does not modify it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .knowledge_models import KnowledgeCategory, KnowledgeEntry, slugify
from .vault import ObsidianVault

STANDARD_FOLDERS = ("Programming", "Projects", "Goals", "Reflections",
                    "Knowledge", "Daily")

# Map a knowledge category onto a top-level vault folder.
_CATEGORY_FOLDER = {
    KnowledgeCategory.PYTHON: "Programming",
    KnowledgeCategory.FLASK: "Programming",
    KnowledgeCategory.FASTAPI: "Programming",
    KnowledgeCategory.SQLITE: "Programming",
    KnowledgeCategory.OPENCV: "Programming",
    KnowledgeCategory.AI: "Programming",
    KnowledgeCategory.AUTOMATION: "Programming",
    KnowledgeCategory.PROJECT: "Projects",
    KnowledgeCategory.LESSON: "Reflections",
    KnowledgeCategory.SUMMARY: "Knowledge",
    KnowledgeCategory.GENERAL: "Knowledge",
}

_LINK = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class IntegrityReport:
    notes: int = 0
    folders: list = field(default_factory=list)
    broken_links: list = field(default_factory=list)   # list[dict]: {note, target}
    missing_id: list = field(default_factory=list)      # vault paths
    ok: bool = True

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class VaultManager:
    def __init__(self, vault: Optional[ObsidianVault] = None) -> None:
        self._vault = vault if vault is not None else ObsidianVault()

    @property
    def vault(self) -> ObsidianVault:
        return self._vault

    @property
    def root(self) -> Path:
        return self._vault.root

    # ── structure ──────────────────────────────────────────────────────────────
    def ensure_structure(self) -> list[str]:
        """Create the standard folder skeleton. Returns the folders ensured."""
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in STANDARD_FOLDERS:
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        return list(STANDARD_FOLDERS)

    @staticmethod
    def folder_for(category: str) -> str:
        return _CATEGORY_FOLDER.get(category, "Knowledge")

    def _route(self, entry: KnowledgeEntry) -> None:
        """Assign a structured vault_path under the category's top-level folder."""
        if entry.vault_path:
            return
        folder = self.folder_for(entry.category)
        entry.vault_path = f"{folder}/{slugify(entry.title)}-{entry.id}.md"

    # ── notes ──────────────────────────────────────────────────────────────────
    def create_note(self, entry: KnowledgeEntry, *, force: bool = False) -> str:
        self.ensure_structure()
        self._route(entry)
        return self._vault.write(entry, force=force)

    def update_note(self, entry: KnowledgeEntry) -> str:
        self._route(entry)
        return self._vault.write(entry, force=True)

    def backlinks(self, entry: KnowledgeEntry) -> list[str]:
        """Concepts this note links out to (from metadata + inline [[links]])."""
        out = list(entry.metadata.get("links", []))
        out += _LINK.findall(entry.content or "")
        # de-dupe, drop the structural backlinks the renderer always adds
        seen, result = set(), []
        for name in out:
            if name in ("Friday Knowledge", entry.category):
                continue
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ── integrity ──────────────────────────────────────────────────────────────
    def integrity_check(self) -> IntegrityReport:
        """Scan the vault: count notes, detect notes missing an id, and find
        [[links]] that point at a title no note in the vault provides."""
        report = IntegrityReport()
        if not self.root.exists():
            return report
        report.folders = [p.name for p in self.root.iterdir() if p.is_dir()]
        entries = self._vault.scan()
        report.notes = len(entries)
        titles = {e.title for e in entries}
        for e in entries:
            if not e.id:
                report.missing_id.append(e.vault_path or e.title)
            for target in _LINK.findall(e.content or ""):
                if target in ("Friday Knowledge", e.category):
                    continue
                if target not in titles:
                    report.broken_links.append({"note": e.title, "target": target})
        # notes referenced via metadata links count too
        for e in entries:
            for target in e.metadata.get("links", []):
                if target not in titles and target not in ("Friday Knowledge",):
                    report.broken_links.append({"note": e.title, "target": target})
        report.ok = not (report.missing_id or report.broken_links)
        return report

    def stats(self) -> dict:
        folders = {}
        if self.root.exists():
            for folder in STANDARD_FOLDERS:
                p = self.root / folder
                folders[folder] = sum(1 for _ in p.rglob("*.md")) if p.exists() else 0
        return {"root": str(self.root), "folders": folders,
                "total_notes": sum(folders.values())}

    def health(self) -> dict:
        report = self.integrity_check()
        return {"status": "ok" if report.ok else "degraded",
                "notes": report.notes, "broken_links": len(report.broken_links),
                "missing_id": len(report.missing_id)}
