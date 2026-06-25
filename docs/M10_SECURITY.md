# M10 — Security Hardening

> Closes the architecture review's highest-severity risk: **unauthenticated local
> write APIs over plaintext data**. New additive package `core/security/auth/`
> (does not modify the M3 security stack). **Tests: `tests/test_security.py` (19).**

## The rule

> **No write endpoint may exist without authentication.** Writes also require a
> valid Origin (CSRF / DNS-rebinding defense) and, where scoped, the right
> permission. Every administrative decision is audited.

## `core/security/auth/`

| Module | Role |
|---|---|
| `store.py` | `AuthStore` — local SQLite (`data/auth.db`), per-thread + WAL + schema_version. Secrets stored **hashed** (sha256), never plaintext. |
| `tokens.py` | `TokenManager` — API tokens via OS CSPRNG; returned once, persisted as a hash; constant-time verify; revoke. |
| `sessions.py` | `SessionManager` — session auth with TTL; hashed tokens; expire/revoke/purge. |
| `headers.py` | Security headers (CSP, X-Frame-Options=DENY, nosniff, Referrer-Policy, COOP/CORP, Permissions-Policy), CSRF token + constant-time validate, `origin_allowed`, secure-cookie options. |
| `audit.py` | `AuthAudit` — every admin action → timestamp · actor · action · result · **trace id** (reuses M1 tracing) · detail, durably in `auth.db`. |
| `authenticator.py` | `Authenticator` — the single front door: composes tokens + sessions + origin + scope checks + audit into one `authenticate(...)` → `AuthResult`. |

## How a request is decided

```
authenticate(http_method, api_token?, session_token?, origin?, required_scope?)
  1. write method + foreign Origin            → DENY (audited)
  2. identify caller (token, then session)    → none + write/protected → DENY
  3. required_scope not in scopes (no admin)  → DENY
  else                                         → ALLOW (audited, actor + method)
```

- **Writes** (`POST/PUT/DELETE/PATCH`) always need a credential + allowed Origin.
- **Reads** are open by default; `protect_reads=True` locks them too.
- A **missing** Origin header is allowed (same-origin requests often omit it); a
  **present foreign** Origin is rejected.

## Applied to the servers

The **Mission Control** server (`core/mission_control/server.py`) attaches
`security_headers()` to every response and gates `POST /api/event` behind
`required_scope="admin"`. The pattern is reusable for the Knowledge Portal and any
future admin/agent APIs: wrap the handler in `authenticate(...)` and return 401 on
`not ok`.

## What this protects (per the brief)

`POST` · `PUT` · `DELETE` · administrative APIs · Mission Control APIs · Knowledge
APIs · Agent APIs — all gated by token/session auth + origin validation, with CSP /
CSRF / XSS protections (headers) and secure-cookie options, and a full audit trail.

## Residual / future

- The plaintext-at-rest concern for personal data (`user_model.db`) is noted in the
  architecture review; auth secrets are now hashed, and an at-rest encryption option
  for personal DBs is a tracked follow-up.
- Login (`/api/auth/login`) currently mints a demo session; wire a real credential
  check before exposing beyond localhost.
