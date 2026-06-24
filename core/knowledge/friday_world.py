"""
friday_world.py — Layer 2: World Model
=======================================
Vault-backed, on-demand knowledge store. Knowledge lives as plain markdown
notes in an Obsidian-style VAULT (one file per managed entry, with YAML-style
frontmatter). Semantic search is provided by FAISS; keyword search is the
always-available fallback. Wikipedia summaries are fetched on demand and
written into the vault — there is NO background download / ingest loop.

Architecture position:
  Layer 2 — WORLD MODEL  (knowledge persistence, independent of query cycle)
  Feeds into → Layer 7: Neural (pre-fetched context slots)

Design rules:
  • No background downloading — knowledge is added on demand only.
  • Each managed entry is one markdown note in the project-root vault.
  • The user's own Obsidian notes (no fact_id frontmatter) are never touched.
  • FAISS semantic search with graceful keyword-only fallback.
  • Vault knowledge persists (no TTL); only news categories expire.
  • All sources are free / no API keys required.
"""

import os
import re
import sys
import json
import time
import math
import hashlib
import logging
import argparse
import threading
import subprocess
import dataclasses
from datetime import datetime, timedelta, timezone

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _utcnow_iso() -> str:
    return _utcnow().replace(tzinfo=None).isoformat()  # naive ISO
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field, asdict

# ── optional heavy deps (lazy-loaded) ────────────────────────────────────────
try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    import faiss
    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False

# ── project root on sys.path ──────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parents[1]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORLD] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("friday.world")

# ── constants ─────────────────────────────────────────────────────────────────
WORLD_DIR      = _HERE / "world_data"               # FAISS sidecar + stats
VAULT_DIR      = Path(os.environ.get("FRIDAY_VAULT", r"C:\VAULT\satvik"))  # Obsidian vault (markdown notes); override via FRIDAY_VAULT
STATS_PATH     = WORLD_DIR / "world_stats.json"
FAISS_PATH     = WORLD_DIR / "world_faiss.index"
FAISS_META     = WORLD_DIR / "world_faiss_meta.json"
QUOTA_BYTES    = 2 * 1024 * 1024 * 1024   # 2 GB hard cap
EMBED_DIM      = 384                        # all-MiniLM-L6-v2
MIN_FACT_LEN   = 40                         # ignore tiny fragments
MAX_FACT_LEN   = 1500                       # truncate huge blobs

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data structures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class WorldEntry:
    fact_id:    str   = ""
    source:     str   = ""
    category:   str   = ""
    title:      str   = ""
    content:    str   = ""
    url:        str   = ""
    relevance:  float = 0.5
    fetched_at: str   = field(default_factory=_utcnow_iso)
    expires_at: str   = ""        # ISO string; empty = never expires
    embed_idx:  int   = -1        # row in FAISS index (-1 = not embedded)

    def __post_init__(self):
        if not self.fact_id:
            self.fact_id = hashlib.sha256(
                f"{self.source}{self.title}{self.content[:80]}".encode()
            ).hexdigest()[:16]
        if not self.expires_at:
            # Only news categories expire; everything else is persistent
            # vault knowledge → leave expires_at empty (never expires).
            if self.category in ("tech", "world", "finance", "sports"):
                self.expires_at = (
                    _utcnow() + timedelta(days=2)
                ).replace(tzinfo=None).isoformat()
            # else: leave empty → never expires (persistent vault knowledge)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Vault store — markdown notes with YAML-style frontmatter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Frontmatter fields written for every managed note, in order.
_FRONTMATTER_FIELDS = [
    "fact_id", "source", "category", "title", "url",
    "relevance", "fetched_at", "expires_at", "embed_idx",
]

# Keys returned to callers (never includes the internal _path).
_PUBLIC_KEYS = [
    "fact_id", "source", "category", "title", "content", "url",
    "relevance", "fetched_at", "expires_at", "embed_idx",
]

# Obsidian linking: every managed note ends with a "**Linked:**" footer of
# [[wikilinks]] so the notes form a connected graph. The footer is appended on
# serialize and stripped on parse, so stored `content` stays clean.
_KNOWLEDGE_HUB  = "Friday Knowledge"          # central hub every note links to
_LINKS_SENTINEL = "\n\n---\n**Linked:** "     # marks the start of the link footer

