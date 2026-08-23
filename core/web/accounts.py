"""
core/web/accounts.py — FRIDAY reads the accounts you're signed into.

She drives her DEDICATED Chrome profile (core/web/browser.py). You log into each
account ONCE, in her window; the session persists there — she never sees your
passwords and never touches your real Chrome profile.

This module is the read/navigate side only: resolve a spoken account name to its
site, open it, and read the page text. ACTING on an account (send an email,
message, or post) is a separate, owner-confirmed path — it is never done here and
never unattended.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger("friday.web.accounts")

# spoken alias -> (display name, url). Matched exact-first, then by substring, so
# "open my email", "check gmail", "read my inbox" all resolve to Gmail.
ACCOUNTS: dict[str, tuple[str, str]] = {
    "gmail":     ("Gmail",     "https://mail.google.com/mail/u/0/#inbox"),
    "email":     ("Gmail",     "https://mail.google.com/mail/u/0/#inbox"),
    "mail":      ("Gmail",     "https://mail.google.com/mail/u/0/#inbox"),
    "inbox":     ("Gmail",     "https://mail.google.com/mail/u/0/#inbox"),
    "instagram": ("Instagram", "https://www.instagram.com/"),
    "insta":     ("Instagram", "https://www.instagram.com/"),
    "whatsapp":  ("WhatsApp",  "https://web.whatsapp.com/"),
    "google":    ("Google",    "https://www.google.com/"),
    "calendar":  ("Google Calendar", "https://calendar.google.com/r"),
}


def resolve(name: str) -> Optional[tuple[str, str]]:
    """(display, url) for a spoken account name, or None if unknown."""
    q = (name or "").lower().strip().strip(".?!")
    if not q:
        return None
    if q in ACCOUNTS:
        return ACCOUNTS[q]
    for alias, hit in ACCOUNTS.items():
        if alias in q or q in alias:
            return hit
    return None


def open_account(name: str) -> dict:
    """Open the account's site in her browser (where you're logged in). This is
    also how you FIRST log in: open it once, sign in, and the session persists."""
    hit = resolve(name)
    if hit is None:
        return {"ok": False, "error": f"I don't know an account called {name!r}."}
    label, url = hit
    from core.web.browser import get_browser
    result = get_browser().open(url)
    result["account"] = label
    return result


def read_account(name: str, *, max_chars: int = 2500,
                 settle_s: float = 2.5) -> dict:
    """Open the account and read the visible page text. These are single-page
    apps, so give them a moment to render before reading. If the read comes back
    looking like a sign-in page, the caller should say so (you're not logged in
    yet), never pretend to have read your inbox."""
    hit = resolve(name)
    if hit is None:
        return {"ok": False, "error": f"I don't know an account called {name!r}."}
    label, url = hit
    from core.web.browser import get_browser
    browser = get_browser()
    opened = browser.open(url)
    if not opened.get("ok"):
        opened["account"] = label
        return opened
    time.sleep(settle_s)
    result = browser.read(max_chars=max_chars)
    result["account"] = label
    result["logged_in"] = not _looks_logged_out(result.get("text", ""),
                                                result.get("title", ""))
    return result


_LOGGED_OUT_HINTS = (
    "sign in", "log in", "login", "create account", "forgot password",
    "enter your phone number", "to continue to gmail", "use your google account",
)


def _looks_logged_out(text: str, title: str) -> bool:
    blob = (text + " " + title).lower()
    return any(h in blob for h in _LOGGED_OUT_HINTS)
