"""
core/user_model/store.py — FRIDAY 4.0 (M9)
UserModelStore: local SQLite persistence for everything FRIDAY learns about her
user. Same store discipline as M2/M4/M5/M7 — per-thread connections, WAL, a
migration gate (`schema_version`). The database lives at `data/user_model.db` and
**never leaves the machine** (privacy-first; no cloud, no telemetry).

Tables: profile, profile_history, preferences, habits, interests, interest_links,
projects, communication, learning, relationship_facts, user_events, user_metrics,
schema_version.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional

from .models import (Habit, Interest, InterestLink, Preference, Project,
                     RelationshipFact, UserProfile)

log = logging.getLogger("friday.user_model.store")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "user_model.db"
_SCHEMA_VERSION = 1


class UserModelEvent(str, Enum):
    PROFILE_UPDATED = "user.profile.updated"
    PREFERENCE_CHANGED = "user.preference.changed"
    INTEREST_GROWN = "user.interest.grown"
    HABIT_DISCOVERED = "user.habit.discovered"
    PROJECT_UPDATED = "user.project.updated"
    LEARNING_ADAPTED = "user.learning.adapted"


def _loads(text, default):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


class UserModelStore:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        c = self._conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile (
                id TEXT PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}',
                version INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                version INTEGER NOT NULL, snapshot TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY, category TEXT NOT NULL DEFAULT 'general',
                value TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0.5,
                evidence_count INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS habits (
                key TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT '',
                bucket TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interests (
                name TEXT PRIMARY KEY, weight REAL NOT NULL DEFAULT 0.5,
                count INTEGER NOT NULL DEFAULT 0, category TEXT NOT NULL DEFAULT '',
                first_seen REAL NOT NULL, last_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interest_links (
                a TEXT NOT NULL, b TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1.0,
                PRIMARY KEY (a, b)
            );
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                data TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS communication (
                aspect TEXT PRIMARY KEY, value REAL NOT NULL DEFAULT 0.5,
                evidence_count INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learning (
                style TEXT PRIMARY KEY, score REAL NOT NULL DEFAULT 0.0,
                count INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS relationship_facts (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'context',
                content TEXT NOT NULL DEFAULT '', approved INTEGER NOT NULL DEFAULT 0,
                sensitive INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                kind TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS user_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                metric TEXT NOT NULL, value REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_proj_status ON projects(status);
            CREATE INDEX IF NOT EXISTS idx_uevents_kind ON user_events(kind);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    # ── profile ────────────────────────────────────────────────────────────────
    def get_profile(self) -> Optional[UserProfile]:
        r = self._conn().execute("SELECT * FROM profile WHERE id='primary'").fetchone()
        if r is None:
            return None
        return UserProfile.from_dict(_loads(r["data"], {}))

    def save_profile(self, profile: UserProfile) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO profile (id, data, version, updated_at)
               VALUES ('primary', ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET data=excluded.data,
                 version=excluded.version, updated_at=excluded.updated_at""",
            (json.dumps(profile.to_dict()), profile.version, profile.updated_at))
        c.commit()

    def add_profile_history(self, version: int, snapshot: dict) -> None:
        c = self._conn()
        c.execute("INSERT INTO profile_history (ts, version, snapshot) VALUES (?, ?, ?)",
                  (time.time(), version, json.dumps(snapshot)))
        c.commit()

    def profile_history(self, limit: int = 50) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM profile_history ORDER BY version DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["snapshot"] = _loads(d["snapshot"], {})
            out.append(d)
        return out

    # ── preferences ────────────────────────────────────────────────────────────
    def get_preference(self, key: str) -> Optional[Preference]:
        r = self._conn().execute("SELECT * FROM preferences WHERE key=?", (key,)).fetchone()
        return Preference(**dict(r)) if r else None

    def save_preference(self, pref: Preference) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO preferences (key, category, value, score, evidence_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET category=excluded.category, value=excluded.value,
                 score=excluded.score, evidence_count=excluded.evidence_count,
                 updated_at=excluded.updated_at""",
            (pref.key, pref.category, pref.value, pref.score, pref.evidence_count, pref.updated_at))
        c.commit()

    def list_preferences(self, category: Optional[str] = None) -> list[Preference]:
        if category:
            rows = self._conn().execute(
                "SELECT * FROM preferences WHERE category=? ORDER BY score DESC", (category,)).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM preferences ORDER BY score DESC").fetchall()
        return [Preference(**dict(r)) for r in rows]

    # ── habits ─────────────────────────────────────────────────────────────────
    def get_habit(self, key: str) -> Optional[Habit]:
        r = self._conn().execute("SELECT * FROM habits WHERE key=?", (key,)).fetchone()
        return Habit(**dict(r)) if r else None

    def save_habit(self, habit: Habit) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO habits (key, kind, bucket, count, confidence, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET kind=excluded.kind, bucket=excluded.bucket,
                 count=excluded.count, confidence=excluded.confidence, updated_at=excluded.updated_at""",
            (habit.key, habit.kind, habit.bucket, habit.count, habit.confidence, habit.updated_at))
        c.commit()

    def list_habits(self, kind: Optional[str] = None) -> list[Habit]:
        if kind:
            rows = self._conn().execute(
                "SELECT * FROM habits WHERE kind=? ORDER BY confidence DESC", (kind,)).fetchall()
        else:
            rows = self._conn().execute("SELECT * FROM habits ORDER BY confidence DESC").fetchall()
        return [Habit(**dict(r)) for r in rows]

    # ── interests ──────────────────────────────────────────────────────────────
    def get_interest(self, name: str) -> Optional[Interest]:
        r = self._conn().execute("SELECT * FROM interests WHERE name=?", (name,)).fetchone()
        return Interest(**dict(r)) if r else None

    def save_interest(self, interest: Interest) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO interests (name, weight, count, category, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET weight=excluded.weight, count=excluded.count,
                 category=excluded.category, last_seen=excluded.last_seen""",
            (interest.name, interest.weight, interest.count, interest.category,
             interest.first_seen, interest.last_seen))
        c.commit()

    def list_interests(self) -> list[Interest]:
        rows = self._conn().execute("SELECT * FROM interests ORDER BY weight DESC").fetchall()
        return [Interest(**dict(r)) for r in rows]

    def add_interest_link(self, link: InterestLink) -> None:
        a, b = sorted((link.a, link.b))
        c = self._conn()
        c.execute(
            """INSERT INTO interest_links (a, b, weight) VALUES (?, ?, ?)
               ON CONFLICT(a, b) DO UPDATE SET weight=excluded.weight""",
            (a, b, link.weight))
        c.commit()

    def interest_links(self, name: Optional[str] = None) -> list[InterestLink]:
        if name:
            rows = self._conn().execute(
                "SELECT * FROM interest_links WHERE a=? OR b=?", (name, name)).fetchall()
        else:
            rows = self._conn().execute("SELECT * FROM interest_links").fetchall()
        return [InterestLink(r["a"], r["b"], r["weight"]) for r in rows]

    # ── projects ───────────────────────────────────────────────────────────────
    def get_project(self, project_id: str) -> Optional[Project]:
        r = self._conn().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return self._project_from_row(r) if r else None

    def find_project_by_name(self, name: str) -> Optional[Project]:
        r = self._conn().execute(
            "SELECT * FROM projects WHERE LOWER(name)=? LIMIT 1", (name.strip().lower(),)).fetchone()
        return self._project_from_row(r) if r else None

    def save_project(self, project: Project) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO projects (id, name, status, data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, status=excluded.status,
                 data=excluded.data, updated_at=excluded.updated_at""",
            (project.id, project.name, project.status, json.dumps(project.to_dict()),
             project.created_at, project.updated_at))
        c.commit()

    def list_projects(self, status: Optional[str] = None) -> list[Project]:
        if status:
            rows = self._conn().execute(
                "SELECT * FROM projects WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
        else:
            rows = self._conn().execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [self._project_from_row(r) for r in rows]

    @staticmethod
    def _project_from_row(r) -> Project:
        return Project.from_dict(_loads(r["data"], {}))

    # ── communication ──────────────────────────────────────────────────────────
    def get_communication(self, aspect: str) -> Optional[dict]:
        r = self._conn().execute("SELECT * FROM communication WHERE aspect=?", (aspect,)).fetchone()
        return dict(r) if r else None

    def save_communication(self, aspect: str, value: float, evidence_count: int) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO communication (aspect, value, evidence_count, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(aspect) DO UPDATE SET value=excluded.value,
                 evidence_count=excluded.evidence_count, updated_at=excluded.updated_at""",
            (aspect, value, evidence_count, time.time()))
        c.commit()

    def list_communication(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM communication").fetchall()]

    # ── learning ───────────────────────────────────────────────────────────────
    def get_learning(self, style: str) -> Optional[dict]:
        r = self._conn().execute("SELECT * FROM learning WHERE style=?", (style,)).fetchone()
        return dict(r) if r else None

    def save_learning(self, style: str, score: float, count: int) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO learning (style, score, count, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(style) DO UPDATE SET score=excluded.score,
                 count=excluded.count, updated_at=excluded.updated_at""",
            (style, score, count, time.time()))
        c.commit()

    def list_learning(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM learning ORDER BY score DESC").fetchall()]

    # ── relationship facts ─────────────────────────────────────────────────────
    def save_relationship_fact(self, fact: RelationshipFact) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO relationship_facts (id, kind, content, approved, sensitive, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, content=excluded.content,
                 approved=excluded.approved, sensitive=excluded.sensitive""",
            (fact.id, fact.kind, fact.content, int(fact.approved), int(fact.sensitive),
             fact.created_at))
        c.commit()

    def get_relationship_fact(self, fact_id: str) -> Optional[RelationshipFact]:
        r = self._conn().execute(
            "SELECT * FROM relationship_facts WHERE id=?", (fact_id,)).fetchone()
        return self._fact_from_row(r) if r else None

    def list_relationship_facts(self, approved_only: bool = False) -> list[RelationshipFact]:
        if approved_only:
            rows = self._conn().execute(
                "SELECT * FROM relationship_facts WHERE approved=1 ORDER BY created_at DESC").fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM relationship_facts ORDER BY created_at DESC").fetchall()
        return [self._fact_from_row(r) for r in rows]

    @staticmethod
    def _fact_from_row(r) -> RelationshipFact:
        return RelationshipFact(id=r["id"], kind=r["kind"], content=r["content"],
                                approved=bool(r["approved"]), sensitive=bool(r["sensitive"]),
                                created_at=r["created_at"])

    # ── events / metrics ───────────────────────────────────────────────────────
    def add_event(self, kind: str, data: Optional[dict] = None) -> None:
        c = self._conn()
        c.execute("INSERT INTO user_events (ts, kind, data) VALUES (?, ?, ?)",
                  (time.time(), kind, json.dumps(data or {})))
        c.commit()

    def events(self, kind: Optional[str] = None, limit: int = 100) -> list[dict]:
        if kind:
            rows = self._conn().execute(
                "SELECT * FROM user_events WHERE kind=? ORDER BY ts DESC LIMIT ?",
                (kind, limit)).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM user_events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = _loads(d["data"], {})
            out.append(d)
        return out

    def record_metric(self, metric: str, value: float = 1.0) -> None:
        c = self._conn()
        c.execute("INSERT INTO user_metrics (ts, metric, value) VALUES (?, ?, ?)",
                  (time.time(), metric, value))
        c.commit()

    # ── diagnostics ────────────────────────────────────────────────────────────
    def counts(self) -> dict:
        c = self._conn()
        q = lambda t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {"preferences": q("preferences"), "habits": q("habits"),
                "interests": q("interests"), "projects": q("projects"),
                "relationship_facts": q("relationship_facts"),
                "has_profile": self.get_profile() is not None}

    def health(self) -> dict:
        return {"status": "ok", **self.counts()}

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
