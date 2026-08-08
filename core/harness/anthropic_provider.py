"""
core/harness/anthropic_provider.py — FRIDAY harness (Claude adapter)

Anthropic's Messages API is not OpenAI-shaped — different endpoint, an
`x-api-key` + `anthropic-version` header pair, `system` as a top-level field,
and a `content[0].text` response — so Claude gets its own adapter behind the
same `ModelProvider` interface. Claude is strong at coding and careful, long-
context reasoning, so it declares those capabilities and sits in the council for
hard problems.

Same boundaries as every provider: never raises, key-gated via `available()`,
caller owns privacy, `transport` injectable for network-free tests.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional

from .openai_compatible import (_retryable_status, _short_http_error,
                                _status_of, render_chat_context)
from .providers import (BaseProvider, Capability, GenRequest, GenResult,
                        make_info)

Transport = Callable[[str, dict, dict, float], dict]

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _requests_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    import requests
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class AnthropicProvider(BaseProvider):
    def __init__(self, *, model: str = _DEFAULT_MODEL, api_key: Optional[str] = None,
                 api_url: str = _API_URL, timeout_s: float = 30.0,
                 name: str = "anthropic", capabilities=None, cost_hint: float = 1.1,
                 transport: Optional[Transport] = None) -> None:
        caps = capabilities or (Capability.TEXT, Capability.REASONING,
                                Capability.CODE, Capability.PLANNING)
        super().__init__(make_info(name, caps, kind="cloud", model=model,
                                   context_length=200000, cost_hint=cost_hint))
        self._api_url = api_url
        self._timeout_s = timeout_s
        self._api_key = (os.environ.get("ANTHROPIC_API_KEY", "") if api_key is None
                         else api_key)
        self._transport = transport or _requests_transport

    def available(self) -> bool:
        return bool(self._api_key)

    async def _generate(self, request: GenRequest) -> GenResult:
        if not self.available():
            return GenResult(provider=self.info.name, ok=False,
                             error="no API key configured (ANTHROPIC_API_KEY)")
        return await asyncio.to_thread(self._blocking, request)

    def _blocking(self, request: GenRequest) -> GenResult:
        system_parts = []
        if request.system:
            system_parts.append(request.system)
        block = render_chat_context(request.context)
        if block:
            system_parts.append("Context from FRIDAY's local state:\n" + block)

        payload = {"model": self.info.model, "max_tokens": request.max_tokens,
                   "temperature": request.temperature,
                   "messages": [{"role": "user", "content": request.prompt}]}
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop:
            payload["stop_sequences"] = request.stop
        headers = {"x-api-key": self._api_key, "anthropic-version": _API_VERSION,
                   "content-type": "application/json"}

        t0 = time.perf_counter()
        try:
            data = self._transport(self._api_url, headers, payload, self._timeout_s)
        except Exception as e:  # noqa: BLE001 — classify so retries aren't wasted
            status = _status_of(e)
            return GenResult(provider=self.info.name, ok=False, model=self.info.model,
                             error=_short_http_error(e),
                             latency_ms=(time.perf_counter() - t0) * 1000.0,
                             retryable=_retryable_status(status),
                             meta={"status": status} if status else {})
        latency = (time.perf_counter() - t0) * 1000.0

        text = _extract_text(data)
        stop_reason = data.get("stop_reason") or ""
        if not text:
            return GenResult(provider=self.info.name, ok=False, model=self.info.model,
                             error=f"empty answer ({stop_reason or 'empty'})",
                             finish_reason=stop_reason, latency_ms=latency, retryable=False)
        usage = data.get("usage") or {}
        return GenResult(provider=self.info.name, ok=True, text=text,
                         model=self.info.model, confidence=0.9, latency_ms=latency,
                         tokens=int(usage.get("output_tokens", 0)),
                         prompt_tokens=int(usage.get("input_tokens", 0)),
                         finish_reason=stop_reason,
                         meta={"kind": "cloud", "vendor": self.info.name})


def _extract_text(data: dict) -> str:
    """Concatenate the text blocks of a Messages response."""
    blocks = data.get("content") or []
    return "".join(b.get("text", "") for b in blocks
                   if isinstance(b, dict) and b.get("type", "text") == "text").strip()


def anthropic(*, model: str = _DEFAULT_MODEL, api_key: Optional[str] = None,
              transport: Optional[Transport] = None, **kw) -> AnthropicProvider:
    return AnthropicProvider(model=model, api_key=api_key, transport=transport, **kw)
