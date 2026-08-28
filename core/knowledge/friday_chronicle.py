"""
friday_chronicle.py — Friday 3.0
The Memory Engine. Everything that ever happened, remembered forever.
SQLite for structured storage. FAISS for neural similarity search.
Episodic memory: conversations, facts, preferences, outcomes.
"""

import os
import json
import time
import atexit
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

log = logging.getLogger("friday.chronicle")

# ── Paths ─────────────────────────────────────────────────────────────────────

_BASE_DIR    = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
_DATA_DIR    = _BASE_DIR / "data"
_DB_PATH     = _DATA_DIR / "chronicle.db"
_FAISS_PATH  = _DATA_DIR / "chronicle.faiss"
_EMBED_PATH  = _DATA_DIR / "chronicle.embeddings.npy"

_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Memory types ──────────────────────────────────────────────────────────────

class MemoryType:
    CONVERSATION = "conversation"   # user ↔ friday turns
    FACT         = "fact"           # extracted knowledge
    PREFERENCE   = "preference"     # what Satvik likes/dislikes
    OUTCOME      = "outcome"        # what worked, what didn't
    CONTEXT      = "context"        # screen / session context
    WORLD        = "world"          # facts from the web


@dataclass
class Memory:
    id:          int
    type:        str
    role:        str          # "user" | "friday" | "system"
    content:     str
    topic:       str
    timestamp:   float
    session_id:  str
    importance:  float        # 0.0 – 1.0
    metadata:    dict


# ── DB setup ──────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")   # wait out writer contention, don't throw
    return conn


_conn_lock  = threading.Lock()
# Writers serialize process-wide: SQLite on Windows can return BUSY on some
# lock upgrades without consulting the busy handler, so relying on timeouts
# alone makes concurrent writes flaky. Reads stay lock-free (per-thread
# connections + WAL).
_write_lock = threading.Lock()
_local      = threading.local()
_schema_ready = False


