"""
tests/test_harness_providers_ext.py — FRIDAY harness (multi-vendor adapters)

Covers the OpenAI-compatible adapter (OpenAI / xAI / Gemini / Groq), the
Anthropic Claude adapter, and the env-based config wiring — all network-free via
injected transports and monkeypatched keys.
"""

from __future__ import annotations

import asyncio

import pytest

from core.harness import (GenRequest, anthropic, build_registry,
                          configured_vendors, gemini, groq, openai, xai_grok)


def run(coro):
    return asyncio.run(coro)


def _chat_ok(content="ok", tokens=5):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"completion_tokens": tokens}}


# ── OpenAI-compatible adapter ────────────────────────────────────────────────
def test_openai_compatible_call_shape():
    seen = {}

    def transport(url, headers, payload, timeout):
        seen.update(url=url, auth=headers["Authorization"], model=payload["model"],
                    roles=[m["role"] for m in payload["messages"]])
        return _chat_ok("gpt says hi", tokens=5)

    p = openai(model="gpt-4o", api_key="k", transport=transport)
    assert p.available()
    res = run(p.generate(GenRequest(prompt="hi", system="be nice")))
    assert res.ok and res.text == "gpt says hi" and res.tokens == 5
    assert "openai.com" in seen["url"] and seen["auth"] == "Bearer k"
    assert seen["model"] == "gpt-4o"
    assert seen["roles"] == ["system", "user"]      # system prepended


@pytest.mark.parametrize("factory,fragment", [
    (openai, "openai.com"), (xai_grok, "x.ai"),
    (gemini, "googleapis.com"), (groq, "groq.com"),
])
def test_vendor_endpoints(factory, fragment):
    seen = {}

    def transport(url, headers, payload, timeout):
        seen["url"] = url
        return _chat_ok("ok")

    prov = factory(api_key="k", transport=transport)
    res = run(prov.generate(GenRequest(prompt="x")))
    assert res.ok and fragment in seen["url"]


def test_vendor_key_gating(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = openai()
    assert p.available() is False
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False and "OPENAI_API_KEY" in res.error


def test_empty_answer_is_failure():
    p = openai(api_key="k", transport=lambda *a: _chat_ok(""))
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False and "empty" in res.error


# ── Anthropic Claude adapter ─────────────────────────────────────────────────
def test_anthropic_call_shape():
    seen = {}

    def transport(url, headers, payload, timeout):
        seen.update(url=url, key=headers["x-api-key"],
                    version=headers["anthropic-version"], system=payload.get("system"))
        return {"content": [{"type": "text", "text": "claude says hi"}],
                "usage": {"output_tokens": 7}}

    p = anthropic(model="claude-x", api_key="k", transport=transport)
    res = run(p.generate(GenRequest(prompt="hi", system="be nice")))
    assert res.ok and res.text == "claude says hi" and res.tokens == 7
    assert "anthropic.com" in seen["url"] and seen["key"] == "k"
    assert seen["version"] and seen["system"] == "be nice"


def test_anthropic_without_key():
    p = anthropic(api_key="")
    assert p.available() is False
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False and "ANTHROPIC_API_KEY" in res.error


# ── config wiring ────────────────────────────────────────────────────────────
_ALL_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
             "XAI_API_KEY", "GROQ_API_KEY")


def test_build_registry_registers_only_available(monkeypatch):
    for env in _ALL_KEYS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "k")

    reg = build_registry(transport=lambda *a: _chat_ok())
    names = {p.info.name for p in reg.all()}
    assert "local-intelligence" in names            # local always present
    assert {"openai", "groq"} <= names
    assert not ({"anthropic", "gemini", "xai-grok"} & names)


def test_configured_vendors(monkeypatch):
    for env in _ALL_KEYS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    v = configured_vendors()
    assert v["anthropic"] is True
    assert v["openai"] is False and v["gemini"] is False
