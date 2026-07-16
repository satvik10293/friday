"""
M49 — proactive presence: she nudges, carefully.

Background cognition already produces concerns, reminders and self-proposed
goals; the ProactiveNotifier surfaces the SALIENT ones as tray notifications
without ever nagging: watermark (each item once), salience order (proposal >
concern > reminder), confidence floor, cooldown, per-hour cap, de-dupe.
Notifications-only — it never acts.
"""

from __future__ import annotations

from core.cognition.thoughts import ThoughtStream
from core.io.proactive import ProactiveNotifier


class _Sink:
    def __init__(self):
        self.sent = []

    def notify(self, title, message):
        self.sent.append((title, message))
        return True


def _notifier(sink, thoughts=None, goals=None, **kw):
    kw.setdefault("min_confidence", 0.6)
    kw.setdefault("cooldown_s", 0.0)
    return ProactiveNotifier(thoughts=thoughts, goals=goals,
                             notify=sink.notify, **kw)


def test_low_salience_thoughts_are_not_surfaced():
    ts, sink = ThoughtStream(), _Sink()
    ts.think("observation", "the cursor moved", confidence=0.9)
    ts.think("hypothesis", "maybe it's raining", confidence=0.9)
    n = _notifier(sink, thoughts=ts)
    assert n.check() is None
    assert sink.sent == []


def test_a_concern_is_surfaced_once():
    ts, sink = ThoughtStream(), _Sink()
    ts.think("concern", "Memory pressure at 90%.", confidence=0.8)
    n = _notifier(sink, thoughts=ts)
    assert n.check() == "Memory pressure at 90%."
    assert len(sink.sent) == 1
    assert n.check() is None                        # watermark: not again
    assert len(sink.sent) == 1


def test_low_confidence_thought_is_ignored():
    ts, sink = ThoughtStream(), _Sink()
    ts.think("concern", "faint worry", confidence=0.3)
    assert _notifier(sink, thoughts=ts).check() is None


def test_salience_prefers_concern_over_reminder():
    ts, sink = ThoughtStream(), _Sink()
    ts.think("reminder", "unfinished goal X", confidence=0.9)
    ts.think("concern", "disk almost full", confidence=0.9)
    n = _notifier(sink, thoughts=ts)
    assert n.check() == "disk almost full"          # concern wins


class _Goal:
    def __init__(self, gid, title):
        self.goal_id, self.title = gid, title


class _Goals:
    def __init__(self, proposals):
        self._p = proposals

    def list_proposals(self):
        return self._p


def test_new_goal_proposal_outranks_thoughts():
    ts, sink = ThoughtStream(), _Sink()
    ts.think("concern", "some concern", confidence=0.9)
    goals = _Goals([_Goal("g1", "organize my notes")])
    n = _notifier(sink, thoughts=ts, goals=goals)
    msg = n.check()
    assert "organize my notes" in msg and "approve" in msg.lower()   # proposal first
    assert n.check() == "some concern"              # then the pending concern
    assert n.check() is None                        # both seen once


def test_cooldown_blocks_a_second_notification():
    ts, sink = ThoughtStream(), _Sink()
    n = _notifier(sink, thoughts=ts, cooldown_s=300.0)
    ts.think("concern", "first", confidence=0.9)
    assert n.check(now=1000.0) is not None
    ts.think("concern", "second", confidence=0.9)
    assert n.check(now=1100.0) is None              # new thought, but within cooldown
    assert n.check(now=1400.0) is not None          # cooldown elapsed → surfaced


def test_per_hour_cap():
    ts, sink = ThoughtStream(), _Sink()
    n = _notifier(sink, thoughts=ts, cooldown_s=0.0, max_per_hour=2)
    t = 1000.0
    for i in range(5):
        ts.think("concern", f"concern {i}", confidence=0.9)
        n.check(now=t)
        t += 1.0
    assert len(sink.sent) == 2                       # capped at 2/hour


def test_dedupe_identical_messages():
    ts, sink = ThoughtStream(), _Sink()
    n = _notifier(sink, thoughts=ts, cooldown_s=0.0)
    ts.think("concern", "same text", confidence=0.9)
    n.check(now=1000.0)
    ts.think("concern", "same text", confidence=0.9)
    n.check(now=1100.0)
    assert len(sink.sent) == 1                       # duplicate suppressed


def test_check_never_raises_on_broken_sources():
    class _Boom:
        def recent(self, limit=30):
            raise RuntimeError("boom")
    n = ProactiveNotifier(thoughts=_Boom(), notify=lambda t, m: True)
    assert n.check() is None                         # swallowed, no crash


def test_speak_aloud_only_when_enabled():
    ts, sink = ThoughtStream(), _Sink()
    spoken = []
    ts.think("concern", "say me", confidence=0.9)
    n = ProactiveNotifier(thoughts=ts, notify=sink.notify,
                          speak=spoken.append, speak_aloud=True,
                          min_confidence=0.6, cooldown_s=0.0)
    n.check()
    assert spoken == ["say me"] and len(sink.sent) == 1
