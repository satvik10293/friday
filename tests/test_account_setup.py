"""Tests for the AI-account onboarding logic (core/launcher/account_setup.py).

GUI-free: only the AccountManager (keys, marker, status) is exercised. Everything
runs against a temp root/data dir so the real .env is never touched.
"""

import os

import pytest

from core.launcher.account_setup import (
    AccountManager, Provider, _providers, installed_chrome, maybe_prompt)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # the dev machine's real .env is loaded into os.environ on import; isolate it
    # so these tests see a clean slate (monkeypatch restores real keys afterward)
    for p in _providers():
        monkeypatch.delenv(p.env_var, raising=False)


@pytest.fixture
def mgr(tmp_path):
    return AccountManager(root=tmp_path, data_dir=tmp_path)


def test_providers_derived_from_harness():
    ids = {p.id for p in _providers()}
    # the harness vendors we onboard for
    assert {"openai", "anthropic", "gemini", "groq"} <= ids
    for p in _providers():
        assert isinstance(p, Provider)
        assert p.env_var and p.env_var == p.env_var.upper()
        assert "_KEY" in p.env_var


def test_save_key_writes_env_and_live_process(mgr):
    name = "OPENAI_API_KEY"
    try:
        assert mgr.key_present(name) is False
        assert mgr.save_key(name, "sk-test-123") is True
        # persisted to .env
        assert mgr.env_path.exists()
        assert "OPENAI_API_KEY=sk-test-123" in mgr.env_path.read_text(encoding="utf-8")
        # live in the process for this session
        assert os.environ.get(name) == "sk-test-123"
        assert mgr.key_present(name) is True
    finally:
        os.environ.pop(name, None)


def test_blank_key_clears(mgr):
    name = "GEMINI_API_KEY"
    try:
        mgr.save_key(name, "abc")
        assert mgr.key_present(name) is True
        assert mgr.save_key(name, "") is False
        assert os.environ.get(name) is None
        assert "GEMINI_API_KEY=abc" not in mgr.env_path.read_text(encoding="utf-8")
    finally:
        os.environ.pop(name, None)


def test_secret_never_leaks_key_name_only(mgr):
    # the .env stores only NAME=VALUE lines; no stray content
    try:
        mgr.save_key("GROQ_API_KEY", "gsk-secret")
        lines = [l for l in mgr.env_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert lines == ["GROQ_API_KEY=gsk-secret"]
    finally:
        os.environ.pop("GROQ_API_KEY", None)


def test_marker_and_should_prompt(mgr):
    assert mgr.is_done() is False
    assert mgr.should_prompt(headless=False) is True     # GUI, not done → prompt
    assert mgr.should_prompt(headless=True) is False      # headless → never
    mgr.mark_done({"configured": False})
    assert mgr.is_done() is True
    assert mgr.should_prompt(headless=False) is False     # done → never again


def test_status_and_summary_reflect_keys(mgr):
    name = "OPENAI_API_KEY"
    try:
        summary = mgr.summary()
        assert all(s["key"] is False for s in summary)
        mgr.save_key(name, "sk-x")
        openai = next(s for s in mgr.summary() if s["id"] == "openai")
        assert openai["key"] is True
        assert mgr.any_configured() is True
    finally:
        os.environ.pop(name, None)


def test_maybe_prompt_headless_is_noop(mgr):
    # headless must never open a window or block
    out = maybe_prompt(headless=True, manager=mgr)
    assert out["shown"] is False
    assert mgr.is_done() is False        # headless didn't mark anything


def test_browser_capability_flags():
    by_id = {p.id: p for p in _providers()}
    assert by_id["openai"].browser_site == "chatgpt"
    assert by_id["anthropic"].browser_site == "claude"
    assert by_id["groq"].browser_site is None      # key-only vendor


def test_installed_chrome_detection_is_a_path_or_none():
    got = installed_chrome()
    assert got is None or (isinstance(got, str) and got.lower().endswith(
        ("chrome.exe", "chrome", "chromium", "chromium-browser", "google chrome")))


def test_link_browser_uses_installed_chrome_channel(mgr, monkeypatch):
    # when Chrome is present we drive it via channel="chrome" and skip the
    # Chromium download; the driver must receive that channel.
    monkeypatch.setattr("core.launcher.account_setup.installed_chrome",
                        lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    monkeypatch.setattr(mgr, "ensure_playwright",
                        lambda on_status=None, download_chromium=True: (True, "ok"))
    captured = {}

    class _FakeDriver:
        def __init__(self, site, *, user_data_dir, headless, channel=None):
            captured["channel"] = channel
            captured["user_data_dir"] = user_data_dir

        def is_ready(self):
            return True

    import core.harness.browser_drivers as bd
    monkeypatch.setattr(bd, "PlaywrightChatDriver", _FakeDriver)
    p = next(pp for pp in mgr.providers() if pp.id == "openai")
    assert mgr.link_browser(p) is True
    assert captured["channel"] == "chrome"
    assert "chatgpt" in captured["user_data_dir"]
