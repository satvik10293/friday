"""
core/web/browser.py — FRIDAY drives a real Chrome.

She controls a Chrome window through Playwright: open pages, read them, screenshot
them, and (governed) click and type. This is how she uses the live web and sites
you're signed into.

SECURITY (matches the 2026-08-08 review): this drives a DEDICATED FRIDAY Chrome
profile (its own user_data_dir under data/) using your INSTALLED Chrome binary
(channel="chrome"). You log into the sites you want her to use ONCE, in her
window; the session persists there. It NEVER copies cookies, the password DB, or
anything else out of your real Chrome profile -- the exact thing the review
flagged. Read/navigate is low-risk; anything that CLICKS or TYPES on a live,
logged-in site is a governed action (owner-confirmed), never taken unattended.

Playwright is imported lazily and everything degrades honestly: if Playwright or
Chrome isn't set up, the client reports not-ready instead of raising.

    first-run setup (once):
        .venv\\Scripts\\python.exe -m pip install playwright
        .venv\\Scripts\\python.exe -m playwright install chromium   # or use channel=chrome
"""

from __future__ import annotations

import ipaddress
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger("friday.web.browser")

_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _ROOT / "data" / "browser_profile"

_URL_RE = re.compile(r"^https?://", re.I)


def _is_public_host(host: str) -> bool:
    """Reject internal/local targets so an untrusted transcript can't steer the
    driven browser at localhost, the LAN, or a cloud-metadata endpoint (SSRF)."""
    h = (host or "").lower().split(":")[0]
    if not h or h == "localhost" or h.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return True                         # an ordinary hostname, not an IP literal
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _normalize_url(url: str) -> Optional[str]:
    u = (url or "").strip().strip("'\"")
    if not u:
        return None
    if not _URL_RE.match(u):
        # bare domain / obvious host -> https; otherwise not a URL
        if re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", u):
            u = "https://" + u
        else:
            return None
    # belt-and-suspenders: only http(s), and never a local/internal/IP-literal target
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not _is_public_host(parsed.hostname or ""):
        return None
    return u


class BrowserController:
    """A single Chrome window FRIDAY drives. Lazy, resilient; never raises out of
    a turn -- methods return {"ok": bool, ...}."""

    def __init__(self, *, profile_dir: Optional[str] = None,
                 channel: str = "chrome", headless: bool = False) -> None:
        self.profile_dir = str(profile_dir or _PROFILE_DIR)
        self.channel = channel
        self.headless = headless
        self._pw = None
        self._ctx = None
        self._page = None

    # ── availability ─────────────────────────────────────────────────────────
    @staticmethod
    def available() -> bool:
        """True if Playwright is importable (the driver dependency)."""
        try:
            import playwright  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        launch_kw = {"headless": self.headless}
        if self.channel:
            launch_kw["channel"] = self.channel
        self._ctx = self._pw.chromium.launch_persistent_context(
            self.profile_dir, **launch_kw)
        self._page = (self._ctx.pages[0] if self._ctx.pages
                      else self._ctx.new_page())
        return self._page

    def _not_ready(self) -> dict:
        return {"ok": False, "reason": "not_available",
                "error": "browser control isn't set up (install Playwright)"}

    # ── read / navigate (low-risk) ───────────────────────────────────────────
    def open(self, url: str) -> dict:
        target = _normalize_url(url)
        if not target:
            return {"ok": False, "reason": "bad_url", "error": f"not a URL: {url!r}"}
        if not self.available():
            return self._not_ready()
        try:
            page = self._ensure_page()
            page.goto(target, wait_until="domcontentloaded", timeout=30000)
            return {"ok": True, "url": page.url, "title": page.title()}
        except Exception as e:  # noqa: BLE001
            log.debug("browser.open failed", exc_info=True)
            return {"ok": False, "reason": "nav_failed", "error": f"{type(e).__name__}: {e}"}

    def read(self, *, max_chars: int = 4000) -> dict:
        if not self.available():
            return self._not_ready()
        try:
            page = self._ensure_page()
            text = (page.inner_text("body") or "").strip()
            text = re.sub(r"\n{3,}", "\n\n", text)
            return {"ok": True, "url": page.url, "title": page.title(),
                    "text": text[:max_chars]}
        except Exception as e:  # noqa: BLE001
            log.debug("browser.read failed", exc_info=True)
            return {"ok": False, "reason": "read_failed", "error": str(e)}

    def screenshot(self, path: Optional[str] = None) -> dict:
        if not self.available():
            return self._not_ready()
        try:
            page = self._ensure_page()
            out = path or str(_ROOT / "data" / "browser_shot.png")
            page.screenshot(path=out, full_page=False)
            return {"ok": True, "path": out, "url": page.url}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": "shot_failed", "error": str(e)}

    def current(self) -> dict:
        if self._page is None:
            return {"ok": False, "reason": "no_page"}
        try:
            return {"ok": True, "url": self._page.url, "title": self._page.title()}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # ── interaction (governed: owner-confirmed) ──────────────────────────────
    def click(self, text: str) -> dict:
        if not self.available():
            return self._not_ready()
        try:
            page = self._ensure_page()
            # EXACT match only: a fuzzy `.first` click on a live, logged-in page is
            # how you accidentally hit "Delete"/"Buy"/"Send". Try exact text, then
            # an exact button/link by name; refuse ambiguity rather than guess.
            for loc in (page.get_by_text(text, exact=True),
                        page.get_by_role("button", name=text, exact=True),
                        page.get_by_role("link", name=text, exact=True)):
                n = loc.count()
                if n == 1:
                    loc.first.click(timeout=8000)
                    page.wait_for_timeout(500)
                    return {"ok": True, "clicked": text, "url": page.url}
                if n > 1:
                    return {"ok": False, "reason": "ambiguous",
                            "error": f"{n} things match {text!r} -- be more specific"}
            return {"ok": False, "reason": "not_found",
                    "error": f"nothing exactly matching {text!r} on the page"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": "click_failed", "error": str(e)}

    def type_text(self, text: str, *, selector: Optional[str] = None) -> dict:
        if not self.available():
            return self._not_ready()
        try:
            page = self._ensure_page()
            if selector:
                page.fill(selector, text, timeout=8000)
            else:
                page.keyboard.insert_text(text)
            return {"ok": True, "typed": text[:60]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": "type_failed", "error": str(e)}

    def close(self) -> None:
        for obj in (self._ctx, self._pw):
            try:
                if obj is not None:
                    obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._page = self._pw = None


_controller: Optional[BrowserController] = None


def get_browser() -> BrowserController:
    """Process-wide controller (one Chrome window she reuses across turns)."""
    global _controller
    if _controller is None:
        _controller = BrowserController()
    return _controller


def set_browser(controller) -> None:
    """Inject a controller (tests / DI)."""
    global _controller
    _controller = controller
