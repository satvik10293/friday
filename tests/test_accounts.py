"""
FRIDAY's account access (core/web/accounts + the conversation route).

Pins the read/navigate side: spoken names resolve to the right site, a signed-out
page is detected (so she never pretends to have read a locked inbox), and the
route matches account phrases while leaving apps ("open spotify"), web search,
and "close ..." alone. No browser is launched by these tests.
"""

from __future__ import annotations

from core.web.accounts import ACCOUNTS, _looks_logged_out, resolve


# ── resolve ─────────────────────────────────────────────────────────────────────────
def test_resolve_aliases():
    assert resolve("gmail")[0] == "Gmail"
    assert resolve("my email")[0] == "Gmail"
    assert resolve("inbox")[0] == "Gmail"
    assert resolve("insta")[0] == "Instagram"
    assert resolve("whatsapp")[0] == "WhatsApp"
    assert resolve("calendar")[0] == "Google Calendar"


def test_resolve_unknown_is_none():
    assert resolve("spotify") is None
    assert resolve("") is None
    assert resolve("chrome") is None


def test_every_account_maps_to_https():
    for label, url in ACCOUNTS.values():
        assert url.startswith("https://") and label


# ── signed-out detection ─────────────────────────────────────────────────────────────
def test_logged_out_detection():
    assert _looks_logged_out("Sign in to continue to Gmail", "Gmail")
    assert _looks_logged_out("", "WhatsApp Web — Log in")
    assert not _looks_logged_out("Inbox (3)  Promotions  Primary", "Inbox - user@x")


# ── the conversation route regex (no instance / no browser needed) ───────────────────
def _route(phrase):
    from core.launcher.conversation import ConversationBridge
    m = ConversationBridge._ACCOUNT_RE.search(phrase)
    if not m:
        return None
    hit = resolve(m.group(2))
    read = bool(ConversationBridge._ACCOUNT_READ_RE.search(phrase))
    return (hit[0] if hit else None, read)


def test_route_matches_account_phrases():
    assert _route("open my gmail") == ("Gmail", False)
    assert _route("check my email") == ("Gmail", True)
    assert _route("any new whatsapp") == ("WhatsApp", True)
    assert _route("what's on my calendar") == ("Google Calendar", True)
    assert _route("open instagram") == ("Instagram", False)


def test_route_leaves_apps_and_search_and_close_alone():
    assert _route("open spotify") is None          # an app → app.open
    assert _route("open chrome") is None
    assert _route("search google for cats") is None  # → web search
    assert _route("close whatsapp") is None          # → close_app


# ── acting: draft + owner-confirmed send ─────────────────────────────────────────────
class _FakeBrowser:
    def __init__(self):
        self.opened: list[str] = []
        self.pressed: list[str] = []
        self._url = ""

    def open(self, url):
        self.opened.append(url)
        self._url = url
        return {"ok": True, "url": url, "title": ""}

    def press(self, combo):
        self.pressed.append(combo)
        return {"ok": True, "pressed": combo}

    def current(self):
        return {"ok": bool(self._url), "url": self._url, "title": ""}

    @staticmethod
    def available():
        return True


def test_resolve_contact_literal_and_map(monkeypatch):
    from core.web import accounts
    assert accounts.resolve_contact("john@x.com", "email") == "john@x.com"
    assert accounts.resolve_contact("+1 (555) 123-4567", "phone") == "15551234567"
    assert accounts.resolve_contact("bob", "email") is None      # unknown → refuse
    monkeypatch.setattr(accounts, "_contacts",
                        lambda: {"mom": {"phone": "15550001111", "email": "mom@x.com"}})
    assert accounts.resolve_contact("Mom", "phone") == "15550001111"
    assert accounts.resolve_contact("mom", "email") == "mom@x.com"


def test_compose_prefills_and_never_sends():
    from core.web.browser import set_browser
    from core.web.accounts import compose_email, compose_whatsapp
    fb = _FakeBrowser()
    set_browser(fb)
    try:
        r = compose_email("john@x.com", "Hi", "hello there")
        assert r["ok"] and r["account"] == "Gmail"
        assert "mail.google.com" in fb.opened[0] and "to=john%40x.com" in fb.opened[0]
        assert "body=hello%20there" in fb.opened[0]
        compose_whatsapp("15551234567", "on my way")
        assert "web.whatsapp.com/send" in fb.opened[1] and "phone=15551234567" in fb.opened[1]
        assert fb.pressed == []                    # composing NEVER sends
    finally:
        set_browser(None)


