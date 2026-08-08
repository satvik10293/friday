"""
tests/test_browser.py — FRIDAY driving Chrome (core/web/browser + skills).

No real browser is launched: URL handling and the not-available/bad-url paths
are exercised directly, and the governed skills are tested against an injected
fake controller. Verifies read/navigate are SAFE and click/type are USER_APPROVAL.
"""

from __future__ import annotations

from core.web.browser import BrowserController, set_browser, _normalize_url


def test_normalize_url_accepts_http_and_bare_domains():
    assert _normalize_url("https://example.com") == "https://example.com"
    assert _normalize_url("example.com") == "https://example.com"
    assert _normalize_url("youtube.com/watch?v=x") == "https://youtube.com/watch?v=x"
    assert _normalize_url("not a url") is None
    assert _normalize_url("") is None


def test_normalize_url_blocks_local_internal_and_ip_targets():
    # SSRF-shaped targets an untrusted transcript could steer her at
    for bad in ("127.0.0.1", "http://127.0.0.1:8123", "192.168.1.1", "10.0.0.5",
                "169.254.169.254", "localhost", "foo.local", "box.internal",
                "file:///etc/passwd", "chrome://settings", "javascript:alert(1)"):
        assert _normalize_url(bad) is None, bad
    # ordinary public hosts still resolve
    assert _normalize_url("example.com") == "https://example.com"
    assert _normalize_url("https://en.wikipedia.org/wiki/X") == \
        "https://en.wikipedia.org/wiki/X"


def test_bad_url_is_reported_without_a_browser():
    r = BrowserController().open("this is not a url")
    assert r["ok"] is False and r["reason"] == "bad_url"
    # a private IP is refused as a bad URL before any launch
    assert BrowserController().open("169.254.169.254")["reason"] == "bad_url"


def test_not_available_when_playwright_missing(monkeypatch):
    monkeypatch.setattr(BrowserController, "available", staticmethod(lambda: False))
    r = BrowserController().open("example.com")
    assert r["ok"] is False and r["reason"] == "not_available"


class _FakeBrowser:
    def __init__(self):
        self.opened = None

    def open(self, url):
        self.opened = url
        return {"ok": True, "url": "https://x", "title": "X Home"}

    def read(self):
        return {"ok": True, "title": "X", "text": "hello world"}

    def screenshot(self, path=None):
        return {"ok": True, "path": "shot.png"}

    def click(self, text):
        return {"ok": True, "clicked": text}

    def type_text(self, text, selector=None):
        return {"ok": True, "typed": text}


def test_open_and_read_skills_delegate():
    from core.skills.builtin import browser_actions as B
    fb = _FakeBrowser()
    set_browser(fb)
    r = B.BrowserOpenSkill().run(None, url="example.com")
    assert r["ok"] and r["title"] == "X Home" and fb.opened == "example.com"
    assert "hello" in B.BrowserReadSkill().run(None)["text"]


def test_read_and_navigate_are_safe_but_interaction_is_gated():
    from core.skills.builtin.browser_actions import (
        BrowserOpenSkill, BrowserReadSkill, BrowserScreenshotSkill,
        BrowserClickSkill, BrowserTypeSkill)
    from core.skills.permissions import Permission
    for s in (BrowserOpenSkill, BrowserReadSkill, BrowserScreenshotSkill):
        assert s.permission == Permission.SAFE
    for s in (BrowserClickSkill, BrowserTypeSkill):
        assert s.permission == Permission.USER_APPROVAL


class _FakeLocator:
    def __init__(self, n):
        self._n = n
        self.clicked = False

    def count(self):
        return self._n

    @property
    def first(self):
        return self

    def click(self, timeout=None):
        self.clicked = True


class _FakePage:
    def __init__(self, text_n=0, button_n=0, link_n=0):
        self._n = {"text": text_n, "button": button_n, "link": link_n}
        self.url = "https://example.com"

    def get_by_text(self, text, exact=False):
        return _FakeLocator(self._n["text"])

    def get_by_role(self, role, name=None, exact=False):
        return _FakeLocator(self._n.get(role, 0))

    def wait_for_timeout(self, ms):
        pass


def test_click_clicks_a_single_exact_match():
    ctrl = BrowserController()
    ctrl._page = _FakePage(text_n=1)
    r = ctrl.click("Submit")
    assert r["ok"] is True and r["clicked"] == "Submit"


def test_click_refuses_ambiguous_matches():
    ctrl = BrowserController()
    ctrl._page = _FakePage(text_n=3)
    r = ctrl.click("Delete")
    assert r["ok"] is False and r["reason"] == "ambiguous"


def test_click_reports_not_found():
    ctrl = BrowserController()
    ctrl._page = _FakePage()
    assert ctrl.click("Nonexistent")["reason"] == "not_found"


def test_sensitive_host_regex_flags_risky_sites_only():
    from core.launcher.conversation import ConversationBridge as CB
    for u in ("https://mybank.com", "https://www.chase.com/x", "https://paypal.com",
              "https://shop.example.com/checkout",
              "https://accounts.google.com/security", "https://amazon.com/gp/buy/x"):
        assert CB._SENSITIVE_HOST_RE.search(u), u
    for u in ("https://en.wikipedia.org", "https://youtube.com", "https://example.com"):
        assert not CB._SENSITIVE_HOST_RE.search(u), u
