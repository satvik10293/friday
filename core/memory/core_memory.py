"""
core/memory/core_memory.py — FRIDAY 5.x (M43)
Core memory: the ambient layer One Memory doesn't have. One Memory is
retrieval memory — a fact surfaces only when the query embeds near it. Core
memory is standing memory: a small set of durable, typed, human-readable facts
(who Satvik is, corrections he has given, active projects) whose index rides
into EVERY reasoning turn regardless of query similarity.

Modelled on the file-based memory Claude Code keeps per project:

  · one markdown file per fact, frontmatter carries identity and policy:
        name         kebab-case slug — the fact's identity (update, don't
                     duplicate: saving the same name overwrites)
        description  one line, used for relevance ranking and the index
        type         user | feedback | project | reference
        private      true (default, fail-safe) → never leaves the box;
                     false → may ground the cloud reasoner
  · MEMORY.md — one line per memory; the always-loaded index
  · files are plain markdown: Satvik curates them directly in any editor
    (flip `private`, fix a fact, delete a stale one — the store obeys)

Storage: data/core_memory/ (override with env FRIDAY_CORE_MEMORY).
The store is the directory; MEMORY.md is derived and rebuilt from the files,
so hand-edits win over anything FRIDAY wrote.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.memory.core")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _ROOT / "data" / "core_memory"
_INDEX_NAME = "MEMORY.md"
_TYPES = ("user", "feedback", "project", "reference")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset(
    ("a an and are as at be but by for from has have i in is it its me my of "
     "on that the this to was we what which who will with you your").split())


def _slugify(text: str, max_words: int = 6) -> str:
    words = [w for w in _SLUG_RE.sub(" ", (text or "").lower()).split()
             if w not in _STOPWORDS][:max_words] or \
            _SLUG_RE.sub(" ", (text or "").lower()).split()[:max_words]
    return "-".join(words) or "memory"


def _keywords(text: str) -> set:
    return {w for w in _SLUG_RE.sub(" ", (text or "").lower()).split()
            if len(w) > 2 and w not in _STOPWORDS}


class CoreMemory:
    """Directory-backed standing memory. Files are the source of truth;
    MEMORY.md is rebuilt from them so human edits always win."""

    def __init__(self, root: Optional[Path] = None) -> None:
        env = os.environ.get("FRIDAY_CORE_MEMORY", "").strip()
        self.root = Path(root) if root else (Path(env) if env else _DEFAULT_DIR)
        self._lock = threading.Lock()

    # ── parsing ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _parse(path: Path) -> Optional[dict]:
        """Parse one memory file. Frontmatter is a flat `key: value` block —
        forgiving by design, since Satvik edits these by hand."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        meta = {"name": path.stem, "description": "", "type": "user",
                "private": True}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" not in line:
                        continue
                    key, _, val = line.partition(":")
                    key, val = key.strip().lower(), val.strip()
                    if key == "name" and val:
                        meta["name"] = _slugify(val, max_words=10)
                    elif key == "description":
                        meta["description"] = val
                    elif key == "type" and val in _TYPES:
                        meta["type"] = val
                    elif key == "private":
                        meta["private"] = val.lower() not in ("false", "no", "0")
                body = parts[2].strip()
        meta["body"] = body.strip()
        return meta

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.glob("*.md") if p.name != _INDEX_NAME)

    def all(self) -> list[dict]:
        return [m for m in (self._parse(p) for p in self._files()) if m]

    def get(self, name: str) -> Optional[dict]:
        path = self.root / f"{_slugify(name, max_words=10)}.md"
        return self._parse(path) if path.exists() else None

    # ── writing ──────────────────────────────────────────────────────────────────
    def save(self, name: str, description: str, body: str, *,
             type: str = "user", private: bool = True) -> str:
        """Create or update (same name = same fact — no duplicates)."""
        slug = _slugify(name, max_words=10)
        kind = type if type in _TYPES else "user"
        text = (f"---\n"
                f"name: {slug}\n"
                f"description: {(description or '').strip()[:200]}\n"
                f"type: {kind}\n"
                f"private: {'true' if private else 'false'}\n"
                f"updated: {time.strftime('%Y-%m-%d')}\n"
                f"---\n\n"
                f"{(body or '').strip()}\n")
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / f"{slug}.md").write_text(text, encoding="utf-8")
            self._rebuild_index()
        log.info("core memory saved: %s (%s)", slug, kind)
        return slug

    def delete(self, name: str) -> bool:
        path = self.root / f"{_slugify(name, max_words=10)}.md"
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
            self._rebuild_index()
        log.info("core memory deleted: %s", path.stem)
        return True

    def forget_matching(self, query: str) -> list[str]:
        """Honour a forget request: remove the single best-matching memory
        (deliberately conservative — bulk wipes are a Mission Control act)."""
        hits = self.relevant(query, k=1)
        return [h["name"] for h in hits if self.delete(h["name"])]

    def _rebuild_index(self) -> None:
        """MEMORY.md is derived: one line per memory, newest knowledge last.
        Called under the lock."""
        lines = ["# FRIDAY core memory — one line per standing fact",
                 "# (files are the source of truth; edit them, not this index)",
                 ""]
        for m in self.all():
            flag = "" if m["private"] else " [shareable]"
            lines.append(f"- [{m['name']}]({m['name']}.md) — "
                         f"{m['type']}{flag}: {m['description'] or m['body'][:80]}")
        (self.root / _INDEX_NAME).write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    # ── reading ──────────────────────────────────────────────────────────────────
    def relevant(self, query: str, k: int = 3) -> list[dict]:
        """The k memories most relevant to the query (keyword overlap — the
        store is small by design, a linear scan is the honest implementation)."""
        qk = _keywords(query)
        if not qk:
            return []
        scored = []
        for m in self.all():
            mk = _keywords(f"{m['name']} {m['description']} {m['body']}")
            overlap = len(qk & mk)
            if overlap:
                scored.append((overlap / len(qk), m))
        scored.sort(key=lambda s: -s[0])
        return [m for _, m in scored[:k]]

    def render_block(self, *, include_private: bool, query: str = "",
                     max_chars: int = 1200) -> str:
        """The ambient block for a reasoning turn: every memory's one-line hook,
        plus full bodies of the ones relevant to the query. include_private=False
        is the cloud boundary — private memories vanish entirely."""
        memories = [m for m in self.all() if include_private or not m["private"]]
        if not memories:
            return ""
        relevant_names = {m["name"] for m in self.relevant(query, k=3)
                          if include_private or not m["private"]} if query else set()
        lines = []
        for m in memories:
            lines.append(f"- ({m['type']}) {m['description'] or m['body'][:80]}")
            if m["name"] in relevant_names and m["body"] and \
                    m["body"] != m["description"]:
                lines.append(f"    {m['body'][:300]}")
        return "\n".join(lines)[:max_chars]

    def status(self) -> dict:
        memories = self.all()
        by_type: dict = {}
        for m in memories:
            by_type[m["type"]] = by_type.get(m["type"], 0) + 1
        return {"count": len(memories), "by_type": by_type,
                "shareable": sum(1 for m in memories if not m["private"]),
                "root": str(self.root)}


# ── singleton (matches the get_teacher / get_knowledge_service pattern) ──────────
_instance: Optional[CoreMemory] = None
_instance_lock = threading.Lock()


def get_core_memory() -> CoreMemory:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = CoreMemory()
        return _instance
