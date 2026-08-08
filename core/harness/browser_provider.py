"""
core/harness/browser_provider.py — FRIDAY harness (browser-seat adapter)

For the common case: the user pays for a chat PLAN (ChatGPT Plus, Claude Pro,
Gemini Advanced) but has no developer API key. FRIDAY can still use that model by
driving the seat the user already pays for — the logged-in web app — behind the
exact same `ModelProvider` interface every other backend uses. The council treats
a browser-driven answer identically to an API answer.

Honest boundaries (these are load-bearing, not disclaimers):
    · This automates the USER'S OWN logged-in seat on the USER'S machine. It does
      NOT evade detection, solve captchas, or bypass anti-bot — if a site blocks
      automation, the driver reports `ok=False` and the harness routes around it.
    · Automating these chat apps generally violates each vendor's Terms of
      Service. It is opt-in, off by default, and never auto-launched.
    · Slower and more fragile than an API (UIs change). Prefer an API key when one
      exists (Gemini/Groq even offer free keys); use this only for plan-only
      vendors like ChatGPT/Claude.

Testability: the actual page automation lives behind the `ChatDriver` protocol,
which is injectable — so `BrowserProvider` is unit-tested with a fake driver and
never needs a browser. A reference Playwright driver (experimental) is provided
for real use.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, runtime_checkable

from .openai_compatible import render_chat_context
from .providers import (BaseProvider, Capability, GenRequest, GenResult,
                        make_info)


@runtime_checkable
class ChatDriver(Protocol):
    """What BrowserProvider needs from any browser automation backend."""

    def is_ready(self) -> bool:
        """Cheap check: is the seat reachable and logged in (not on a login wall)?"""
        ...

    def ask(self, message: str, *, timeout_s: float) -> str:
        """Send one message to the chat app and return the assistant's reply text."""
        ...

    def close(self) -> None:
        ...


DriverFactory = Callable[[], ChatDriver]


class BrowserProvider(BaseProvider):
    def __init__(self, *, name: str, driver: Optional[ChatDriver] = None,
                 driver_factory: Optional[DriverFactory] = None,
                 capabilities=(Capability.TEXT, Capability.REASONING, Capability.CODE),
                 cost_hint: float = 2.0, timeout_s: float = 90.0,
                 model: str = "web-seat") -> None:
        # cost_hint high by default: a driven browser is the slowest, priciest-in-
        # time option, so the router prefers APIs/local and reaches for it last.
        super().__init__(make_info(name, capabilities, kind="browser", model=model,
                                   context_length=8192, cost_hint=cost_hint))
        self._driver = driver
        self._driver_factory = driver_factory
        self._timeout_s = timeout_s

    def available(self) -> bool:
        if self._driver is not None:
            try:
                return bool(self._driver.is_ready())
            except Exception:  # noqa: BLE001 — readiness probe must never raise
                return False
        return self._driver_factory is not None

    async def _generate(self, request: GenRequest) -> GenResult:
        return await asyncio.to_thread(self._blocking, request)

    def _blocking(self, request: GenRequest) -> GenResult:
        driver = self._resolve_driver()
        if driver is None:
            return GenResult(provider=self.info.name, ok=False,
                             error="no browser driver configured")
        try:
            if not driver.is_ready():
                return GenResult(provider=self.info.name, ok=False,
                                 error=f"{self.info.name}: seat not logged in / unreachable")
        except Exception as e:  # noqa: BLE001
            return GenResult(provider=self.info.name, ok=False,
                             error=f"{self.info.name}: readiness check failed: {e}")

        text = driver.ask(self._compose(request), timeout_s=self._timeout_s)
        text = (text or "").strip()
        if not text:
            return GenResult(provider=self.info.name, ok=False, model=self.info.model,
                             error="empty answer from browser seat")
        return GenResult(provider=self.info.name, ok=True, text=text,
                         model=self.info.model, confidence=0.85,
                         meta={"kind": "browser", "vendor": self.info.name})

    def _resolve_driver(self) -> Optional[ChatDriver]:
        if self._driver is None and self._driver_factory is not None:
            self._driver = self._driver_factory()
        return self._driver

    def _compose(self, request: GenRequest) -> str:
        """Chat apps have one input box, so fold system + context + prompt into
        a single message."""
        parts = []
        if request.system:
            parts.append(request.system)
        block = render_chat_context(request.context)
        if block:
            parts.append(block)
        parts.append(request.prompt)
        return "\n\n".join(parts)


# ── known chat seats ─────────────────────────────────────────────────────────
@dataclass
class BrowserSite:
    """Where a vendor's chat lives and how to reach its composer/response. These
    selectors are best-effort and DO drift — treat as a starting point."""
    vendor: str
    url: str
    input_selector: str
    response_selector: str


SITES: dict[str, BrowserSite] = {
    "chatgpt": BrowserSite(
        vendor="chatgpt", url="https://chatgpt.com/",
        input_selector="#prompt-textarea",
        response_selector='[data-message-author-role="assistant"]'),
    "claude": BrowserSite(
        vendor="claude", url="https://claude.ai/new",
        input_selector='div[contenteditable="true"]',
        response_selector='.font-claude-message'),
    "gemini": BrowserSite(
        vendor="gemini", url="https://gemini.google.com/app",
        input_selector='div[contenteditable="true"]',
        response_selector="message-content"),
}


def browser_provider(vendor: str, *, driver: Optional[ChatDriver] = None,
                     driver_factory: Optional[DriverFactory] = None,
                     **kw) -> BrowserProvider:
    """Build a BrowserProvider named `<vendor>-web` for a known or custom seat."""
    return BrowserProvider(name=f"{vendor}-web", driver=driver,
                           driver_factory=driver_factory, **kw)
