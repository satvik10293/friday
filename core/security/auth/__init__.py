"""
core/security/auth/ — FRIDAY 4.0 (M10)
Authentication & request-hardening layer. Closes the architecture review's
"unauthenticated local write API" risk: session + API-token authentication, origin
validation, CSRF tokens, security headers, and an audit trail for administrative
actions. Additive — does not modify the M3 security stack; composes alongside it.

Side-effect-free to import (the SQLite auth store opens only when a manager is
constructed).
"""

from __future__ import annotations

from .audit import AuthAudit, AuthAuditEntry
from .authenticator import AuthResult, Authenticator
from .headers import (SECURITY_HEADERS, csrf_token, origin_allowed,
                      secure_cookie_options, security_headers, validate_csrf)
from .sessions import Session, SessionManager
from .store import AuthStore
from .tokens import ApiToken, TokenManager

__all__ = [
    "Authenticator", "AuthResult", "SessionManager", "Session",
    "TokenManager", "ApiToken", "AuthAudit", "AuthAuditEntry", "AuthStore",
    "security_headers", "SECURITY_HEADERS", "csrf_token", "validate_csrf",
    "origin_allowed", "secure_cookie_options",
]