def _db() -> sqlite3.Connection:
    """
    Connection accessor — one connection per thread. Chronicle is written from
    at least three threads (FAISS indexer, sovereign daemon, Flask job workers);
    WAL mode makes per-thread connections safe where the old single shared
    connection raced. Schema init happens exactly once, under the lock.
    """
    global _schema_ready
    conn = getattr(_local, "conn", None)
    if conn is None:
        # Connection CREATION is serialized, not just schema init: flipping a
        # fresh DB to WAL (PRAGMA journal_mode) needs exclusive access and
        # SQLite does not consult the busy handler for that transition — two
        # threads opening first connections concurrently → "database is locked".
        with _conn_lock:
            conn = _get_conn()
            if not _schema_ready:
                _init_schema(conn)
                _schema_ready = True
        _local.conn = conn
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT    NOT NULL DEFAULT 'conversation',
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            topic       TEXT    NOT NULL DEFAULT '',
            timestamp   REAL    NOT NULL,
            session_id  TEXT    NOT NULL DEFAULT '',
            importance  REAL    NOT NULL DEFAULT 0.5,
            metadata    TEXT    NOT NULL DEFAULT '{}',
            embed_id    INTEGER DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS facts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subject     TEXT    NOT NULL,
            predicate   TEXT    NOT NULL,
            object      TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'conversation',
            confidence  REAL    NOT NULL DEFAULT 0.8,
            timestamp   REAL    NOT NULL,
            metadata    TEXT    NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS preferences (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT    NOT NULL,
            key         TEXT    NOT NULL,
            value       TEXT    NOT NULL,
            weight      REAL    NOT NULL DEFAULT 1.0,
            updated_at  REAL    NOT NULL,
            UNIQUE(category, key)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT    PRIMARY KEY,
            started_at  REAL    NOT NULL,
            ended_at    REAL,
            summary     TEXT    DEFAULT NULL,
            turn_count  INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_memories_type      ON memories(type);
        CREATE INDEX IF NOT EXISTS idx_memories_topic     ON memories(topic);
        CREATE INDEX IF NOT EXISTS idx_memories_session   ON memories(session_id);
        CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp);
        CREATE INDEX IF NOT EXISTS idx_facts_subject      ON facts(subject);
        CREATE INDEX IF NOT EXISTS idx_prefs_category     ON preferences(category);
    """)
    conn.commit()
    log.info("Chronicle schema ready at %s", _DB_PATH)


# ── Embedding engine ──────────────────────────────────────────────────────────

_embed_model  = None
_faiss_index  = None
_embed_ids:   list[int] = []    # maps FAISS index position → memory.id
_embed_lock   = threading.Lock()
_embed_ready  = False


def _load_embedder():
    global _embed_model, _embed_ready
    if _embed_model is not None:
        return True
    try:
        from sentence_transformers import SentenceTransformer
        from core.intelligence.device import preferred_device
        device = preferred_device("embeddings")   # wizard's device plan (M35)
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        _embed_ready = True
        log.info("Embedding model loaded on %s", device)
        return True
    except ImportError:
        log.warning("sentence-transformers not installed — FAISS search disabled")
        return False
    except Exception as e:
        log.warning("Embedding model failed: %s — FAISS disabled", e)
        return False


def _load_faiss():
    global _faiss_index, _embed_ids
    if _faiss_index is not None:
        return True
    try:
        import faiss
        import numpy as np
        if _FAISS_PATH.exists():
            _faiss_index = faiss.read_index(str(_FAISS_PATH))
            if _EMBED_PATH.exists():
                _embed_ids = list(np.load(str(_EMBED_PATH)))
            else:
                _embed_ids = []
            # The .npy side list can lag the index after a crash (it used to be
            # saved only every 20 inserts). memories.embed_id is the durable
            # source of truth — recover the mapping from the DB on mismatch.
            if len(_embed_ids) != _faiss_index.ntotal:
                _embed_ids = _embed_ids_from_db()
                log.warning(
                    "FAISS side list desynced (%d vs %d vectors) — recovered %d from embed_id",
                    len(_embed_ids), _faiss_index.ntotal, len(_embed_ids))
            log.info("FAISS index loaded: %d vectors", _faiss_index.ntotal)
        else:
            _faiss_index = faiss.IndexFlatL2(384)   # all-MiniLM-L6-v2 dim
            _embed_ids   = []
            log.info("New FAISS index created")
        return True
    except ImportError:
        log.warning("faiss-cpu not installed — neural search disabled")
        return False
    except Exception as e:
        log.warning("FAISS load failed: %s", e)
        return False


def _embed_ids_from_db() -> list[int]:
    """Rebuild the FAISS-position → memory-id mapping from memories.embed_id."""
    rows = _db().execute(
        "SELECT id, embed_id FROM memories WHERE embed_id IS NOT NULL ORDER BY embed_id"
    ).fetchall()
    return [r["id"] for r in rows]


def _embed(text: str):
    if not _load_embedder():
        return None
    return _embed_model.encode([text[:512]], normalize_embeddings=True)[0]


def _save_faiss():
    if _faiss_index is None:
        return
    try:
        import faiss
        import numpy as np
        faiss.write_index(_faiss_index, str(_FAISS_PATH))
        np.save(str(_EMBED_PATH), np.array(_embed_ids))
    except Exception as e:
        log.warning("FAISS save failed: %s", e)


# ── Session management ────────────────────────────────────────────────────────

_current_session: Optional[str] = None


def start_session() -> str:
    global _current_session
    import uuid
    sid = str(uuid.uuid4())[:8]
    db = _db()
    with _write_lock:
        db.execute(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            (sid, time.time())
        )
        db.commit()
    _current_session = sid
    log.info("Session started: %s", sid)
    return sid


def end_session(summary: Optional[str] = None) -> None:
    if not _current_session:
        return
    db = _db()
    with _write_lock:
        db.execute(
            "UPDATE sessions SET ended_at=?, summary=? WHERE id=?",
            (time.time(), summary, _current_session)
        )
        db.commit()
    log.info("Session ended: %s", _current_session)


def get_session() -> str:
    global _current_session
    if not _current_session:
        start_session()
    return _current_session


# ── Core write operations ─────────────────────────────────────────────────────

def save_turn(
    role:       str,
    content:    str,
    topic:      str      = "",
    importance: float    = 0.5,
    metadata:   dict     = None,
    mem_type:   str      = MemoryType.CONVERSATION,
) -> int:
    """
    Save a conversation turn. Returns memory ID.
    Embeds into FAISS if available.
    """
    db   = _db()
    meta = json.dumps(metadata or {})
    sid  = get_session()

    with _write_lock:
        cursor = db.execute(
            """INSERT INTO memories
               (type, role, content, topic, timestamp, session_id, importance, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (mem_type, role, content, topic, time.time(), sid, importance, meta)
        )
        mem_id = cursor.lastrowid
        db.commit()

    # Embed async-ish — don't block caller
    _index_memory(mem_id, content)

    log.debug("Saved [%s/%s] id=%d topic=%s", mem_type, role, mem_id, topic)
    return mem_id


