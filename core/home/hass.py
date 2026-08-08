"""
core/home/hass.py — FRIDAY's bridge to the home.

One local integration that reaches everything. FRIDAY talks to a Home Assistant
instance over its REST API with a long-lived access token; Home Assistant talks
to the actual devices (TVs, fans, lights, plugs, IR blasters) and to the phone
(its companion app). This keeps FRIDAY vendor-neutral: add a device in Home
Assistant and she can drive it, with no new code here.

Config lives in friday_config.json under "home_assistant"; the token is read
from the environment first (never commit it):

    "home_assistant": {"url": "http://homeassistant.local:8123", "token": ""}
    # .env:  HASS_TOKEN=<a long-lived access token from your HA profile>

Everything is best-effort and HONEST: if HA isn't configured or reachable, the
client reports not-ready (and records a degradation) instead of raising. Nothing
here ever throws out of a turn.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

log = logging.getLogger("friday.home.hass")

_DEFAULT_TIMEOUT = 8.0
_MATCH_FLOOR = 0.5          # below this, a spoken name isn't a confident device


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def _match(want: str, cand: str) -> float:
    """Token-overlap score in [0,1] between a spoken name and a device name."""
    w, c = set(want.split()), set(cand.split())
    if not w or not c:
        return 0.0
    if want == cand:
        return 1.0
    inter = len(w & c)
    if not inter:
        return 0.0
    # reward covering the spoken words; a full subset ("fan" in "living room fan")
    # scores high without over-rewarding long device names
    return inter / len(w) * (0.6 + 0.4 * inter / len(c))


class HomeAssistant:
    """A thin, honest Home Assistant REST client. Build via from_config()."""

    def __init__(self, url: str = "", token: str = "", *,
                 timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.url = (url or "").rstrip("/")
        self._token = token or ""
        self.timeout = timeout
        self._ready: Optional[bool] = None

    @classmethod
    def from_config(cls, config: Optional[dict] = None) -> "HomeAssistant":
        cfg = ((config or {}).get("home_assistant") or {}) if config else {}
        url = cfg.get("url") or os.environ.get("HASS_URL", "")
        token = (cfg.get("token") or os.environ.get("HASS_TOKEN")
                 or os.environ.get("HOME_ASSISTANT_TOKEN", ""))
        return cls(url, token)

    # ── connectivity ─────────────────────────────────────────────────────────
    def available(self) -> bool:
        """Configured at all? (URL + token present.)"""
        return bool(self.url and self._token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    def ready(self, *, refresh: bool = False) -> bool:
        """True if HA answers the auth-checked ping. Cached; never raises."""
        if not self.available():
            return False
        if self._ready is not None and not refresh:
            return self._ready
        try:
            import requests
            r = requests.get(self.url + "/api/", headers=self._headers(),
                             timeout=self.timeout)
            self._ready = r.status_code == 200
        except Exception:  # noqa: BLE001 — unreachable HA is a state, not an error
            log.debug("home assistant not reachable", exc_info=True)
            self._ready = False
        if not self._ready:
            self._note_degraded("home assistant unreachable or unauthorized")
        return self._ready

    def _note_degraded(self, detail: str) -> None:
        try:
            from core.observability import note_degraded
            note_degraded("home.assistant", detail)
        except Exception:  # noqa: BLE001
            pass

    # ── raw API ──────────────────────────────────────────────────────────────
    def states(self) -> list:
        """All entity states (each has entity_id, state, attributes). [] on any
        failure."""
        if not self.available():
            return []
        try:
            import requests
            r = requests.get(self.url + "/api/states", headers=self._headers(),
                             timeout=self.timeout)
            if r.status_code == 200:
                return list(r.json())
        except Exception:  # noqa: BLE001
            log.debug("home assistant states() failed", exc_info=True)
        return []

    def call_service(self, domain: str, service: str,
                     entity_id: Optional[str] = None,
                     data: Optional[dict] = None) -> bool:
        """POST /api/services/<domain>/<service>. Returns success; never raises."""
        if not self.available():
            return False
        payload = dict(data or {})
        if entity_id:
            payload["entity_id"] = entity_id
        try:
            import requests
            r = requests.post(f"{self.url}/api/services/{domain}/{service}",
                              headers=self._headers(), json=payload,
                              timeout=self.timeout)
            return r.status_code in (200, 201)
        except Exception:  # noqa: BLE001
            log.debug("home assistant call_service failed", exc_info=True)
            return False

    # ── friendly-name resolution ─────────────────────────────────────────────
    def find_entity(self, name: str) -> Optional[str]:
        """Resolve a spoken device name to an entity_id by matching against
        friendly_name and the entity_id itself. None if no confident match."""
        want = _norm(name)
        if not want:
            return None
        best, best_score = None, 0.0
        for st in self.states():
            eid = st.get("entity_id", "")
            attrs = st.get("attributes") or {}
            for cand in (attrs.get("friendly_name", ""),
                         eid.split(".", 1)[-1].replace("_", " ")):
                score = _match(want, _norm(cand))
                if score > best_score:
                    best, best_score = eid, score
        return best if best_score >= _MATCH_FLOOR else None

    def controllable(self) -> list:
        """Friendly names of the devices FRIDAY can switch (lights, switches,
        fans, media players, climate) — for a 'what can you control' answer."""
        out = []
        for st in self.states():
            eid = st.get("entity_id", "")
            domain = eid.split(".", 1)[0]
            if domain in ("light", "switch", "fan", "media_player", "climate",
                          "cover", "input_boolean"):
                name = (st.get("attributes") or {}).get("friendly_name") or eid
                out.append(name)
        return sorted(set(out))

    # ── high-level actions ───────────────────────────────────────────────────
    def turn_on(self, entity_id: str) -> bool:
        return self.call_service("homeassistant", "turn_on", entity_id)

    def turn_off(self, entity_id: str) -> bool:
        return self.call_service("homeassistant", "turn_off", entity_id)

    def toggle(self, entity_id: str) -> bool:
        return self.call_service("homeassistant", "toggle", entity_id)

    def set_by_name(self, name: str, *, on: bool) -> tuple[bool, Optional[str]]:
        """Resolve a spoken name and switch it on/off. Returns (ok, entity_id);
        entity_id is None when the name didn't resolve to a device."""
        eid = self.find_entity(name)
        if not eid:
            return (False, None)
        return ((self.turn_on(eid) if on else self.turn_off(eid)), eid)

    def notify_phone(self, message: str, *, target: str = "notify") -> bool:
        """Send a notification to the phone via HA's notify service (the
        companion app registers as notify.mobile_app_<device>)."""
        return self.call_service("notify", target, data={"message": message})
