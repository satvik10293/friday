"""
core/harness/groq_provider.py — FRIDAY harness (Groq adapter)

Groq speaks the OpenAI `/chat/completions` format, so `GroqProvider` is now a
thin subclass of `OpenAICompatibleProvider` — the transport lives in one place.
Kept as a named class (and importable) for back-compat with existing callers and
so the config layer can list vendors uniformly; new code can equally use
`openai_compatible.groq()`.
"""

from __future__ import annotations

from typing import Optional

from .openai_compatible import OpenAICompatibleProvider, Transport
from .providers import Capability

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, *, model: str = _DEFAULT_MODEL, api_key: Optional[str] = None,
                 timeout_s: float = 20.0, name: str = "groq", capabilities=None,
                 cost_hint: float = 0.3, transport: Optional[Transport] = None) -> None:
        caps = capabilities or (Capability.TEXT, Capability.REASONING,
                                Capability.CODE, Capability.PLANNING)
        super().__init__(name=name, model=model, base_url=_BASE_URL,
                         api_key=api_key, api_key_env="GROQ_API_KEY",
                         capabilities=caps, cost_hint=cost_hint,
                         context_length=32768, timeout_s=timeout_s,
                         transport=transport)
