"""
core/harness/openai_compatible.py — FRIDAY harness (OpenAI-compatible cloud adapter)

Most frontier vendors speak the same `/chat/completions` wire format, so ONE
adapter serves them all — only the base URL, model id, and API key differ:

    · OpenAI  (GPT)   — https://api.openai.com/v1
    · xAI     (Grok)  — https://api.x.ai/v1
    · Google  (Gemini)— https://generativelanguage.googleapis.com/v1beta/openai
    · Groq            — https://api.groq.com/openai/v1

Anthropic's Claude uses a different schema (see anthropic_provider.py). Each
vendor is exposed as a small factory (`openai()`, `xai_grok()`, `gemini()`,
`groq()`) that reads its key from the environment and declares sensible
capabilities/cost so the registry can route.

Honest boundaries carried over from the rest of the harness: never raises
(BaseProvider wraps it), key-gated via `available()`, and the CALLER owns
privacy filtering — nothing marked private should reach `request`. `transport`
is injectable so tests drive the full path without a network.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional

from .providers import (BaseProvider, Capability, GenRequest, GenResult,
                        make_info)

Transport = Callable[[str, dict, dict, float], dict]

_DEFAULT_CAPS = (Capability.TEXT, Capability.REASONING, Capability.CODE,
                 Capability.PLANNING)


def requests_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    """Default transport: a real POST via `requests`, imported lazily so this
    module never pulls in `requests` or touches the network at import time."""
    import requests
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def render_chat_context(context: Optional[dict]) -> str:
    """Compact rendering of caller-supplied, already-privacy-filtered context
    (standing / recent_turns / facts) into a system-message block. Shared by
    every chat-shaped provider so callers pass one context dict everywhere."""
    if not context:
        return ""
    parts: list[str] = []
    standing = (context.get("standing") or "").strip()
    if standing:
        parts.append("Standing memory:\n" + standing)
    turns = context.get("recent_turns") or []
    if turns:
        lines = [f"{t.get('role', '?')}: {t.get('text', '')}" for t in turns[-6:]]
        parts.append("Recent conversation:\n" + "\n".join(lines))
    facts = context.get("facts") or []
    if facts:
        parts.append("Relevant local facts:\n" + "\n".join(f"- {f}" for f in facts[:5]))
    return "\n\n".join(parts)[:2400]


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, *, name: str, model: str, base_url: str,
                 api_key: Optional[str] = None, api_key_env: str = "",
                 capabilities=_DEFAULT_CAPS, cost_hint: float = 1.0,
                 context_length: int = 8192, timeout_s: float = 30.0,
                 transport: Optional[Transport] = None) -> None:
        super().__init__(make_info(name, capabilities, kind="cloud", model=model,
                                   context_length=context_length, cost_hint=cost_hint))
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._api_key_env = api_key_env
        self._api_key = (os.environ.get(api_key_env, "") if api_key is None
                         else api_key)
        self._timeout_s = timeout_s
        self._transport = transport or requests_transport

    def available(self) -> bool:
        return bool(self._api_key)

    async def _generate(self, request: GenRequest) -> GenResult:
        if not self.available():
            return GenResult(provider=self.info.name, ok=False,
                             error=f"no API key configured ({self._api_key_env or 'api_key'})")
        return await asyncio.to_thread(self._blocking, request)

    def _blocking(self, request: GenRequest) -> GenResult:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        block = render_chat_context(request.context)
        if block:
            messages.append({"role": "system",
                             "content": "Context from FRIDAY's local state:\n" + block})
        messages.append({"role": "user", "content": request.prompt})

        payload = {"model": self.info.model, "messages": messages,
                   "temperature": request.temperature,
                   "max_tokens": request.max_tokens}
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        t0 = time.perf_counter()
        data = self._transport(self._endpoint, headers, payload, self._timeout_s)
        latency = (time.perf_counter() - t0) * 1000.0
        text = (data["choices"][0]["message"]["content"] or "").strip()
        if not text:
            return GenResult(provider=self.info.name, ok=False, model=self.info.model,
                             error="empty answer", latency_ms=latency)
        usage = data.get("usage") or {}
        return GenResult(provider=self.info.name, ok=True, text=text,
                         model=self.info.model, confidence=0.9, latency_ms=latency,
                         tokens=int(usage.get("completion_tokens", 0)),
                         meta={"kind": "cloud", "vendor": self.info.name})


# ── vendor factories ─────────────────────────────────────────────────────────
def openai(*, model: str = "gpt-4o", api_key: Optional[str] = None,
           transport: Optional[Transport] = None, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="openai", model=model, base_url="https://api.openai.com/v1",
        api_key=api_key, api_key_env="OPENAI_API_KEY", cost_hint=1.0,
        context_length=128000, transport=transport, **kw)


def xai_grok(*, model: str = "grok-2-latest", api_key: Optional[str] = None,
             transport: Optional[Transport] = None, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="xai-grok", model=model, base_url="https://api.x.ai/v1",
        api_key=api_key, api_key_env="XAI_API_KEY", cost_hint=0.9,
        context_length=131072, transport=transport, **kw)


def gemini(*, model: str = "gemini-1.5-pro", api_key: Optional[str] = None,
           transport: Optional[Transport] = None, **kw) -> OpenAICompatibleProvider:
    # Google's OpenAI-compatible surface; free tier available via AI Studio.
    caps = kw.pop("capabilities", (*_DEFAULT_CAPS, Capability.VISION))
    return OpenAICompatibleProvider(
        name="gemini", model=model, capabilities=caps,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key=api_key, api_key_env="GEMINI_API_KEY", cost_hint=0.4,
        context_length=1000000, transport=transport, **kw)


def groq(*, model: str = "llama-3.3-70b-versatile", api_key: Optional[str] = None,
         transport: Optional[Transport] = None, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="groq", model=model, base_url="https://api.groq.com/openai/v1",
        api_key=api_key, api_key_env="GROQ_API_KEY", cost_hint=0.3,
        context_length=32768, transport=transport, **kw)
