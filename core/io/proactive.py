"""
core/io/proactive.py — FRIDAY V3 (M49)
Proactive presence. Background cognition already thinks between turns —
concerns ("memory pressure high"), reminders ("unfinished goal…"), and new
self-proposed goals awaiting approval. Until now those thoughts just sat in
the internal stream; nothing reached the owner. This surfaces the SALIENT
ones as desktop (tray) notifications so FRIDAY nudges instead of only
reacting — carefully, so she never nags:

  · watermark on thought id — a thought is considered once, ever
  · salience order: new goal proposal > concern > reminder; below a
    confidence floor nothing surfaces
  · cooldown between notifications + a per-hour cap
  · de-dupe on the message text

Notifications-only: this raises awareness, it never acts. Config-gated
(`proactive` block; enabled by default) and fully guarded — a failure here
never disturbs cognition.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable, Optional

log = logging.getLogger("friday.io.proactive")

# which thought kinds are worth interrupting the owner for, most urgent first
_SALIENCE = {"concern": 3, "planning": 2, "reminder": 1}


class ProactiveNotifier:
    def __init__(self, *, thoughts=None, goals=None,
                 notify: Optional[Callable[[str, str], bool]] = None,
                 speak: Optional[Callable[[str], None]] = None,
                 min_confidence: float = 0.6, cooldown_s: float = 300.0,
                 max_per_hour: int = 6, speak_aloud: bool = False) -> None:
        self._thoughts = thoughts
        self._goals = goals
        self._notify = notify
        self._speak = speak
        self.min_confidence = min_confidence
        self.cooldown_s = cooldown_s
        self.max_per_hour = max_per_hour
        self.speak_aloud = speak_aloud
        self._seen_thought_id = 0
        self._seen_proposals: set = set()
        self._recent_msgs: deque = deque(maxlen=12)   # (text, ts) for de-dupe
        self._fired: deque = deque(maxlen=64)          # ts of each notification
        self._last_ts = 0.0
        self.notified = 0

    # ── the one bounded pass (call after each background tick) ────────────────────
    def check(self, *, now: Optional[float] = None) -> Optional[str]:
        """Surface at most ONE salient item. Returns the message shown, or None.
        Never raises."""
        now = now if now is not None else time.time()
        try:
            candidate = self._pick()
            if candidate is None:
                return None
            title, message, kind, ref = candidate
            if not self._allowed(message, now):
                return None
            # commit the watermark only on ACTUAL emission — a candidate blocked
            # by cooldown/cap must be re-surfaced later, not silently dropped
            if kind == "proposal":
                self._seen_proposals.add(ref)
            else:
                self._seen_thought_id = max(self._seen_thought_id, int(ref))
            self._emit(title, message, now)
            return message
        except Exception:  # noqa: BLE001 — proactivity must never disturb cognition
            log.debug("proactive check failed", exc_info=True)
            return None

    # ── choose the single most salient NEW item (does not mutate state) ───────────
    def _pick(self) -> Optional[tuple]:
        """Return (title, message, kind, ref) for the top candidate, or None.
        Pure inspection — the watermark advances only when check() emits."""
        # 1. a brand-new goal proposal awaiting approval is the highest signal
        if self._goals is not None:
            try:
                for goal in self._goals.list_proposals():
                    gid = getattr(goal, "goal_id", None) or getattr(goal, "title", "")
                    if gid and gid not in self._seen_proposals:
                        title = getattr(goal, "title", "a goal")
                        return ("FRIDAY has a suggestion",
                                f"I'd like to work on: {title}. Say 'approve "
                                "proposal' to let me.", "proposal", gid)
            except Exception:  # noqa: BLE001
                log.debug("proposal scan failed", exc_info=True)

        # 2. else the most salient new, confident thought
        if self._thoughts is not None:
            try:
                best = None
                best_rank = (-1, 0.0)
                for t in self._thoughts.recent(limit=30):
                    if t.id <= self._seen_thought_id or t.confidence < self.min_confidence:
                        continue
                    if _SALIENCE.get(t.kind, 0) <= 0:
                        continue
                    rank = (_SALIENCE[t.kind], t.confidence)
                    if rank > best_rank:
                        best, best_rank = t, rank
                if best is not None:
                    return ("FRIDAY", best.text, best.kind, best.id)
            except Exception:  # noqa: BLE001
                log.debug("thought scan failed", exc_info=True)
        return None

    # ── rate limiting + de-dupe ───────────────────────────────────────────────────
    def _allowed(self, message: str, now: float) -> bool:
        if now - self._last_ts < self.cooldown_s:
            return False
        # per-hour cap
        hour_ago = now - 3600.0
        while self._fired and self._fired[0] < hour_ago:
            self._fired.popleft()
        if len(self._fired) >= self.max_per_hour:
            return False
        # de-dupe recent identical messages
        norm = message.strip().lower()
        if any(m == norm for m, _ in self._recent_msgs):
            return False
        return True

    def _emit(self, title: str, message: str, now: float) -> None:
        if self._notify is not None:
            try:
                self._notify(title, message)
            except Exception:  # noqa: BLE001
                log.debug("notify failed", exc_info=True)
        if self.speak_aloud and self._speak is not None:
            try:
                self._speak(message)
            except Exception:  # noqa: BLE001
                log.debug("proactive speak failed", exc_info=True)
        self._last_ts = now
        self._fired.append(now)
        self._recent_msgs.append((message.strip().lower(), now))
        self.notified += 1

    def status(self) -> dict:
        return {"notified": self.notified, "cooldown_s": self.cooldown_s,
                "max_per_hour": self.max_per_hour, "speak_aloud": self.speak_aloud}
