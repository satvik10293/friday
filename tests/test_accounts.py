"""
FRIDAY's account access (core/web/accounts + the conversation route).

Pins the read/navigate side: spoken names resolve to the right site, a signed-out
page is detected (so she never pretends to have read a locked inbox), and the
route matches account phrases while leaving apps ("open spotify"), web search,
and "close ..." alone. No browser is launched by these tests.
"""

from __future__ import annotations

from core.web.accounts import ACCOUNTS, _looks_logged_out, resolve


# ── resolve ─────────────────────────────────────────────────────────────────────────
def test_resolve_aliases():
    assert resolve("gmail")[0] == "Gmail"
    assert resolve("my email")[0] == "Gmail"
    assert resolve("inbox")[0] == "Gmail"
    assert resolve("insta")[0] == "Instagram"
    assert resolve("whatsapp")[0] == "WhatsApp"
    assert resolve("calendar")[0] == "Google Calendar"


def test_resolve_unknown_is_none():
    assert resolve("spotify") is None
    assert resolve("") is None
    assert resolve("chrome") is None


def test_every_account_maps_to_https():
    for label, url in ACCOUNTS.values():
        assert url.startswith("https://") and label


# ── signed-out detection ─────────────────────────────────────────────────────────────
def test_logged_out_detection():
    assert _looks_logged_out("Sign in to continue to Gmail", "Gmail")
    assert _looks_logged_out("", "WhatsApp Web — Log in")
    assert not _looks_logged_out("Inbox (3)  Promotions  Primary", "Inbox - user@x")


# ── the conversation route regex (no instance / no browser needed) ───────────────────
def _route(phrase):
    from core.launcher.conversation import ConversationBridge
    m = ConversationBridge._ACCOUNT_RE.search(phrase)
    if not m:
        return None
    hit = resolve(m.group(2))
    read = bool(ConversationBridge._ACCOUNT_READ_RE.search(phrase))
    return (hit[0] if hit else None, read)


def test_route_matches_account_phrases():
    assert _route("open my gmail") == ("Gmail", False)
    assert _route("check my email") == ("Gmail", True)
    assert _route("any new whatsapp") == ("WhatsApp", True)
    assert _route("what's on my calendar") == ("Google Calendar", True)
    assert _route("open instagram") == ("Instagram", False)


def test_route_leaves_apps_and_search_and_close_alone():
    assert _route("open spotify") is None          # an app → app.open
    assert _route("open chrome") is None
    assert _route("search google for cats") is None  # → web search
    assert _route("close whatsapp") is None          # → close_app
