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
import re
import time
from typing import Optional
from urllib.parse import quote

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


# ── acting: draft, then SEND only on the owner's explicit confirm ────────────────────
# Composing pre-fills a real draft in her browser (visible to you) and NEVER
# sends; sending is a separate call the conversation layer makes only after you
# say "send it". Deep links (Gmail cm / WhatsApp send) are used over brittle DOM
# clicking so the draft lands reliably.

def _contacts() -> dict:
    """name(lower) -> {"email":.., "phone":..} from friday_config.json (optional).
    Voice can't spell an address or reel off a number, so the owner maps the
    people FRIDAY may contact once, by name. Best-effort; empty if unset."""
    import json
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parents[2]
        cfg = json.loads((root / "friday_config.json").read_text(encoding="utf-8"))
        return {str(k).lower(): v for k, v in (cfg.get("contacts") or {}).items()
                if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def resolve_contact(name: str, kind: str) -> Optional[str]:
    """Resolve a spoken recipient to an email address or phone number (kind =
    "email" | "phone"). Looks up the contacts map first, then accepts a value the
    owner spoke literally (an address with '@', or a 7+ digit number). None means
    'I don't know who that is' — the caller must refuse rather than guess."""
    q = (name or "").strip().strip(".?!")
    if not q:
        return None
    contact = _contacts().get(q.lower())
    if contact and contact.get(kind):
        return str(contact[kind])
    if kind == "email" and "@" in q and "." in q.split("@")[-1]:
        return q.replace(" ", "")
    if kind == "phone":
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 7:
            return digits
    return None


def compose_email(to: str, subject: str, body: str) -> dict:
    """Open a Gmail compose window PRE-FILLED with to/subject/body. Does NOT send."""
    url = ("https://mail.google.com/mail/?view=cm&fs=1"
           f"&to={quote(to or '')}&su={quote(subject or '')}&body={quote(body or '')}")
    from core.web.browser import get_browser
    r = get_browser().open(url)
    r["account"] = "Gmail"
    return r


def compose_whatsapp(phone: str, text: str) -> dict:
    """Open a WhatsApp Web chat with `phone`, message PRE-FILLED. Does NOT send."""
    url = f"https://web.whatsapp.com/send?phone={quote(phone or '')}&text={quote(text or '')}"
    from core.web.browser import get_browser
    r = get_browser().open(url)
    r["account"] = "WhatsApp"
    return r


def send_open_draft(account: str) -> dict:
    """Send the draft currently open in her browser — Gmail with Ctrl+Enter,
    WhatsApp with Enter. Called ONLY after the owner confirmed 'send it'."""
    from core.web.browser import get_browser
    key = "Control+Enter" if account == "Gmail" else "Enter"
    return get_browser().press(key)
