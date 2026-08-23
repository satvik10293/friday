"""
Gmail through the API (Google blocks sign-in on automation browsers, so Friday
reads/sends Gmail over the API instead). No network is touched — the Google
service is mocked.
"""

from __future__ import annotations

import base64

from core.launcher.conversation import ConversationBridge
from core.web.gmail_api import GmailClient


# ── a mock of the googleapiclient service (svc.users().messages().<op>().execute())
class _Exec:
    def __init__(self, val):
        self._val = val

    def execute(self):
        return self._val


class _FakeMsgs:
    def __init__(self, headers_by_id):
        self.headers_by_id = headers_by_id
        self.sent: list = []

    def list(self, userId, q, maxResults):
        ids = list(self.headers_by_id)[:maxResults]
        return _Exec({"messages": [{"id": i} for i in ids]})

    def get(self, userId, id, format, metadataHeaders):
        hdrs, snippet = self.headers_by_id[id]
        return _Exec({"payload": {"headers": [{"name": k, "value": v}
                                              for k, v in hdrs.items()]},
                      "snippet": snippet})

    def send(self, userId, body):
        self.sent.append(body)
        return _Exec({"id": "x"})


class _FakeService:
    def __init__(self, msgs):
        self._m = msgs

    def users(self):
        m = self._m

        class _U:
            def messages(self):
                return m
        return _U()


# ── GmailClient primitives ──────────────────────────────────────────────────────────
def test_not_available_without_credentials():
    c = GmailClient()                              # libs installed, but no creds/token
    assert c.credentials_present() is False
    assert c.available() is False
    assert "connected" in c.setup_hint().lower() or "installed" in c.setup_hint().lower()


def test_check_formats_headers_and_snippet(monkeypatch):
    msgs = _FakeMsgs({"1": ({"From": "Alice <a@x.com>", "Subject": "Hi"}, "hello there"),
                      "2": ({"From": "Bob <b@x.com>", "Subject": "Yo"}, "sup")})
    c = GmailClient()
    monkeypatch.setattr(c, "_service", lambda: _FakeService(msgs))
    r = c.check(max_results=2)
    assert r["ok"] and len(r["messages"]) == 2
    assert r["messages"][0] == {"from": "Alice <a@x.com>", "subject": "Hi",
                                "snippet": "hello there"}


def test_send_builds_a_base64url_mime(monkeypatch):
    msgs = _FakeMsgs({})
    c = GmailClient()
    monkeypatch.setattr(c, "_service", lambda: _FakeService(msgs))
    r = c.send("to@x.com", "Subj", "the body")
    assert r["ok"] and len(msgs.sent) == 1
    decoded = base64.urlsafe_b64decode(msgs.sent[0]["raw"]).decode()
    assert "to@x.com" in decoded and "Subj" in decoded and "the body" in decoded


def test_service_none_degrades_honestly(monkeypatch):
    c = GmailClient()
    monkeypatch.setattr(c, "_service", lambda: None)
    assert c.check()["ok"] is False
    assert c.send("a@b.com", "s", "b")["ok"] is False


# ── conversation wiring ─────────────────────────────────────────────────────────────
def test_summarize_email():
    b = ConversationBridge(ios=None)
    assert b._summarize_email([]) == "No unread emails."
    s = b._summarize_email([{"from": "Alice <a@x.com>", "subject": "Hi"},
                            {"from": "Bob <b@x.com>", "subject": "Yo"}])
    assert "2 unread emails" in s and "from Alice: Hi" in s and "from Bob: Yo" in s


def test_read_gmail_setup_hint_when_not_connected():
    b = ConversationBridge(ios=None)
    ans = b._read_gmail()                           # no creds in the repo data dir
    assert "connected" in ans.lower() or "installed" in ans.lower()


def test_gmail_send_routes_through_the_api(monkeypatch):
    from core.web import gmail_api

    class _FakeGmail:
        def __init__(self):
            self.sent: list = []

        def available(self):
            return True

        def send(self, to, subject, body):
            self.sent.append((to, subject, body))
            return {"ok": True}

    fake = _FakeGmail()
    monkeypatch.setattr(gmail_api, "get_gmail", lambda: fake)
    b = ConversationBridge(ios=None)

    key, ans = b._account_action("email john@x.com saying hello there")
    assert key == "account.send:await_confirm" and "via Gmail" in ans
    assert b._pending_send and b._pending_send["method"] == "gmail_api"
    assert fake.sent == []                          # drafting NEVER sends

    key, ans = b._account_action("send it")
    assert key == "account.send" and "Sent your email" in ans
    assert fake.sent == [("john@x.com", "(no subject)", "hello there")]
