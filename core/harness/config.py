"""
core/harness/config.py — FRIDAY harness (wiring)

The one place that turns "the subscriptions the user has" into a live registry.
It registers the local mind plus exactly the cloud vendors whose API key is
present in the environment (loaded from the gitignored .env by
core.infra.friday_secrets), and it respects the per-vendor MODEL the owner chose
in friday_config.json (`openai_model`, `gemini_model`, `groq_model`, …) so the
council uses the models the rest of FRIDAY already uses. Keys stay env-only — the
config file is tracked, so secrets never belong in it.

For plan-but-no-key users it also (opt-in) registers a browser-seat provider for
any vendor enabled under `harness.browser_seats` — a real API key always wins
over driving the browser.

Declarative: add a vendor to `_CLOUD_VENDORS` and it lights up the moment its key
exists, with no other code change.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
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

log = logging.getLogger("friday.harness.config")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "friday_config.json"

# (display name, env var that gates it, config-key prefix, factory)
_CLOUD_VENDORS = (
    ("openai", "OPENAI_API_KEY", "openai", openai),
    ("anthropic", "ANTHROPIC_API_KEY", "anthropic", anthropic),
    ("gemini", "GEMINI_API_KEY", "gemini", gemini),
    ("xai-grok", "XAI_API_KEY", "xai", xai_grok),
    ("groq", "GROQ_API_KEY", "groq", groq),
)

# which API vendor a browser seat stands in for — a real key beats the browser
_BROWSER_TO_API = {"chatgpt": "openai", "claude": "anthropic",
                   "gemini": "gemini", "grok": "xai-grok"}


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def configured_vendors() -> dict:
    """Which cloud vendors have a key present right now (for diagnostics/UX)."""
    return {name: bool(os.environ.get(env)) for name, env, _p, _f in _CLOUD_VENDORS}


def build_registry(*, include_local: bool = True, only_available: bool = True,
                   transport=None, local_ios=None,
                   browser_drivers: Optional[dict] = None,
                   config: Optional[dict] = None) -> ProviderRegistry:
    """Register the local mind, every cloud vendor whose API key is present (using
    the owner's configured model), and (opt-in) browser-seat providers.

    `transport` is forwarded to the cloud adapters so tests wire fakes;
    `only_available=False` registers configured-but-keyless vendors too. `config`
    overrides the on-disk friday_config.json (tests pass a dict)."""
    cfg = config if config is not None else _load_config()
    reg = ProviderRegistry()
    if include_local:
        reg.register(LocalProvider(ios=local_ios))
    for _name, _env, prefix, factory in _CLOUD_VENDORS:
        kwargs = {"transport": transport}
        model = (cfg.get(f"{prefix}_model") or "").strip()
        if model:
            kwargs["model"] = model                 # honor the owner's chosen model
        provider = factory(**kwargs)
        if only_available and not provider.available():
            continue
        reg.register(provider)
    for vendor, driver in (browser_drivers or {}).items():
        if reg.has(_BROWSER_TO_API.get(vendor, vendor)):
            continue                                # a real API key wins
        from .browser_provider import browser_provider
        reg.register(browser_provider(vendor, driver=driver))
    return reg


def browser_drivers_from_config(config: Optional[dict] = None) -> dict:
    """Build `{vendor: PlaywrightChatDriver}` for every seat enabled under
    `harness.browser_seats` in friday_config.json. Construction is cheap and does
    not launch a browser (Playwright loads lazily on first use), so this is safe
    to call at boot even when Playwright is not installed."""
    cfg = config if config is not None else _load_config()
    seats = ((cfg.get("harness") or {}).get("browser_seats") or {})
    drivers: dict = {}
    for vendor, spec in seats.items():
        if not (isinstance(spec, dict) and spec.get("enabled")):
            continue
        try:
            from .browser_drivers import playwright_driver
            drivers[vendor] = playwright_driver(
                vendor,
                user_data_dir=spec.get("user_data_dir") or f"data/seats/{vendor}",
                channel=spec.get("channel") or "chrome",
                headless=bool(spec.get("headless", False)))
        except Exception:  # noqa: BLE001 — a bad seat spec must not break boot
            log.debug("browser seat %r not built", vendor, exc_info=True)
    return drivers


def build_orchestrator(*, transport=None, local_ios=None, only_available: bool = True,
                       include_local: bool = True,
                       browser_drivers: Optional[dict] = None,
                       config: Optional[dict] = None,
                       **kw) -> HarnessOrchestrator:
    """A ready-to-use hybrid orchestrator over the user's configured providers.
    Callers use `.run_auto(objective)` for route-simple / council-hard behaviour.
    Pass `include_local=False` for a pure cloud-subscription council (the
    conversation bridge does this — the local mind has its own turn)."""
    reg = build_registry(include_local=include_local, transport=transport,
                         local_ios=local_ios, only_available=only_available,
                         browser_drivers=browser_drivers, config=config)
    return HarnessOrchestrator(reg, **kw)
