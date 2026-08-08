"""core/web — FRIDAY's window on the internet (Chrome via Playwright)."""

from .browser import BrowserController, get_browser, set_browser

__all__ = ["BrowserController", "get_browser", "set_browser"]
