"""
core/security/auth/tokens.py — FRIDAY 4.0 (M10)
API token authentication. Tokens are generated with the OS CSPRNG, returned to the
caller exactly once, and stored only as a sha256 hash — so the database never holds
a usable credential. Constant-time comparison on verify.
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


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class ApiToken:
    id: str
    name: str
    scopes: list
    created_at: float
    secret: Optional[str] = None     # only populated at creation time


class TokenManager:
    def __init__(self, store: AuthStore) -> None:
        self._store = store

    def create(self, name: str, scopes: Optional[list] = None) -> ApiToken:
        """Mint a new token. The plaintext secret is returned **once** in
        `.secret`; only its hash is persisted."""
        tid = uuid.uuid4().hex[:12]
        secret = f"frd_{secrets.token_urlsafe(32)}"
        c = self._store.conn()
        c.execute("INSERT INTO api_tokens (id, name, token_hash, scopes, created_at, revoked) "
                  "VALUES (?, ?, ?, ?, ?, 0)",
                  (tid, name, _hash(secret), ",".join(scopes or []), time.time()))
        c.commit()
        return ApiToken(id=tid, name=name, scopes=list(scopes or []),
                        created_at=time.time(), secret=secret)

    def verify(self, secret: str) -> Optional[ApiToken]:
        """Return the token record for a valid, non-revoked secret, else None.
        Uses constant-time hash comparison."""
        if not secret:
            return None
        h = _hash(secret)
        rows = self._store.conn().execute(
            "SELECT * FROM api_tokens WHERE revoked=0").fetchall()
        for r in rows:
            if hmac.compare_digest(r["token_hash"], h):
                return ApiToken(id=r["id"], name=r["name"],
                                scopes=r["scopes"].split(",") if r["scopes"] else [],
                                created_at=r["created_at"])
        return None

    def revoke(self, token_id: str) -> bool:
        c = self._store.conn()
        cur = c.execute("UPDATE api_tokens SET revoked=1 WHERE id=?", (token_id,))
        c.commit()
        return cur.rowcount > 0

    def list(self) -> list[dict]:
        rows = self._store.conn().execute(
            "SELECT id, name, scopes, created_at, revoked FROM api_tokens").fetchall()
        return [dict(r) for r in rows]
