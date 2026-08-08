"""
core/launcher/wakeup.py — FRIDAY's honest wake-up.

When she comes up, she says so — and says it *truthfully*. The spoken line is
derived from the boot's own verdict and the degradation ledger, not a script:
if vision didn't start, she says vision is degraded and why; if everything came
up, she says so. This turns the first few seconds of a session from "slow,
silent software" into "a mind coming awake that knows its own state".

    line = wakeup_line(stages, ledger_report, owner="Satvik")
    #  healthy → "Good evening, Satvik. All systems nominal — I'm ready."
    #  degraded→ "Good evening, Satvik. I'm up, but hearing is offline
    #             (faster-whisper not installed). Everything else is nominal."

`wakeup_line` is pure (inject `now` for tests). `announce` speaks it via
FRIDAY's voice, guarded — it never raises and never blocks the boot.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("friday.launcher.wakeup")

# how a ledger subsystem key reads out loud (longest prefix wins)
_FRIENDLY = (
    ("audio.stt", "hearing"),
    ("voice.playback", "voice"),
    ("voice.tts", "voice"),
    ("voice", "voice"),
    ("vision.live", "vision"),
    ("boot.perception", "vision"),
    ("boot.voice", "voice"),
    ("boot.wake_word", "wake word"),
    ("boot.memory", "memory"),
    ("boot.knowledge", "knowledge"),
    ("boot.intelligence", "reasoning"),
    ("boot.skills", "skills"),
    ("boot.mind", "the internal mind"),
    ("boot.simulation", "simulation"),
    ("boot.ui", "the app surface"),
)


def _friendly(subsystem: str) -> str:
    for prefix, name in _FRIENDLY:
        if subsystem == prefix or subsystem.startswith(prefix + "."):
            return name
    # boot.<stage> with no explicit mapping → the bare stage name
    if subsystem.startswith("boot."):
        return subsystem[len("boot."):].replace("_", " ")
    return subsystem.replace("_", " ")


def _greeting(now: datetime) -> str:
    h = now.hour
    if h < 12:
        return "Good morning"
    if h < 18:
        return "Good afternoon"
    return "Good evening"


def wakeup_line(stages: Optional[list], degradation: Optional[dict], *,
                owner: str = "", now: Optional[datetime] = None,
                max_named: int = 3) -> str:
    """A truthful one-line wake-up. `stages` is the boot report's stage list
    (used only to note how many came up); `degradation` is the ledger's
    `report()`. Health and specifics come from the ledger."""
    now = now or datetime.now()
    dg = degradation or {}
    subsystems = dg.get("subsystems", {}) or {}

    who = f", {owner}" if owner else ""
    greet = f"{_greeting(now)}{who}."

    # collect the faculties that are failed or degraded (skipped-only stays
    # nominal — those are intentional opt-outs, not breakage)
    impaired: list[tuple[str, str]] = []       # (friendly name, reason)
    seen: set[str] = set()
    for key, s in subsystems.items():
        sev = s.get("last_severity")
        if sev not in ("failed", "degraded"):
            continue
        name = _friendly(key)
        if name in seen:
            continue
        seen.add(name)
        impaired.append((name, str(s.get("last_detail") or "")))

    if not impaired:
        return f"{greet} All systems nominal — I'm ready."

    # name the first few, with the shortest useful reason for the first one
    names = [n for n, _ in impaired]
    shown = names[:max_named]
    extra = len(names) - len(shown)
    if len(shown) == 1:
        subject = shown[0]
        verb = "is"
    elif len(shown) == 2:
        subject = f"{shown[0]} and {shown[1]}"   # no comma for a pair
        verb = "are"
    else:
        subject = ", ".join(shown[:-1]) + f", and {shown[-1]}"  # Oxford comma
        verb = "are"
    tail = f" and {extra} more" if extra > 0 else ""

    # a short parenthetical reason from the first impaired faculty, if it reads cleanly
    reason = impaired[0][1]
    reason = reason.split(" — ")[0].split(" (")[0].strip()
    because = f" ({reason})" if reason and len(reason) < 60 else ""

    return (f"{greet} I'm up, but {subject}{tail} {verb} degraded{because}. "
            f"I'm ready, running degraded.")


def announce(launcher, *, config: Optional[dict] = None,
             now: Optional[datetime] = None) -> str:
    """Speak the wake-up line through FRIDAY's voice (guarded). Returns the line
    whether or not it was spoken. Respects `ui.wake_narration` (default on);
    never raises, never blocks the boot."""
    cfg = config or getattr(launcher, "config", {}) or {}
    report = getattr(launcher, "report", None) or {}
    stages = ((report.get("startup") or {}).get("stages")) or []
    owner = str(cfg.get("owner_name") or "")

    try:
        from core.observability import get_degradation_ledger
        degradation = get_degradation_ledger().report()
    except Exception:  # noqa: BLE001
        degradation = {}

    line = wakeup_line(stages, degradation, owner=owner, now=now)

    ui = cfg.get("ui") or {}
    if ui.get("wake_narration", True) is False:
        return line
    try:
        from core.voice.friday_voice import FridayVoice
        FridayVoice().say(line)
    except Exception:  # noqa: BLE001 — narration is never load-bearing
        log.debug("wake narration not spoken", exc_info=True)
    return line
