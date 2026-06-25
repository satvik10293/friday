"""
core/security/auth/headers.py — FRIDAY 4.0 (M10)
Request-hardening primitives: security headers (CSP/XSS/clickjacking), CSRF tokens,
origin validation, and secure-cookie options. Framework-agnostic — these return
plain values the Mission Control / Portal servers attach to responses.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Iterable, Optional

# A strict, self-contained CSP: same-origin only, no inline script except what we
# ship (Mission Control inlines its bootstrap), no framing, no external connects.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

# Loopback-only by default (no cloud, localhost-only cockpit).
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5050", "http://localhost:5050",
    "http://127.0.0.1:5000", "http://localhost:5000",
)


def security_headers(extra: Optional[dict] = None) -> dict:
    h = dict(SECURITY_HEADERS)
    if extra:
        h.update(extra)
    return h


def origin_allowed(origin: Optional[str], allowed: Optional[Iterable[str]] = None) -> bool:
    """True if `origin` is in the allowlist. A *missing* Origin header (same-origin
    non-CORS requests often omit it) is permitted; a *present, foreign* Origin is
    rejected — the DNS-rebinding / CSRF defense."""
    if not origin:
        return True
    allowed = set(allowed) if allowed is not None else set(DEFAULT_ALLOWED_ORIGINS)
    return origin in allowed


def csrf_token() -> str:
    return secrets.token_urlsafe(24)


def validate_csrf(expected: Optional[str], provided: Optional[str]) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def secure_cookie_options(*, https: bool = False) -> dict:
    """Cookie flags for session cookies: HttpOnly + SameSite=Strict (Secure only
    over HTTPS — loopback HTTP can't set Secure or the cookie is dropped)."""
    return {"httponly": True, "samesite": "Strict", "secure": bool(https)}
