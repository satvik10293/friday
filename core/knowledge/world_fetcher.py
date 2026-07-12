"""
core/knowledge/world_fetcher.py — FRIDAY 3.0-era (M40)
The key to the M7 documentation bridge: a real external fetcher. Wikipedia's
public REST summary API — keyless, one HTTPS GET, returns an encyclopedic
extract with provenance (a real reference source, not LLM generation).

Rules (matching the teacher's, M30):
  · config-gated: `librarian.enabled` in friday_config.json (default true —
    there is no key or account; offline simply degrades to None)
  · never raises: any failure returns None and the caller falls back
  · privacy: only the distilled TOPIC of the question leaves the box, never
    the raw utterance or anything from memory

The fetcher is handed to KnowledgeService/DocumentationService, which apply
the M7 charter on top: local-first, last resort only, summarize before
storing, never store whole pages.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.knowledge.world")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "friday_config.json"

_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_TIMEOUT_S = 6.0
_HEADERS = {"User-Agent": "FRIDAY-assistant/3.0 (local personal assistant)"}

# question scaffolding: leading words dropped until the first content word
_LEAD_WORDS = {
    "what", "what's", "whats", "who", "who's", "whos", "where", "when", "why",
    "how", "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "far", "old", "many", "much", "big", "tall", "long", "away", "the", "a",
    "an", "tell", "me", "about", "you", "know", "please",
}
_TRAIL_WORDS = {"right", "now", "today", "currently", "exactly", "please"}


def _topicize(query: str) -> str:
    """Reduce a spoken question to a lookup topic: "how far away is the moon?"
    → "moon". Deliberately simple — Wikipedia's search resolves the rest."""
    words = re.findall(r"[A-Za-z0-9'&.-]+", (query or ""))
    i = 0
    while i < len(words) and words[i].lower() in _LEAD_WORDS:
        i += 1
    core = words[i:] or words
    while core and core[-1].lower() in _TRAIL_WORDS:
        core = core[:-1]
    return " ".join(core).strip()


def _librarian_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg.get("librarian") or {}
    except (OSError, ValueError):
        return {}


def _resolve_title(topic: str) -> Optional[str]:
    import requests
    resp = requests.get(
        _SEARCH_URL,
        params={"action": "opensearch", "search": topic, "limit": 1,
                "namespace": 0, "format": "json"},
        headers=_HEADERS, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    titles = resp.json()[1]
    return titles[0] if titles else None


def wikipedia_fetcher(query: str) -> Optional[str]:
    """Query → Wikipedia summary extract, or None. Never raises."""
    try:
        topic = _topicize(query)
        if len(topic) < 2:
            return None
        title = _resolve_title(topic)
        if not title:
            return None
        import requests
        resp = requests.get(
            _SUMMARY_URL.format(title=title.replace(" ", "_")),
            headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        extract = (data.get("extract") or "").strip()
        if not extract or data.get("type") == "disambiguation":
            return None
        log.info("[Librarian] fetched %r for topic %r", data.get("title"), topic)
        return extract
    except Exception:  # noqa: BLE001 — the librarian must never break a turn
        log.debug("wikipedia fetch failed for %r", query, exc_info=True)
        return None


def make_world_fetcher():
    """The default fetcher for get_knowledge_service(): wikipedia when the
    librarian is enabled, else None (the M7 bridge stays fully offline)."""
    if _librarian_config().get("enabled", True):
        return wikipedia_fetcher
    return None


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "how far away is the moon"
    print(f"topic: {_topicize(q)!r}")
    print(wikipedia_fetcher(q) or "(no result)")
