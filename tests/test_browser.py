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


def test_bad_url_is_reported_without_a_browser():
    r = BrowserController().open("this is not a url")
    assert r["ok"] is False and r["reason"] == "bad_url"


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
