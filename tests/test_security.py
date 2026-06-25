"""M10 — Authentication & request-hardening layer."""

import pytest

from core.security.auth import (Authenticator, AuthStore, SessionManager,
                                TokenManager, csrf_token, origin_allowed,
                                secure_cookie_options, security_headers,
                                validate_csrf)


@pytest.fixture
def auth_store(tmp_path):
    s = AuthStore(path=tmp_path / "auth.db")
    try:
        yield s
    finally:
        s.close()


# ── tokens ────────────────────────────────────────────────────────────────────────
def test_token_create_verify(auth_store):
    tm = TokenManager(auth_store)
    tok = tm.create("ci", ["read"])
    assert tok.secret and tok.secret.startswith("frd_")
    got = tm.verify(tok.secret)
    assert got is not None and got.name == "ci" and got.scopes == ["read"]


def test_token_secret_not_stored_plaintext(auth_store):
    tm = TokenManager(auth_store)
    tok = tm.create("x")
    row = auth_store.conn().execute("SELECT token_hash FROM api_tokens").fetchone()
    assert row["token_hash"] != tok.secret      # hashed at rest


def test_token_revoke(auth_store):
    tm = TokenManager(auth_store)
    tok = tm.create("x")
    assert tm.revoke(tok.id)
    assert tm.verify(tok.secret) is None


def test_bad_token_rejected(auth_store):
    assert TokenManager(auth_store).verify("frd_not_real") is None


# ── sessions ──────────────────────────────────────────────────────────────────────
def test_session_create_verify(auth_store):
    sm = SessionManager(auth_store)
    sess = sm.create("operator")
    assert sm.verify(sess.token).actor == "operator"


def test_session_expiry(auth_store):
    sm = SessionManager(auth_store, ttl=0.0)
    sess = sm.create("operator")
    assert sm.verify(sess.token) is None        # already expired


def test_session_revoke(auth_store):
    sm = SessionManager(auth_store)
    sess = sm.create("operator")
    sm.revoke(sess.id)
    assert sm.verify(sess.token) is None


# ── headers / csrf / origin ───────────────────────────────────────────────────────
def test_security_headers_present():
    h = security_headers()
    assert "Content-Security-Policy" in h
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"


def test_csrf_roundtrip():
    t = csrf_token()
    assert validate_csrf(t, t)
    assert not validate_csrf(t, "other")
    assert not validate_csrf(None, t)


def test_origin_validation():
    assert origin_allowed(None)                          # missing origin ok
    assert origin_allowed("http://127.0.0.1:5050")
    assert not origin_allowed("http://evil.example.com")


def test_secure_cookie_options():
    o = secure_cookie_options()
    assert o["httponly"] and o["samesite"] == "Strict"


# ── authenticator (the core contract) ─────────────────────────────────────────────
def test_write_requires_auth(auth_store):
    a = Authenticator(store=auth_store)
    res = a.authenticate(http_method="POST", origin="http://127.0.0.1:5050")
    assert not res.ok and "authentication required" in res.reason


def test_write_with_token_ok(auth_store):
    a = Authenticator(store=auth_store)
    tok = a.tokens.create("admin", ["admin"])
    res = a.authenticate(http_method="POST", api_token=tok.secret,
                         origin="http://127.0.0.1:5050", required_scope="admin")
    assert res.ok and res.actor == "admin" and res.method == "token"


def test_write_foreign_origin_blocked(auth_store):
    a = Authenticator(store=auth_store)
    tok = a.tokens.create("admin", ["admin"])
    res = a.authenticate(http_method="POST", api_token=tok.secret,
                         origin="http://evil.example.com")
    assert not res.ok and "origin" in res.reason


def test_missing_scope_denied(auth_store):
    a = Authenticator(store=auth_store)
    tok = a.tokens.create("reader", ["read"])
    res = a.authenticate(http_method="POST", api_token=tok.secret,
                         origin="http://127.0.0.1:5050", required_scope="admin")
    assert not res.ok and "scope" in res.reason


def test_open_read_allowed(auth_store):
    a = Authenticator(store=auth_store)
    res = a.authenticate(http_method="GET")
    assert res.ok and res.actor == "anonymous"


def test_protected_reads(auth_store):
    a = Authenticator(store=auth_store, protect_reads=True)
    assert not a.authenticate(http_method="GET").ok


def test_audit_records_decisions(auth_store):
    a = Authenticator(store=auth_store)
    a.authenticate(http_method="POST", origin="http://127.0.0.1:5050")  # denied
    fails = a.audit.failures()
    assert fails and fails[0]["result"] == "denied" and fails[0]["trace_id"]


def test_session_auth_via_authenticator(auth_store):
    a = Authenticator(store=auth_store)
    sess = a.login(actor="operator")
    res = a.authenticate(http_method="POST", session_token=sess.token,
                         origin="http://127.0.0.1:5050")
    assert res.ok and res.method == "session"
