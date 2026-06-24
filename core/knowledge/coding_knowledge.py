"""
core/knowledge/coding_knowledge.py — FRIDAY 4.0 (M7)
Curated, distilled coding patterns FRIDAY can recall and apply. These are not
raw snippets scraped from the web — they are *understood* patterns: a named
problem, a minimal correct solution, and the principle behind it.

The seed library covers patterns the assistant reaches for constantly
(authentication, DB connections, retries, error handling). `seed()` writes them
into the KnowledgeStore once; re-running it is idempotent (keyed by title).
"""

from __future__ import annotations

import re
from typing import Optional

from .knowledge_models import KnowledgeCategory, KnowledgeEntry, new_knowledge

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"how", "do", "i", "to", "a", "an", "the", "in", "on", "with", "for",
         "of", "and", "or", "my", "you", "users", "use", "using"}


# ── pattern library ──────────────────────────────────────────────────────────────
# Each pattern: (title, category, content). Content is the distilled principle +
# a minimal, correct illustration — never a whole tutorial.
_PATTERNS: list[tuple[str, str, str]] = [
    (
        "Flask session authentication",
        KnowledgeCategory.FLASK,
        "Store the user id in Flask's signed session after verifying a password "
        "hash; gate protected views with a decorator that redirects when the key "
        "is absent.\n\n"
        "    from functools import wraps\n"
        "    from flask import session, redirect, url_for\n"
        "    def login_required(view):\n"
        "        @wraps(view)\n"
        "        def wrapped(*a, **k):\n"
        "            if 'uid' not in session:\n"
        "                return redirect(url_for('login'))\n"
        "            return view(*a, **k)\n"
        "        return wrapped\n\n"
        "Principle: never trust the client; the signed cookie carries only the id, "
        "and authorisation is re-checked server-side on every request.",
    ),
    (
        "SQLite connection per thread",
        KnowledgeCategory.SQLITE,
        "SQLite connections are not safe to share across threads. Open one "
        "connection per thread (threading.local), enable WAL for concurrent "
        "readers, and set a busy_timeout so writers wait instead of erroring.\n\n"
        "    import sqlite3, threading\n"
        "    _local = threading.local()\n"
        "    def conn(path):\n"
        "        c = getattr(_local, 'c', None)\n"
        "        if c is None:\n"
        "            c = sqlite3.connect(path, check_same_thread=False)\n"
        "            c.execute('PRAGMA journal_mode=WAL')\n"
        "            c.execute('PRAGMA busy_timeout=5000')\n"
        "            _local.c = c\n"
        "        return c\n\n"
        "Principle: the DB is the source of truth; isolate connections, let WAL "
        "handle concurrency.",
    ),
    (
        "API retry with exponential backoff",
        KnowledgeCategory.PYTHON,
        "Transient network/HTTP failures should be retried with exponential "
        "backoff and jitter, capped, and only for idempotent calls.\n\n"
        "    import time, random\n"
        "    def with_retry(call, attempts=4, base=0.5):\n"
        "        for i in range(attempts):\n"
        "            try:\n"
        "                return call()\n"
        "            except TransientError:\n"
        "                if i == attempts - 1:\n"
        "                    raise\n"
        "                time.sleep(base * 2 ** i + random.random() * 0.1)\n\n"
        "Principle: back off to relieve the failing service; jitter avoids "
        "thundering herds; never retry non-idempotent writes blindly.",
    ),
    (
        "Error handling at the boundary",
        KnowledgeCategory.PYTHON,
        "Catch exceptions where you can act on them — at the I/O boundary — not "
        "deep in the call stack. Catch the narrowest type, preserve the cause, "
        "and never swallow silently.\n\n"
        "    try:\n"
        "        data = load(path)\n"
        "    except FileNotFoundError as e:\n"
        "        raise ConfigError(f'missing {path}') from e\n\n"
        "Principle: exceptions carry intent; let them propagate to a layer that "
        "can decide, log with context, and re-raise as a domain error.",
    ),
]


class CodingKnowledge:
    def __init__(self, store) -> None:
        self._store = store

    def patterns(self) -> list[KnowledgeEntry]:
        """The seed patterns as (unstored) KnowledgeEntry objects."""
        return [
            new_knowledge(title=t, content=c, category=cat, confidence=0.9,
                          source="curated", metadata={"pattern": True})
            for (t, cat, c) in _PATTERNS
        ]

    def seed(self) -> list[str]:
        """Insert any missing seed patterns. Idempotent (keyed by title)."""
        created: list[str] = []
        for entry in self.patterns():
            if self._store.find_by_title(entry.title, entry.category) is None:
                self._store.create(entry)
                created.append(entry.id)
        return created

    def find(self, problem: str) -> Optional[KnowledgeEntry]:
        """Best curated pattern for a described problem. Scores seed patterns by
        how many salient query terms appear in their title/content."""
        terms = [w for w in _WORD.findall((problem or "").lower())
                 if w not in _STOP and len(w) > 2]
        if not terms:
            return None
        best, best_score = None, 0
        for e in self._store.list(limit=1000):
            if not e.metadata.get("pattern"):
                continue
            hay = f"{e.title} {e.content}".lower()
            score = sum(1 for t in terms if t in hay)
            if score > best_score:
                best, best_score = e, score
        return best if best_score > 0 else None
