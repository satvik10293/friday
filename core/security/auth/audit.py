"""
core/security/auth/audit.py — FRIDAY 4.0 (M10)
Authentication / administrative audit trail. Every administrative action records a
timestamp, actor, action, result, and trace id — durably, in the local auth DB.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .store import AuthStore

try:
    from core.observability.tracing import get_trace_id, new_trace_id
except Exception:  # pragma: no cover - observability always present, but stay safe
    def new_trace_id() -> str:  # type: ignore
        import uuid
        return uuid.uuid4().hex[:16]

    def get_trace_id():  # type: ignore
        return None


@dataclass
class AuthAuditEntry:
    ts: float
    actor: str
    action: str
    result: str
    trace_id: str
    detail: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class AuthAudit:
    def __init__(self, store: AuthStore) -> None:
        self._store = store

    def record(self, actor: str, action: str, result: str, *,
               trace_id: Optional[str] = None, detail: str = "") -> AuthAuditEntry:
        tid = trace_id or get_trace_id() or new_trace_id()
        ts = time.time()
        c = self._store.conn()
        c.execute("INSERT INTO auth_audit (ts, actor, action, result, trace_id, detail) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (ts, actor, action, result, tid, detail))
        c.commit()
        return AuthAuditEntry(ts=ts, actor=actor, action=action, result=result,
                              trace_id=tid, detail=detail)

    def recent(self, limit: int = 100, *, action: Optional[str] = None) -> list[dict]:
        if action:
            rows = self._store.conn().execute(
                "SELECT * FROM auth_audit WHERE action=? ORDER BY ts DESC LIMIT ?",
                (action, limit)).fetchall()
        else:
            rows = self._store.conn().execute(
                "SELECT * FROM auth_audit ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def failures(self, limit: int = 100) -> list[dict]:
        rows = self._store.conn().execute(
            "SELECT * FROM auth_audit WHERE result='denied' ORDER BY ts DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