def test_send_uses_the_right_key_per_account():
    from core.web.browser import set_browser
    from core.web.accounts import send_open_draft
    fb = _FakeBrowser()
    set_browser(fb)
    try:
        send_open_draft("Gmail")
        send_open_draft("WhatsApp")
        assert fb.pressed == ["Control+Enter", "Enter"]
    finally:
        set_browser(None)


def test_browser_press_is_allowlisted():
    from core.web.browser import BrowserController
    # an arbitrary key is refused before anything is pressed
    assert BrowserController().press("Delete")["ok"] is False


def test_compose_command_regexes():
    from core.launcher.conversation import ConversationBridge as CB
    m = CB._SEND_EMAIL_RE.match("email john@x.com saying I'll be late")
    assert m and m.group("to").strip() == "john@x.com" and "late" in m.group("body")
    m = CB._SEND_EMAIL_RE.match("send an email to boss subject Update saying it's done")
    assert m and m.group("to").strip() == "boss" and m.group("subj").strip() == "Update"
    m = CB._SEND_WA_RE.match("whatsapp mom saying on my way")
    assert m and m.group("to").strip() == "mom" and "way" in m.group("body")
    assert CB._SEND_CONFIRM_RE.match("send it")
    assert not CB._SEND_CONFIRM_RE.match("send an email to bob saying hi")


# ── the conversation-level gate (the two HIGH findings' territory) ───────────────────
import time  # noqa: E402


def _bridge_with_fake_browser():
    from core.launcher.conversation import ConversationBridge
    from core.web.browser import set_browser
    fb = _FakeBrowser()
    set_browser(fb)
    return ConversationBridge(ios=None), fb


def test_draft_arms_but_never_presses_and_only_confirm_sends():
    b, fb = _bridge_with_fake_browser()
    try:
        key, _ = b._account_action("email john@x.com saying running late")
        assert key == "account.send:await_confirm"
        assert fb.pressed == []                    # DRAFT sends nothing
        assert b._pending_send is not None and b._pending_send["expires_at"] > time.time()
        key, ans = b._account_action("send it")
        assert key == "account.send" and fb.pressed == ["Control+Enter"]
        assert b._pending_send is None             # single-shot
    finally:
        from core.web.browser import set_browser
        set_browser(None)


def test_a_plain_yes_does_not_send_a_draft():
    b, fb = _bridge_with_fake_browser()
    try:
        b._account_action("email john@x.com saying hi")
        assert b._account_action("yes") is None    # 'yes' is not 'send it' → drops, no send
        assert fb.pressed == [] and b._pending_send is None
    finally:
        from core.web.browser import set_browser
        set_browser(None)


def test_expired_draft_is_never_sent(monkeypatch):
    b, fb = _bridge_with_fake_browser()
    try:
        b._account_action("email john@x.com saying hi")
        b._pending_send["expires_at"] = time.time() - 1     # forgotten, now stale
        assert b._account_action("send it") is None         # TTL: refuses, no press
        assert fb.pressed == [] and b._pending_send is None
    finally:
        from core.web.browser import set_browser
        set_browser(None)


def test_send_refuses_when_page_navigated_off_the_draft():
    b, fb = _bridge_with_fake_browser()
    try:
        b._account_action("email john@x.com saying hi")
        fb._url = "https://web.whatsapp.com/"        # the shared page moved elsewhere
        _, ans = b._account_action("send it")
        assert fb.pressed == [] and "won't send" in ans.lower()
    finally:
        from core.web.browser import set_browser
        set_browser(None)


def test_drafting_clears_other_confirm_flows():
    b, _ = _bridge_with_fake_browser()
    try:
        b._pending_command = ("x", {}, lambda a: "", time.time() + 60)
        b._pending_code = "print(1)"
        b._account_action("email john@x.com saying hi")    # arming a send
        assert b._pending_command is None and b._pending_code is None
    finally:
        from core.web.browser import set_browser
        set_browser(None)