# Characters that are invalid in Windows filenames.
_WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _slugify(title: str) -> str:
    """Title → safe, collapsed slug (~48 chars), 'note' fallback if empty."""
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)        # strip non-word chars (keep spaces/-)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    s = s[:48].strip("-")
    s = _WIN_INVALID.sub("", s)            # belt-and-suspenders for Windows
    return s or "note"


class VaultStore:
    """Markdown-vault knowledge store. Same public API as the old WorldDB.

    Each managed entry is one markdown note (frontmatter + body content).
    Notes lacking a `fact_id` in frontmatter are the user's own Obsidian
    notes and are never read into the cache, modified, or deleted.
    """

    def __init__(self, vault_dir: Path = VAULT_DIR):
        self._dir = Path(vault_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}   # fact_id → frontmatter + content + _path
        self._load_all()

    # ── markdown serialize / parse ──────────────────────────────────────────
    @staticmethod
    def _serialize(rec: dict) -> str:
        lines = ["---"]
        for key in _FRONTMATTER_FIELDS:
            val = rec.get(key, "")
            if val is None:
                val = ""
            lines.append(f"{key}: {val}")
        lines.append("---")
        lines.append("")
        body  = (rec.get("content", "") or "").rstrip()
        links = VaultStore._link_targets(rec)
        if links:
            body = body + _LINKS_SENTINEL + " · ".join(links)
        lines.append(body)
        return "\n".join(lines)

    @staticmethod
    def _link_targets(rec: dict) -> list[str]:
        """Wikilink targets that connect this note into the Obsidian graph."""
        targets: list[str] = []
        title = str(rec.get("title", ""))
        # Facts are titled "Subject — predicate"; link the subject as a concept node.
        if " — " in title:
            subj = re.sub(r'[\[\]#^|:\\/]', "", title.split(" — ", 1)[0]).strip()
            if subj and len(subj) <= 40:
                targets.append(subj)
        targets.append(_KNOWLEDGE_HUB)
        seen: set = set()
        links: list[str] = []
        for t in targets:
            key = t.lower()
            if t and key not in seen:
                seen.add(key)
                links.append(f"[[{t}]]")
        return links

    @staticmethod
    def _parse(text: str) -> Optional[dict]:
        """Parse a managed note. Returns None if no valid frontmatter/fact_id."""
        # Find the first two '---' delimiters (each on its own line).
        lines = text.splitlines()
        delim_idxs = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
        if len(delim_idxs) < 2:
            return None
        first, second = delim_idxs[0], delim_idxs[1]
        fm_lines = lines[first + 1:second]
        body = "\n".join(lines[second + 1:]).strip()
        # Strip the appended "**Linked:**" footer so stored content stays clean.
        cut = body.find(_LINKS_SENTINEL)
        if cut != -1:
            body = body[:cut].strip()

        rec: dict = {}
        for ln in fm_lines:
            if ": " in ln:
                key, val = ln.split(": ", 1)
                rec[key.strip()] = val.strip()
            elif ln.rstrip().endswith(":"):
                key = ln.rstrip()[:-1].strip()
                if key:
                    rec[key] = ""
        if not rec.get("fact_id"):
            return None

        # Coerce numeric fields.
        try:
            rec["relevance"] = float(rec.get("relevance", 0.5))
        except (TypeError, ValueError):
            rec["relevance"] = 0.5
        try:
            rec["embed_idx"] = int(rec.get("embed_idx", -1))
        except (TypeError, ValueError):
            rec["embed_idx"] = -1

        # Ensure all public keys exist.
        for k in ("source", "category", "title", "url", "fetched_at", "expires_at"):
            rec.setdefault(k, "")
        rec["content"] = body
        return rec

    # ── load ────────────────────────────────────────────────────────────────
    def _load_all(self):
        for path in self._dir.glob("*.md"):
            try:
                rec = self._parse(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if rec is None:
                continue   # user's own note (no fact_id) — never touch it
            rec["_path"] = path
            self._cache[rec["fact_id"]] = rec

    # ── helpers ─────────────────────────────────────────────────────────────
    def _path_for(self, fact_id: str, title: str) -> Path:
        slug = _slugify(title)
        return self._dir / f"{slug}-{fact_id[:8]}.md"

    @staticmethod
    def _is_expired(rec: dict) -> bool:
        exp = rec.get("expires_at", "")
        if not exp:
            return False
        try:
            # expires_at is stored as naive UTC (see _utcnow_iso) — compare in UTC.
            return datetime.fromisoformat(exp) < _utcnow().replace(tzinfo=None)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _public(rec: dict) -> dict:
        return {k: rec.get(k, "") for k in _PUBLIC_KEYS}

    def _write_note(self, rec: dict):
        """Serialize and write a managed note. rec must contain '_path'."""
        path: Path = rec["_path"]
        path.write_text(self._serialize(rec), encoding="utf-8")

    # ── write ───────────────────────────────────────────────────────────────
    def upsert(self, entry: WorldEntry) -> bool:
        """Insert or update. Returns True if new entry."""
        data = dataclasses.asdict(entry)
        with self._lock:
            is_new = entry.fact_id not in self._cache
            if is_new:
                path = self._path_for(entry.fact_id, entry.title)
            else:
                # Reuse the existing note's path so we don't orphan a file
                # when the title (and thus slug) changes.
                path = self._cache[entry.fact_id].get("_path") \
                    or self._path_for(entry.fact_id, entry.title)
            rec = dict(data)
            rec["_path"] = path
            self._write_note(rec)
            self._cache[entry.fact_id] = rec
            return is_new

    def update_embed_idx(self, fact_id: str, idx: int):
        with self._lock:
            rec = self._cache.get(fact_id)
            if rec is None:
                return
            rec["embed_idx"] = idx
            self._write_note(rec)

    # ── read ────────────────────────────────────────────────────────────────
    def search_keyword(self, query: str, limit: int = 8) -> list[dict]:
        words = query.lower().split()[:6]
        if not words:
            return []
        scored = []
        with self._lock:
            recs = list(self._cache.values())
        for rec in recs:
            if self._is_expired(rec):
                continue
            hay = (str(rec.get("title", "")) + " " + str(rec.get("content", ""))).lower()
            matches = sum(1 for w in words if w in hay)
            if matches >= 1:
                scored.append((matches, rec.get("relevance", 0.5), rec))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [self._public(rec) for _, _, rec in scored[:limit]]

    def get_recent(self, category: str = "", limit: int = 10) -> list[dict]:
        with self._lock:
            recs = list(self._cache.values())
        out = []
        for rec in recs:
            if self._is_expired(rec):
                continue
            if category and rec.get("category", "") != category:
                continue
            out.append(rec)
        out.sort(key=lambda r: str(r.get("fetched_at", "")), reverse=True)
        return [self._public(r) for r in out[:limit]]

    def get_by_ids(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        with self._lock:
            return [self._public(self._cache[i]) for i in ids if i in self._cache]

    # ── maintenance ─────────────────────────────────────────────────────────
    def purge_expired(self) -> int:
        with self._lock:
            expired = [fid for fid, rec in self._cache.items()
                       if self._is_expired(rec)]
            for fid in expired:
                rec = self._cache.pop(fid)
                p = rec.get("_path")
                if p:
                    try:
                        Path(p).unlink()
                    except OSError:
                        pass
            return len(expired)

    def count(self) -> int:
        with self._lock:
            return len(self._cache)

    def lowest_relevance_ids(self, n: int) -> list[str]:
        with self._lock:
            recs = sorted(self._cache.values(),
                          key=lambda r: r.get("relevance", 0.5))
        return [r["fact_id"] for r in recs[:n]]

    def delete_ids(self, ids: list[str]):
        if not ids:
            return
        with self._lock:
            for fid in ids:
                rec = self._cache.pop(fid, None)
                if rec is None:
                    continue
                p = rec.get("_path")
                if p:
                    try:
                        Path(p).unlink()
                    except OSError:
                        pass

    # ── stats (small JSON dict) ─────────────────────────────────────────────
    def _load_stats(self) -> dict:
        try:
            return json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_stat(self, key: str, value: str):
        with self._lock:
            STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
            stats = self._load_stats()
            stats[key] = value
            STATS_PATH.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    def get_stat(self, key: str, default: str = "") -> str:
        with self._lock:
            return self._load_stats().get(key, default)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FAISS vector index (optional — falls back to keyword search)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WorldIndex:
    """FAISS flat-L2 index over world entries. Thread-safe reads, locked writes."""

    def __init__(self):
        self._lock    = threading.Lock()
        self._index   = None          # faiss.IndexFlatL2
        self._id_map: list[str] = []  # row → fact_id
        self._model   = None
        self._ready   = False

        if _HAS_FAISS and _HAS_NUMPY:
            self._try_load()

    # ── init ──────────────────────────────────────────────────────────────────
    def _try_load(self):
        try:
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            if FAISS_PATH.exists() and FAISS_META.exists():
                self._index  = faiss.read_index(str(FAISS_PATH))
                self._id_map = json.loads(FAISS_META.read_text())
                log.info("FAISS index loaded — %d vectors", self._index.ntotal)
            else:
                self._index  = faiss.IndexFlatL2(EMBED_DIM)
                self._id_map = []
                log.info("FAISS index created fresh")
            self._ready = True
        except Exception as e:
            log.warning("FAISS init failed: %s — using keyword search only", e)
            self._ready = False

    # ── add ───────────────────────────────────────────────────────────────────
    def add(self, fact_id: str, text: str) -> int:
        """Embed text and add to index. Returns FAISS row index or -1."""
        if not self._ready:
            return -1
        try:
            vec = self._model.encode([text], normalize_embeddings=True)
            vec = np.array(vec, dtype="float32")
            with self._lock:
                idx = self._index.ntotal
                self._index.add(vec)
                self._id_map.append(fact_id)
                self._save_meta()
            return idx
        except Exception as e:
            log.debug("FAISS add error: %s", e)
            return -1

    # ── search ────────────────────────────────────────────────────────────────
    def search(self, query: str, k: int = 8) -> list[str]:
        """Return up to k fact_ids most similar to query."""
        if not self._ready or self._index.ntotal == 0:
            return []
        try:
            vec = self._model.encode([query], normalize_embeddings=True)
            vec = np.array(vec, dtype="float32")
            with self._lock:
                k   = min(k, self._index.ntotal)
                D, I = self._index.search(vec, k)
            results = []
            for dist, row in zip(D[0], I[0]):
                if row < 0 or row >= len(self._id_map):
                    continue
                # L2 distance → similarity: smaller = better
                sim = 1.0 / (1.0 + float(dist))
                if sim > 0.3:
                    results.append(self._id_map[row])
            return results
        except Exception as e:
            log.debug("FAISS search error: %s", e)
            return []

    # ── persistence ───────────────────────────────────────────────────────────
    def _save_meta(self):
        """Must be called within self._lock."""
        try:
            FAISS_META.parent.mkdir(parents=True, exist_ok=True)
            FAISS_META.write_text(json.dumps(self._id_map))
            faiss.write_index(self._index, str(FAISS_PATH))
        except Exception as e:
            log.debug("FAISS save error: %s", e)

    def save(self):
        if not self._ready:
            return
        with self._lock:
            self._save_meta()

    @property
    def ready(self) -> bool:
        return self._ready


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Source helpers — Wikipedia on demand, no keys
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _clean(text: str) -> str:
    """Normalize whitespace and truncate."""
    text = " ".join(text.split())
    return text[:MAX_FACT_LEN]


def scrape_wikipedia(topic: str) -> Optional[WorldEntry]:
    if not _HAS_REQUESTS:
        return None
    try:
        url  = WIKIPEDIA_API.format(topic.replace(" ", "_"))
        resp = requests.get(url, timeout=8, headers={"User-Agent": "FridayWorld/3.0"})
        if resp.status_code != 200:
            return None
        data    = resp.json()
        title   = data.get("title", "")
        extract = _clean(data.get("extract", ""))
        if len(extract) < MIN_FACT_LEN:
            return None
        return WorldEntry(
            source   = "wikipedia",
            category = "knowledge",
            title    = title,
            content  = extract,
            url      = data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            relevance = 0.75,
        )
    except Exception as e:
        log.debug("Wikipedia scrape failed [%s]: %s", topic, e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Disk usage helper
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _dir_size_bytes(path: Path) -> int:
    total = 0
    for f in Path(path).rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FridayWorld — main engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FridayWorld:
    """
    Vault-backed knowledge engine.

    Public API (called by friday_neural.py / friday_brain.py):
      query(text, k)          → list[dict]   semantic + keyword search
      get_recent(category, n) → list[dict]
      ingest_on_demand(topic) → int           new entries added
      enrich_wikipedia(topic) → bool
      status()                → dict
    """

    def __init__(self, vault_dir: Path = VAULT_DIR):
        WORLD_DIR.mkdir(parents=True, exist_ok=True)
        self._db     = VaultStore(vault_dir)
        self._index  = WorldIndex()
        self._ingesting = threading.Lock()
        log.info("FridayWorld initialised — Vault: %s | FAISS: %s",
                 vault_dir, "ready" if self._index.ready else "keyword-only")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Public query API
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def query(self, text: str, k: int = 6) -> list[dict]:
        """Return up to k relevant world entries for a query."""
        results = {}

        # 1. Semantic FAISS search (if available)
        if self._index.ready:
            ids = self._index.search(text, k=k * 2)
            for entry in self._db.get_by_ids(ids):
                results[entry["fact_id"]] = entry

        # 2. Keyword fallback / supplement
        if len(results) < k:
            for entry in self._db.search_keyword(text, limit=k):
                results.setdefault(entry["fact_id"], entry)

        # Sort by relevance, return top k
        return sorted(results.values(), key=lambda x: x["relevance"], reverse=True)[:k]

    def get_recent(self, category: str = "", n: int = 6) -> list[dict]:
        return self._db.get_recent(category=category, limit=n)

    def ingest_on_demand(self, topic: str) -> int:
        """Triggered by Neural when a query has no world context. Non-blocking attempt."""
        if not self._ingesting.acquire(blocking=False):
            return 0   # already ingesting
        try:
            entry = scrape_wikipedia(topic)
            added = self._store_entries([entry]) if entry else 0
            log.info("On-demand Wikipedia ingest [%s] → %d new entries", topic, added)
            return added
        finally:
            self._ingesting.release()

    def status(self) -> dict:
        return {
            "total_entries": self._db.count(),
            "vault_path":    str(VAULT_DIR),
            "disk_mb":       round(_dir_size_bytes(VAULT_DIR) / 1e6, 1),
            "quota_mb":      round(QUOTA_BYTES / 1e6),
            "faiss_ready":   self._index.ready,
            "last_ingest":   self._db.get_stat("last_ingest", "never"),
            "background":    False,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Internal helpers
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _store_entries(self, entries: list[WorldEntry]) -> int:
        added = 0
        for e in entries:
            if not e.content or len(e.content) < MIN_FACT_LEN:
                continue
            is_new = self._db.upsert(e)
            if is_new:
                # Embed and add to FAISS
                embed_text = f"{e.title} {e.content}"[:512]
                idx = self._index.add(e.fact_id, embed_text)
                if idx >= 0:
                    self._db.update_embed_idx(e.fact_id, idx)
                added += 1
        return added

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Wikipedia on-demand enrichment
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def enrich_wikipedia(self, topic: str) -> bool:
        """Pull Wikipedia summary for a topic and store it. Returns True if stored."""
        entry = scrape_wikipedia(topic)
        if not entry:
            return False
        added = self._store_entries([entry])
        return added > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Signal bus integration — IPC when running as separate process
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _try_register_signal(world: FridayWorld):
    """Optionally connect to friday_signal's event bus if it's running."""
    try:
        from core.infra.friday_signal import get_bus, EventType
        bus = get_bus()

        async def _on_world_query(event):
            query = event.data.get("query", "")
            if not query:
                return
            results = world.query(query, k=5)
            await bus.emit("world.results", {"query": query, "results": results})

        bus.subscribe(EventType.WORLD_QUERY, _on_world_query)
        log.info("Signal bus connected")
    except Exception as e:
        log.debug("Signal bus not available: %s", e)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Singleton accessor (used by brain modules in-process)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_world_instance: Optional[FridayWorld] = None

def get_world() -> FridayWorld:
    global _world_instance
    if _world_instance is None:
        _world_instance = FridayWorld()
    return _world_instance


def start(*args, **kwargs):
    """No background loop anymore — just initialise the vault-backed world.

    Accepts and ignores legacy kwargs like env_interval / knowledge_interval.
    """
    return get_world()


def stop(*args, **kwargs):
    """Persist the FAISS index on shutdown."""
    try:
        get_world()._index.save()
    except Exception:
        pass


def query_world(text: str, k: int = 6) -> list[dict]:
    """Convenience wrapper for Neural/Brain modules."""
    return get_world().query(text, k)


def learn(question: str, answer: str, source: str = "friday.learned") -> bool:
    """Store a Q&A Friday just figured out as a persistent vault note, so she can
    recall it later (and the local QA module can learn it on its next retrain).
    Returns True if a new note was stored."""
    question = (question or "").strip()
    answer   = (answer or "").strip()
    if not question or len(answer) < 20:
        return False
    try:
        entry = WorldEntry(
            source    = source,
            category  = "learned",
            title     = question[:120],
            content   = answer,
            relevance = 0.7,
        )
        return get_world()._store_entries([entry]) > 0
    except Exception as e:
        log.debug("learn() failed: %s", e)
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Standalone process entry-point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _run_as_process():
    """Run FridayWorld utilities from the command line."""
    parser = argparse.ArgumentParser(description="FridayWorld vault-backed world")
    parser.add_argument("--query",  type=str, default="", help="Query mode: print results and exit")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--enrich", type=str, default="", help="Fetch a Wikipedia note for TOPIC into the vault")
    args = parser.parse_args()

    world = FridayWorld()

    if args.status:
        s = world.status()
        print(json.dumps(s, indent=2))
        return

    if args.query:
        results = world.query(args.query)
        for r in results:
            print(f"[{r['category']}] {r['title']}")
            print(f"  {r['content'][:200]}")
            print()
        return

    if args.enrich:
        stored = world.enrich_wikipedia(args.enrich)
        if stored:
            print(f"Stored Wikipedia note for '{args.enrich}' in the vault.")
        else:
            print(f"No note stored for '{args.enrich}' (not found or already present).")
        return

    print("Background ingest has been removed — knowledge now lives in the "
          "Obsidian vault. Use --query, --status, or --enrich TOPIC.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _run_tests():
    import tempfile, shutil

    print("=" * 60)
    print("friday_world.py — test suite")
    print("=" * 60)

    tmpdir = Path(tempfile.mkdtemp()) / "test_world"
    tmpdir.mkdir()

    # Override global paths for tests
    global VAULT_DIR, WORLD_DIR, FAISS_PATH, FAISS_META, STATS_PATH
    _orig = (VAULT_DIR, WORLD_DIR, FAISS_PATH, FAISS_META, STATS_PATH)
    VAULT_DIR  = tmpdir
    WORLD_DIR  = tmpdir
    FAISS_PATH = tmpdir / "test_faiss.index"
    FAISS_META = tmpdir / "test_faiss_meta.json"
    STATS_PATH = tmpdir / "test_stats.json"

    passed = failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            print(f"  [PASS]  {name}")
            passed += 1
        else:
            print(f"  [FAIL]  {name}  {detail}")
            failed += 1

    try:
        # ── VaultStore layer ────────────────────────────────────────────────
        print("\n[ VaultStore ]")
        db = VaultStore(tmpdir)

        e1 = WorldEntry(source="test", category="tech", title="AI news",
                        content="Artificial intelligence is advancing rapidly in 2025.")
        e2 = WorldEntry(source="test", category="sports", title="IPL 2025",
                        content="Mumbai Indians won the IPL 2025 championship in a thrilling final.")
        e3 = WorldEntry(source="test", category="tech", title="Python update",
                        content="Python 3.13 released with major performance improvements and JIT compiler.")

        db.upsert(e1); db.upsert(e2); db.upsert(e3)
        check("upsert 3 entries", db.count() == 3)

        dup = db.upsert(e1)   # same fact_id → not new
        check("duplicate upsert returns False", dup == False)
        check("count still 3 after dup", db.count() == 3)

        results = db.search_keyword("artificial intelligence", limit=5)
        check("keyword search returns AI entry",
              any("AI news" in r["title"] or "intelligence" in r["content"].lower()
                  for r in results))

        recent = db.get_recent(limit=5)
        check("get_recent returns entries", len(recent) == 3)

        recent_sports = db.get_recent(category="sports", limit=5)
        check("get_recent filtered by category", len(recent_sports) == 1)
        check("category filter correct", recent_sports[0]["category"] == "sports")

        # ── Persistence / round-trip ────────────────────────────────────────
        print("\n[ Persistence ]")
        db2 = VaultStore(tmpdir)   # fresh store reads notes back off disk
        check("reload count == 3", db2.count() == 3)
        reloaded = {r["fact_id"]: r for r in db2.get_recent(limit=10)}
        check("AI entry round-trips",
              e1.fact_id in reloaded and reloaded[e1.fact_id]["title"] == "AI news")
        check("content round-trips",
              "Artificial intelligence" in reloaded.get(e1.fact_id, {}).get("content", ""))

        # ── WorldEntry defaults ─────────────────────────────────────────────
        print("\n[ WorldEntry ]")
        e_know = WorldEntry(source="wikipedia", category="knowledge",
                            title="Test", content="Some test content here for validation")
        check("fact_id auto-generated", bool(e_know.fact_id))
        check("knowledge entry never expires (empty expires_at)",
              e_know.expires_at == "", f"got '{e_know.expires_at}'")

        e_tech = WorldEntry(source="rss", category="tech",
                            title="Test tech", content="Some tech content here for validation")
        check("tech entry has non-empty expires_at", bool(e_tech.expires_at))

        # fetched_at is stored as naive UTC (see _utcnow_iso) — compare against UTC now
        ft = datetime.fromisoformat(e_know.fetched_at)
        now_naive = _utcnow().replace(tzinfo=None)
        check("fetched_at set to now", abs((now_naive - ft).total_seconds()) < 10)

        # ── FridayWorld query ───────────────────────────────────────────────
        print("\n[ FridayWorld query ]")
        world = FridayWorld(tmpdir)

        q_results = world.query("Python programming language")
        check("query returns results", len(q_results) > 0,
              f"got {len(q_results)} results")
        check("Python entry returned in query",
              any("Python" in r.get("title", "") or "python" in r.get("content", "").lower()
                  for r in q_results))

        q_sports = world.query("cricket IPL Mumbai")
        check("cricket query returns sports entry",
              any("IPL" in r.get("title", "") for r in q_sports))

        # ── Status ──────────────────────────────────────────────────────────
        print("\n[ Status ]")
        status = world.status()
        check("status has total_entries", "total_entries" in status)
        check("status total_entries == 3", status["total_entries"] == 3)
        check("status has disk_mb", "disk_mb" in status)
        check("status background=False", status["background"] == False)

        # ── Dedup check ─────────────────────────────────────────────────────
        print("\n[ Deduplication ]")
        world._store_entries([e1, e1, e1])   # same entry 3x
        check("no duplicates stored", world._db.count() == 3)

        # ── Clean text ──────────────────────────────────────────────────────
        print("\n[ _clean ]")
        long_text = "word " * 400
        cleaned   = _clean(long_text)
        check("long text truncated to MAX_FACT_LEN", len(cleaned) <= MAX_FACT_LEN)

        noisy = "  lots   of   spaces  here  "
        check("whitespace normalized", _clean(noisy) == "lots of spaces here")

        # ── lowest_relevance / delete ───────────────────────────────────────
        print("\n[ Relevance / delete ]")
        ids_before = db.count()
        low_id = db.lowest_relevance_ids(1)
        check("lowest_relevance_ids returns 1", len(low_id) == 1)
        db.delete_ids(low_id)
        check("delete_ids removes entry", db.count() == ids_before - 1)

    finally:
        # Restore global paths
        VAULT_DIR, WORLD_DIR, FAISS_PATH, FAISS_META, STATS_PATH = _orig
        shutil.rmtree(tmpdir.parent, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All tests passed")
    print("=" * 60)
    return failed == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    if "--test" in sys.argv:
        ok = _run_tests()
        sys.exit(0 if ok else 1)
    else:
        _run_as_process()