def _index_memory(mem_id: int, content: str) -> None:
    """Add to FAISS index. Called after DB write."""
    with _embed_lock:
        if not _load_embedder() or not _load_faiss():
            return
        try:
            vec = _embed(content)
            if vec is None:
                return
            position = _faiss_index.ntotal
            _faiss_index.add(vec.reshape(1, -1).astype("float32"))
            _embed_ids.append(mem_id)
            # Durable link: the row records its own FAISS position, so the
            # mapping survives a crash even if the .npy side list is stale.
            with _write_lock:
                _db().execute(
                    "UPDATE memories SET embed_id=? WHERE id=?", (position, mem_id))
                _db().commit()
            # Save every 20 new vectors
            if len(_embed_ids) % 20 == 0:
                _save_faiss()
        except Exception as e:
            log.warning("FAISS index failed for id=%d: %s", mem_id, e)


def flush() -> None:
    """Persist the FAISS index + side list now. Called at shutdown."""
    with _embed_lock:
        _save_faiss()


atexit.register(flush)


def save_fact(
    subject:    str,
    predicate:  str,
    object_:    str,
    source:     str   = "conversation",
    confidence: float = 0.8,
    metadata:   dict  = None,
) -> int:
    """Store a structured fact triple: subject → predicate → object."""
    db = _db()
    with _write_lock:
        cursor = db.execute(
            """INSERT INTO facts
               (subject, predicate, object, source, confidence, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (subject, predicate, object_, source, confidence, time.time(),
             json.dumps(metadata or {}))
        )
        db.commit()
    log.debug("Fact saved: %s %s %s", subject, predicate, object_)
    return cursor.lastrowid


def save_preference(
    category: str,
    key:      str,
    value:    str,
    weight:   float = 1.0,
) -> None:
    """Upsert a preference. Thread-safe."""
    db = _db()
    with _write_lock:
        db.execute(
            """INSERT INTO preferences (category, key, value, weight, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(category, key) DO UPDATE SET
                   value=excluded.value,
                   weight=excluded.weight,
                   updated_at=excluded.updated_at""",
            (category, key, value, weight, time.time())
        )
        db.commit()


# ── Core read operations ──────────────────────────────────────────────────────

def search_neural(query: str, limit: int = 8) -> list[dict]:
    """
    FAISS similarity search. Returns most relevant memories.
    Falls back to keyword search if FAISS unavailable.
    """
    with _embed_lock:
        if not _load_embedder() or not _load_faiss() or _faiss_index.ntotal == 0:
            return search_keyword(query, limit=limit)

        try:
            vec = _embed(query)
            if vec is None:
                return search_keyword(query, limit=limit)

            k = min(limit, _faiss_index.ntotal)
            distances, indices = _faiss_index.search(
                vec.reshape(1, -1).astype("float32"), k
            )
            mem_ids = [
                _embed_ids[i]
                for i in indices[0]
                if i < len(_embed_ids)
            ]
            if not mem_ids:
                return []

            db = _db()
            placeholders = ",".join("?" * len(mem_ids))
            rows = db.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})",
                mem_ids
            ).fetchall()
            return [dict(r) for r in rows]

        except Exception as e:
            log.warning("Neural search failed: %s — falling back to keyword", e)
            return search_keyword(query, limit=limit)


def search_keyword(
    query:   str,
    limit:   int  = 8,
    mem_type: Optional[str] = None,
) -> list[dict]:
    """SQLite full-text keyword search fallback."""
    db = _db()
    q  = f"%{query.lower()}%"
    if mem_type:
        rows = db.execute(
            """SELECT * FROM memories
               WHERE type=? AND (LOWER(content) LIKE ? OR LOWER(topic) LIKE ?)
               ORDER BY importance DESC, timestamp DESC LIMIT ?""",
            (mem_type, q, q, limit)
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT * FROM memories
               WHERE LOWER(content) LIKE ? OR LOWER(topic) LIKE ?
               ORDER BY importance DESC, timestamp DESC LIMIT ?""",
            (q, q, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent(limit: int = 20, session_only: bool = False) -> list[dict]:
    """Get the most recent conversation turns."""
    db  = _db()
    sid = get_session()
    if session_only:
        rows = db.execute(
            """SELECT * FROM memories
               WHERE type='conversation' AND session_id=?
               ORDER BY timestamp DESC LIMIT ?""",
            (sid, limit)
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT * FROM memories
               WHERE type='conversation'
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    return list(reversed([dict(r) for r in rows]))


def get_facts(subject: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Retrieve stored facts, optionally filtered by subject."""
    db = _db()
    if subject:
        rows = db.execute(
            """SELECT * FROM facts
               WHERE LOWER(subject) LIKE ?
               ORDER BY confidence DESC, timestamp DESC LIMIT ?""",
            (f"%{subject.lower()}%", limit)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM facts ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_preferences(category: Optional[str] = None) -> list[dict]:
    """Retrieve preferences, optionally by category."""
    db = _db()
    if category:
        rows = db.execute(
            "SELECT * FROM preferences WHERE category=? ORDER BY weight DESC",
            (category,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM preferences ORDER BY category, weight DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_persistent_context(limit: int = 20) -> str:
    """
    Returns last N conversations as context string.
    Ported from v2 — gives Friday cross-session memory.
    """
    history = get_recent(limit=limit)
    if not history:
        return ""
    lines = ["Previous conversation history:"]
    for msg in history:
        role    = "Satvik" if msg["role"] == "user" else "Friday"
        content = msg["content"][:200]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def get_user_profile() -> str:
    """
    Builds a comprehensive profile of Satvik from stored facts + preferences.
    Ported from v2 — injected into every brain call for personalization.
    """
    facts = get_facts(limit=30)
    prefs = get_preferences()
    lines = []
    if facts:
        lines.append("What I know about Satvik:")
        for f in facts[:10]:
            lines.append(f"  - {f['subject']} {f['predicate']} {f['object']}")
    if prefs:
        lines.append("Preferences:")
        for p in prefs[:8]:
            lines.append(f"  - {p['category']}.{p['key']} = {p['value']}")
    return "\n".join(lines) if lines else ""


def build_context_block(query: str, max_chars: int = 1500) -> str:
    """
    Assemble a rich context string for the neural module.
    Combines: relevant memories + recent history + facts + preferences.
    """
    parts: list[str] = []
    budget = max_chars

    # 1. Neural search — most relevant memories
    relevant = search_neural(query, limit=5)
    if relevant:
        lines = []
        for m in relevant:
            snippet = m["content"][:200].replace("\n", " ")
            lines.append(f"[{m['role']}] {snippet}")
        block = "Relevant memories:\n" + "\n".join(lines)
        parts.append(block)
        budget -= len(block)

    # 2. Recent turns (last 6)
    if budget > 300:
        recent = get_recent(limit=6, session_only=True)
        if recent:
            lines = [
                f"{r['role'].upper()}: {r['content'][:150]}"
                for r in recent
            ]
            block = "Recent conversation:\n" + "\n".join(lines)
            parts.append(block)
            budget -= len(block)

    # 3. Relevant facts
    if budget > 200:
        facts = get_facts(limit=5)
        if facts:
            lines = [
                f"{f['subject']} {f['predicate']} {f['object']}"
                for f in facts[:5]
            ]
            block = "Known facts:\n" + "\n".join(lines)
            parts.append(block)

    # 4. Preferences
    prefs = get_preferences()
    if prefs and budget > 100:
        lines = [f"{p['category']}.{p['key']} = {p['value']}" for p in prefs[:5]]
        parts.append("Preferences:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def stats() -> dict:
    """Return memory statistics."""
    db = _db()
    return {
        "total_memories":  db.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        "total_facts":     db.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "total_prefs":     db.execute("SELECT COUNT(*) FROM preferences").fetchone()[0],
        "total_sessions":  db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        "faiss_vectors":   _faiss_index.ntotal if _faiss_index else 0,
        "embed_ready":     _embed_ready,
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_chronicle] Running self-test...\n")

    # Start session
    sid = start_session()
    print(f"  OK Session started: {sid}")

    # Save turns
    id1 = save_turn("user",   "I'm building an AI called Friday",      topic="friday_project", importance=0.9)
    id2 = save_turn("friday", "Sounds amazing — what's the core idea?", topic="friday_project", importance=0.8)
    id3 = save_turn("user",   "She should be independent and learn",    topic="friday_project", importance=0.9)
    print(f"  OK Saved 3 turns: ids {id1}, {id2}, {id3}")

    # Save facts
    save_fact("Satvik", "is_building", "Friday AI")
    save_fact("Friday", "runs_on",     "Windows 11")
    save_fact("Friday", "uses",        "Groq API")
    print("  OK Saved 3 facts")

    # Save preferences
    save_preference("ui", "theme",    "glassmorphism dark")
    save_preference("voice", "style", "warm and direct")
    print("  OK Saved 2 preferences")

    # Keyword search
    results = search_keyword("AI Friday")
    print(f"  OK Keyword search returned {len(results)} results")

    # Context block
    ctx = build_context_block("what is Friday?")
    print(f"  OK Context block built: {len(ctx)} chars")

    # Stats
    s = stats()
    print(f"  OK Stats: {s}")

    end_session("Test session completed")
    print("\n[friday_chronicle] All tests passed OK\n")