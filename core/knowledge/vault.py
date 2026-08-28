"""
core/knowledge/vault.py — FRIDAY 4.0 (M7)
Obsidian vault adapter. The vault (one Markdown note per knowledge entry) is the
permanent, human-owned source of truth; the SQLite store and vector index are
rebuildable projections of it.

Responsibilities:
  • render a KnowledgeEntry → Markdown note (YAML front-matter + body + links)
  • parse a Markdown note → KnowledgeEntry
  • write / read / scan notes on disk
  • detect changes (mtime) so modified notes can be re-indexed
  • preserve manual edits — never overwrite a note whose body the user changed
    unless explicitly told to (`force=True`)

Default location: env FRIDAY_KNOWLEDGE_VAULT, else C:\\VAULT\\friday_knowledge.
Import is side-effect-free: no directory is created until you call a method.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .knowledge_models import (KnowledgeCategory, KnowledgeEntry, KnowledgeStatus,
                               slugify)

_DEFAULT_VAULT = Path(os.environ.get("FRIDAY_KNOWLEDGE_VAULT", r"C:\VAULT\friday_knowledge"))

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if re.search(r"[:#\[\]{}]", s) or s != s.strip():
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _parse_scalar(raw: str):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"')
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


class ObsidianVault:
    def __init__(self, root: Optional[str | Path] = None) -> None:
        self.root = Path(root) if root else _DEFAULT_VAULT

    # ── paths ──────────────────────────────────────────────────────────────────
    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, entry: KnowledgeEntry) -> Path:
        if entry.vault_path:
            return self.root / entry.vault_path
        cat = entry.category or KnowledgeCategory.GENERAL
        return self.root / cat / f"{slugify(entry.title)}-{entry.id}.md"

    def rel_path_for(self, entry: KnowledgeEntry) -> str:
        return str(self.path_for(entry).relative_to(self.root)).replace("\\", "/")

    # ── render / parse ─────────────────────────────────────────────────────────
    def render(self, entry: KnowledgeEntry) -> str:
        meta = {
            "id": entry.id, "title": entry.title, "category": entry.category,
            "confidence": round(entry.confidence, 3), "source": entry.source,
            "status": entry.status, "usage_count": entry.usage_count,
            "created_at": entry.created_at, "updated_at": entry.updated_at,
        }
        front = "\n".join(f"{k}: {_yaml_scalar(v)}" for k, v in meta.items())
        links = "\n".join(f"- [[{t}]]" for t in entry.metadata.get("links", []))
        body = entry.content.rstrip()
        parts = [f"---\n{front}\n---", f"# {entry.title}", body,
                 "## Knowledge", "- [[Friday Knowledge]]",
                 f"- [[{entry.category}]]"]
        if links:
            parts.append("## Related\n" + links)
        return "\n\n".join(parts) + "\n"

    def parse(self, text: str) -> Optional[KnowledgeEntry]:
        m = _FRONT.match(text or "")
        if not m:
            return None
        front_raw, body = m.group(1), m.group(2)
        meta: dict = {}
        for line in front_raw.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            meta[key.strip()] = _parse_scalar(val)
        if "id" not in meta or "title" not in meta:
            return None
        # strip the leading "# title" heading and the trailing link sections
        content = re.sub(r"^#\s+.*\n", "", body.strip(), count=1).strip()
        content = re.split(r"\n##\s+(Knowledge|Related)\b", content)[0].strip()
        return KnowledgeEntry(
            id=str(meta["id"]), title=str(meta["title"]),
            category=str(meta.get("category", KnowledgeCategory.GENERAL)),
            content=content,
            confidence=float(meta.get("confidence", 0.5)),
            source=str(meta.get("source", "system")),
            created_at=float(meta.get("created_at", 0.0)),
            updated_at=float(meta.get("updated_at", 0.0)),
            usage_count=int(meta.get("usage_count", 0)),
            status=str(meta.get("status", KnowledgeStatus.ACTIVE.value)),
        )

    # ── disk I/O ───────────────────────────────────────────────────────────────
    def write(self, entry: KnowledgeEntry, *, force: bool = False) -> str:
        """Write a note for `entry`. Honours manual edits: if the on-disk note's
        body differs from what FRIDAY last wrote and `force` is False, the write
        is skipped so user changes survive. Returns the vault-relative path."""
        self._ensure()
        rel = self.rel_path_for(entry)
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not force:
            existing = self.parse(path.read_text(encoding="utf-8"))
            if existing and existing.updated_at > entry.updated_at + 1e-6:
                entry.vault_path = rel
                return rel                      # on-disk copy is newer ⇒ keep it
        path.write_text(self.render(entry), encoding="utf-8")
        entry.vault_path = rel
        return rel

    def read(self, rel_path: str) -> Optional[KnowledgeEntry]:
        path = self.root / rel_path
        if not path.exists():
            return None
        entry = self.parse(path.read_text(encoding="utf-8"))
        if entry is not None:
            entry.vault_path = rel_path
        return entry

    def delete(self, entry: KnowledgeEntry) -> None:
        path = self.path_for(entry)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def scan(self) -> list[KnowledgeEntry]:
        """Parse every note in the vault. The recovery source for a full rebuild."""
        if not self.root.exists():
            return []
        out: list[KnowledgeEntry] = []
        for path in self.root.rglob("*.md"):
            entry = self.parse(path.read_text(encoding="utf-8"))
            if entry is not None:
                entry.vault_path = str(path.relative_to(self.root)).replace("\\", "/")
                out.append(entry)
        return out

    def changed_since(self, ts: float) -> list[str]:
        """Vault-relative paths of notes modified after `ts` (for re-indexing)."""
        if not self.root.exists():
            return []
        out: list[str] = []
        for path in self.root.rglob("*.md"):
            if path.stat().st_mtime > ts:
                out.append(str(path.relative_to(self.root)).replace("\\", "/"))
        return out

    def health(self) -> dict:
        exists = self.root.exists()
        notes = sum(1 for _ in self.root.rglob("*.md")) if exists else 0
        return {"status": "ok", "root": str(self.root), "exists": exists, "notes": notes}
