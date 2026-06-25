"""
core/security/auth/authenticator.py — FRIDAY 4.0 (M10)
The single front door for request authentication. Composes API-token + session
verification, origin validation, and scope/permission checks, and writes an audit
entry for every administrative decision.

Framework-agnostic: callers pass primitives (token, session token, origin, HTTP
method, required scope) extracted from their request. The Mission Control and
Portal servers wrap this; the rule it enforces is **no write without auth**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .audit import AuthAudit
from .headers import DEFAULT_ALLOWED_ORIGINS, origin_allowed
from .sessions import SessionManager
from .store import AuthStore
from .tokens import TokenManager

WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


@dataclass
class AuthResult:
    ok: bool
    actor: str = "anonymous"
    method: str = ""              # how they authenticated: token | session | none
    scopes: list = field(default_factory=list)
    reason: str = ""
    trace_id: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class Authenticator:
    def __init__(self, store: Optional[AuthStore] = None, *,
                 allowed_origins: Optional[Iterable[str]] = None,
                 protect_reads: bool = False) -> None:
        self._store = store if store is not None else AuthStore()
        self.tokens = TokenManager(self._store)
        self.sessions = SessionManager(self._store)
        self.audit = AuthAudit(self._store)
        self._origins = set(allowed_origins) if allowed_origins is not None \
            else set(DEFAULT_ALLOWED_ORIGINS)
        self._protect_reads = protect_reads

    @property
    def store(self) -> AuthStore:
        return self._store

    def authenticate(self, *, http_method: str = "GET", api_token: Optional[str] = None,
                     session_token: Optional[str] = None, origin: Optional[str] = None,
                     required_scope: Optional[str] = None,
                     action: str = "") -> AuthResult:
        """Decide whether a request is allowed. Writes always require a valid
        credential and an allowed origin; reads are open unless `protect_reads`."""
        method = (http_method or "GET").upper()
        is_write = method in WRITE_METHODS
        act = action or f"{method}"

        # 1) origin validation (CSRF / DNS-rebinding defense) — enforced for writes
        if is_write and not origin_allowed(origin, self._origins):
            return self._deny(act, "anonymous", f"origin not allowed: {origin}")

        # 2) identify the caller
        identity = self._identify(api_token, session_token)
        if identity is None:
            if is_write or self._protect_reads:
                return self._deny(act, "anonymous", "authentication required")
            return AuthResult(ok=True, actor="anonymous", method="none", reason="open read")

        actor, how, scopes = identity

        # 3) scope / permission check
        if required_scope and required_scope not in scopes and "admin" not in scopes:
            return self._deny(act, actor, f"missing scope: {required_scope}")

        entry = self.audit.record(actor, act, "allowed")
        return AuthResult(ok=True, actor=actor, method=how, scopes=scopes,
                          reason="ok", trace_id=entry.trace_id)

    def _identify(self, api_token, session_token):
        if api_token:
            tok = self.tokens.verify(api_token)
            if tok is not None:
                return tok.name, "token", list(tok.scopes)
        if session_token:
            sess = self.sessions.verify(session_token)
            if sess is not None:
                return sess.actor, "session", ["session"]
        return None

    def _deny(self, action: str, actor: str, reason: str) -> AuthResult:
        entry = self.audit.record(actor, action, "denied", detail=reason)
        return AuthResult(ok=False, actor=actor, method="none", reason=reason,
                          trace_id=entry.trace_id)

    # ── convenience ──────────────────────────────────────────────────────────────
    def bootstrap_token(self, name: str = "admin", scopes: Optional[list] = None):
        """Mint an initial admin token (e.g. for the operator / Mission Control)."""
        return self.tokens.create(name, scopes or ["admin"])

    def login(self, actor: str = "operator", **kw):
        return self.sessions.create(actor, **kw)

    def health(self) -> dict:
        return {"status": "ok", "tokens": len(self.tokens.list()),
                "protect_reads": self._protect_reads,
                "allowed_origins": sorted(self._origins)}
