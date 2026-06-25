"""
core/security/auth/sessions.py — FRIDAY 4.0 (M10)
Session authentication. A login mints a session with a CSPRNG token (stored hashed)
and a TTL; the token is what the client presents. Sessions can be expired or
revoked. Constant-time verification.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .store import AuthStore

_DEFAULT_TTL = 3600.0   # 1 hour


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Session:
    id: str
    actor: str
    created_at: float
    expires_at: float
    token: Optional[str] = None       # only at creation time

    def active(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) < self.expires_at


class SessionManager:
    def __init__(self, store: AuthStore, *, ttl: float = _DEFAULT_TTL) -> None:
        self._store = store
        self._ttl = ttl

    def create(self, actor: str, *, ttl: Optional[float] = None) -> Session:
        sid = uuid.uuid4().hex[:16]
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + (ttl if ttl is not None else self._ttl)
        c = self._store.conn()
        c.execute("INSERT INTO sessions (id, actor, token_hash, created_at, expires_at, revoked) "
                  "VALUES (?, ?, ?, ?, ?, 0)", (sid, actor, _hash(token), now, expires))
        c.commit()
        return Session(id=sid, actor=actor, created_at=now, expires_at=expires, token=token)

    def verify(self, token: str, *, now: Optional[float] = None) -> Optional[Session]:
        if not token:
            return None
        now = now or time.time()
        h = _hash(token)
        rows = self._store.conn().execute(
            "SELECT * FROM sessions WHERE revoked=0 AND expires_at > ?", (now,)).fetchall()
        for r in rows:
            if hmac.compare_digest(r["token_hash"], h):
                return Session(id=r["id"], actor=r["actor"], created_at=r["created_at"],
                               expires_at=r["expires_at"])
        return None

    def revoke(self, session_id: str) -> bool:
        c = self._store.conn()
        cur = c.execute("UPDATE sessions SET revoked=1 WHERE id=?", (session_id,))
        c.commit()
        return cur.rowcount > 0

    def purge_expired(self, *, now: Optional[float] = None) -> int:
        now = now or time.time()
        c = self._store.conn()
        cur = c.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        c.commit()
        return cur.rowcount
