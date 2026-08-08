"""
core/harness/browser_drivers.py — FRIDAY harness (reference browser driver)

An EXPERIMENTAL Playwright-based `ChatDriver` that drives a real, logged-in chat
seat. Kept out of browser_provider.py so the tested provider abstraction never
depends on a browser; Playwright is imported lazily, so importing this module is
free and the rest of the harness works without it installed.

First-run setup (once):
    1. pip install playwright && playwright install chromium
    2. Launch with a persistent profile and log in BY HAND to each service:
         driver = PlaywrightChatDriver(SITES["claude"], user_data_dir="…/friday_seats/claude", headless=False)
       Log in in the window that opens; the session persists in user_data_dir.
    3. Thereafter FRIDAY reuses that logged-in profile.

This automates the user's OWN seat and does not evade detection. Selectors drift;
if a site stops working, update its `BrowserSite` in browser_provider.py.
"""

from __future__ import annotations

import time
from typing import Optional

from .browser_provider import BrowserSite


class PlaywrightChatDriver:
    """Drives one chat seat via a persistent (logged-in) Chromium profile.

    Lazy + resilient: if Playwright isn't installed or the seat isn't logged in,
    `is_ready()`/`ask()` fail softly (return False / raise a clear error that
    BrowserProvider converts to ok=False) rather than taking a turn down."""

    def __init__(self, site: BrowserSite, *, user_data_dir: str,
                 headless: bool = False, stability_s: float = 1.5) -> None:
        self._site = site
        self._user_data_dir = user_data_dir
        self._headless = headless
        self._stability_s = stability_s
        self._ctx = None
        self._page = None

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def _ensure_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("playwright not installed "
                               "(pip install playwright && playwright install chromium)") from e
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            self._user_data_dir, headless=self._headless)
        self._page = self._ctx.new_page()
        self._page.goto(self._site.url, wait_until="domcontentloaded")
        return self._page

    def is_ready(self) -> bool:
        try:
            page = self._ensure_page()
            page.goto(self._site.url, wait_until="domcontentloaded")
            page.wait_for_selector(self._site.input_selector, timeout=8000)
            return True
        except Exception:  # noqa: BLE001 — not logged in, blocked, or no playwright
            return False

    def ask(self, message: str, *, timeout_s: float = 90.0) -> str:
        page = self._ensure_page()
        box = page.wait_for_selector(self._site.input_selector, timeout=timeout_s * 1000)
        # count existing assistant messages so we can wait for the NEW one
        before = len(page.query_selector_all(self._site.response_selector))
        box.click()
        page.keyboard.insert_text(message)
        page.keyboard.press("Enter")
        return self._await_reply(page, before, timeout_s)

    def _await_reply(self, page, before: int, timeout_s: float) -> str:
        """Wait for a new assistant message, then until its text stops growing
        (streaming finished) or we hit the timeout."""
        deadline = time.time() + timeout_s
        last_text, stable_since = "", None
        while time.time() < deadline:
            nodes = page.query_selector_all(self._site.response_selector)
            if len(nodes) > before:
                text = (nodes[-1].inner_text() or "").strip()
                if text and text == last_text:
                    if stable_since and (time.time() - stable_since) >= self._stability_s:
                        return text
                    stable_since = stable_since or time.time()
                else:
                    last_text, stable_since = text, None
            page.wait_for_timeout(300)
        return last_text

    def close(self) -> None:
        for obj in (self._ctx, getattr(self, "_pw", None)):
            try:
                if obj is not None:
                    obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._page = None


def playwright_driver(vendor: str, *, user_data_dir: str, **kw) -> PlaywrightChatDriver:
    """Convenience for a known vendor in `SITES` ('chatgpt' | 'claude' | 'gemini')."""
    from .browser_provider import SITES
    site = SITES.get(vendor)
    if site is None:
        raise KeyError(f"unknown chat seat {vendor!r}; known: {sorted(SITES)}")
    return PlaywrightChatDriver(site, user_data_dir=user_data_dir, **kw)
