"""
tests/test_verified_run.py — the Verify gate governs one real skill (browser.open).

Deterministic (no network): a fake browser controller stands in for Chrome so the
two verdicts are provable in CI. The thesis under test is that `success` comes from
an INDEPENDENT re-read of the (fake) live browser via the objective runner — never
from the skill's own {"ok": ...} payload. The lying-skill case proves it directly.
"""

from urllib.parse import urlparse

from core.skills.registry import get_registry
from core.skills.builtin import register_builtins
from core.skills.verified_run import (
    run_verified, browser_open_objective, SkillOutcome,
)
from core.web.browser import set_browser


class _FakeBrowser:
    """Navigates for allowed hosts only; current() reports the live page — the
    independent signal the gate reads. Mirrors BrowserController's dict contracts."""

    def __init__(self):
        self._url = "about:blank"

    def open(self, url):
        host = urlparse(url if "://" in url else "https://" + url).hostname or ""
        if host == "example.com":
            self._url = "https://example.com/"
            return {"ok": True, "url": self._url, "title": "Example Domain"}
        return {"ok": False, "reason": "nav_failed", "error": "name not resolved"}

    def current(self):
        return {"ok": True, "url": self._url, "title": ""}


def _setup():
    register_builtins(get_registry())          # idempotent (registry .has() guards)


def test_honest_success_is_objectively_checked():
    _setup()
    set_browser(_FakeBrowser())
    try:
        out = run_verified("browser.open", {"url": "https://example.com"},
                           objective=browser_open_objective)
    finally:
        set_browser(None)
    assert isinstance(out, SkillOutcome)
    assert out.attempted is True
    assert out.happened is True                # skill ran and self-reports ok
    assert out.success is True                 # AND the live re-read confirms it
    assert out.tier == 1                       # decided objectively, not self-report


def test_honest_failure_is_reported():
    _setup()
    set_browser(_FakeBrowser())
    try:
        out = run_verified(
            "browser.open",
            {"url": "https://nonexistent-friday-test-9f3a2c7b.com"},
            objective=browser_open_objective)
    finally:
        set_browser(None)
    assert out.attempted is True
    assert out.happened is False               # skill self-reports failure
    assert out.success is False                # gate confirms the page never loaded
    assert out.tier == 1


def test_success_is_never_copied_from_self_report():
    """Even a skill that LIES with {"ok": True} must be ruled a failure when the
    objective check disagrees — success is the gate's verdict, not the producer's."""
    _setup()

    class _LyingBrowser(_FakeBrowser):
        def open(self, url):                   # claims success, never navigates
            return {"ok": True, "url": "https://example.com/", "title": "faked"}

    set_browser(_LyingBrowser())
    try:
        out = run_verified("browser.open", {"url": "https://example.com"},
                           objective=browser_open_objective)
    finally:
        set_browser(None)
    assert out.happened is True                # the skill claims it worked...
    assert out.success is False                # ...but the live page is about:blank
    assert out.tier == 1
