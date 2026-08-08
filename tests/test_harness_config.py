"""
tests/test_harness_config.py — config-aware wiring

The harness must respect the models the owner set in friday_config.json and turn
`harness.browser_seats` into browser providers — with a real API key always
beating a browser seat. Network-free (fake transport, config passed as a dict).
"""

from __future__ import annotations

from core.harness import build_registry, configured_vendors
from core.harness.browser_provider import BrowserProvider

_ALL_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
             "XAI_API_KEY", "GROQ_API_KEY")


def _clear_keys(monkeypatch):
    for env in _ALL_KEYS:
        monkeypatch.delenv(env, raising=False)


# ── model overrides ──────────────────────────────────────────────────────────
def test_registry_honors_configured_models(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    cfg = {"gemini_model": "gemini-3.6-flash", "groq_model": "openai/gpt-oss-120b"}

    reg = build_registry(config=cfg, transport=lambda *a: {})
    assert reg.get("gemini").info.model == "gemini-3.6-flash"
    assert reg.get("groq").info.model == "openai/gpt-oss-120b"


def test_registry_falls_back_to_default_model_when_unset(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    reg = build_registry(config={}, transport=lambda *a: {})   # no groq_model
    assert reg.get("groq").info.model == "llama-3.3-70b-versatile"


# ── browser seats (from the launcher's linked seats) ─────────────────────────
def test_api_key_beats_browser_seat(monkeypatch):
    # user has an OpenAI key AND a chatgpt browser seat → API wins, seat skipped
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    class _Driver:
        def is_ready(self): return True
        def ask(self, m, *, timeout_s): return "x"
        def close(self): ...

    reg = build_registry(config={}, transport=lambda *a: {},
                         browser_drivers={"chatgpt": _Driver(), "claude": _Driver()})
    names = {p.info.name for p in reg.all()}
    assert "openai" in names                    # the API provider
    assert "chatgpt-web" not in names           # its browser seat was deduped
    assert "claude-web" in names                # no anthropic key → seat kept
    assert isinstance(reg.get("claude-web"), BrowserProvider)


def test_configured_vendors_reflects_env(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    v = configured_vendors()
    assert v["groq"] is True and v["openai"] is False
