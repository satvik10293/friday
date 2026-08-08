"""
core/harness/config.py — FRIDAY harness (wiring)

The one place that turns "the subscriptions the user has" into a live registry.
It reads which API keys are present in the environment (loaded from the
gitignored .env by core.infra.friday_secrets) and registers exactly those cloud
providers, always alongside the local mind. Absent a key, that vendor is simply
not registered — the harness stays honest to what the user actually has.

This keeps provider selection declarative: add a vendor to `_CLOUD_VENDORS` and
it lights up the moment its key exists, with no other code change.
"""

from __future__ import annotations

import os
from typing import Optional

from .anthropic_provider import anthropic
from .local_provider import LocalProvider
from .openai_compatible import gemini, groq, openai, xai_grok
from .orchestrator import HarnessOrchestrator
from .registry import ProviderRegistry

try:  # loads .env so GROQ/OPENAI/… keys are visible; optional in bare contexts
    from core.infra import friday_secrets  # noqa: F401
except Exception:  # noqa: BLE001
    pass

# (display name, env var that gates it, factory)
_CLOUD_VENDORS = (
    ("openai", "OPENAI_API_KEY", openai),
    ("anthropic", "ANTHROPIC_API_KEY", anthropic),
    ("gemini", "GEMINI_API_KEY", gemini),
    ("xai-grok", "XAI_API_KEY", xai_grok),
    ("groq", "GROQ_API_KEY", groq),
)


def configured_vendors() -> dict:
    """Which cloud vendors have a key present right now (for diagnostics/UX)."""
    return {name: bool(os.environ.get(env)) for name, env, _ in _CLOUD_VENDORS}


def build_registry(*, include_local: bool = True, only_available: bool = True,
                   transport=None, local_ios=None,
                   browser_drivers: Optional[dict] = None) -> ProviderRegistry:
    """Register the local mind, every cloud vendor whose API key is present, and
    (opt-in) a browser-seat provider for any vendor the user drives via a logged-in
    chat app. `transport` is forwarded to the cloud adapters so tests wire fakes;
    `only_available=False` registers configured-but-keyless vendors too.

    `browser_drivers` maps a vendor name (e.g. "chatgpt", "claude") to a
    `ChatDriver` — for plan-only users with no API key. This is how the same
    council reaches a paid seat the user has but can't call via API."""
    reg = ProviderRegistry()
    if include_local:
        reg.register(LocalProvider(ios=local_ios))
    for _name, _env, factory in _CLOUD_VENDORS:
        provider = factory(transport=transport)
        if only_available and not provider.available():
            continue
        reg.register(provider)
    for vendor, driver in (browser_drivers or {}).items():
        from .browser_provider import browser_provider
        reg.register(browser_provider(vendor, driver=driver))
    return reg


def build_orchestrator(*, transport=None, local_ios=None, only_available: bool = True,
                       include_local: bool = True,
                       browser_drivers: Optional[dict] = None,
                       **kw) -> HarnessOrchestrator:
    """A ready-to-use hybrid orchestrator over the user's configured providers.
    Callers use `.run_auto(objective)` for route-simple / council-hard behaviour.
    Pass `include_local=False` for a pure cloud-subscription council (the
    conversation bridge does this — the local mind has its own turn)."""
    reg = build_registry(include_local=include_local, transport=transport,
                         local_ios=local_ios, only_available=only_available,
                         browser_drivers=browser_drivers)
    return HarnessOrchestrator(reg, **kw)
