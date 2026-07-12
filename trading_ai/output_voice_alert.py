"""
Output Module — Voice Alerts.

Takes a Recommendation (from recommend_recommendation_engine.py) and speaks
it out loud: action, confidence, and the reasons behind it. Also prints the
same thing to console so nothing is lost if speakers are muted/unavailable.

Strictly observe-and-announce, in line with the project's safety rules:
this module NEVER clicks anything, places anything, or touches the trading
platform. It only converts a Recommendation object into speech/text.

Uses pyttsx3 (offline, no API key, works without internet) so it keeps the
same "no external dependency beyond pip install" philosophy as the rest of
the project.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import pyttsx3
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "pyttsx3 is required for voice alerts. Install it with:\n"
        "    pip install pyttsx3\n"
        "On Windows this uses SAPI5 and needs no extra setup."
    ) from exc

from recommend_recommendation_engine import Recommendation


@dataclass
class VoiceSettings:
    rate: int = 175          # words per minute
    volume: float = 1.0      # 0.0 - 1.0
    voice_index: Optional[int] = None  # None = engine default voice
    min_seconds_between_repeats: float = 30.0  # don't re-announce the same call too often


class VoiceAlert:
    """
    Wraps pyttsx3 in a background thread so speaking never blocks the main
    observe/analyze loop in main.py. Recommendations are queued and spoken
    one at a time, in order.
    """

    def __init__(self, settings: Optional[VoiceSettings] = None):
        self.settings = settings or VoiceSettings()
        self._queue: "queue.Queue[Recommendation]" = queue.Queue()
        self._last_announced = {}  # symbol -> (action, timestamp)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- public API -----------------------------------------------------

    def announce(self, rec: Recommendation, force: bool = False) -> None:
        """
        Queue a recommendation to be spoken. By default, suppresses repeat
        announcements of the same action for the same symbol within
        min_seconds_between_repeats, so it doesn't nag every cycle while a
        signal stays unchanged.
        """
        key = rec.symbol
        now = time.time()
        last = self._last_announced.get(key)

        if not force and last is not None:
            last_action, last_time = last
            same_call = last_action == rec.action
            too_soon = (now - last_time) < self.settings.min_seconds_between_repeats
            if same_call and too_soon:
                return

        self._last_announced[key] = (rec.action, now)
        self._queue.put(rec)

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)  # unblock the worker thread
        self._thread.join(timeout=5)

    # ---- internals --------------------------------------------------------

    def _build_speech_text(self, rec: Recommendation) -> str:
        action_phrase = {
            "BUY": "Buy signal",
            "SELL": "Sell signal",
            "HOLD": "Hold",
            "WAIT": "Wait, no clear setup",
        }.get(rec.action, rec.action)

        parts = [f"{action_phrase} on {rec.symbol}.", f"Confidence {rec.confidence:.0f} percent."]

        plan = getattr(rec, "plan", None)
        if plan is not None and rec.action in ("BUY", "SELL"):
            parts.append(
                f"Entry {plan.entry:.2f}. Stop loss {plan.stop_loss:.2f}. Target {plan.target:.2f}."
            )
            if plan.est_win_rate is not None:
                parts.append(f"Historical win rate {plan.est_win_rate * 100:.0f} percent.")

        if rec.reasons:
            parts.append("Reasons:")
            for reason in rec.reasons:
                parts.append(reason)

        return " ".join(parts)

    def _run(self) -> None:
        engine = pyttsx3.init()
        engine.setProperty("rate", self.settings.rate)
        engine.setProperty("volume", self.settings.volume)

        if self.settings.voice_index is not None:
            voices = engine.getProperty("voices")
            if 0 <= self.settings.voice_index < len(voices):
                engine.setProperty("voice", voices[self.settings.voice_index].id)

        while not self._stop_event.is_set():
            rec = self._queue.get()
            if rec is None:
                break

            text = self._build_speech_text(rec)
            print(f"\n[VOICE ALERT] {text}\n")

            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:  # pragma: no cover - hardware/driver dependent
                print(f"[VOICE ALERT] (speech failed, text-only) {exc}")


# ---- quick manual test -----------------------------------------------------

if __name__ == "__main__":
    sample = Recommendation(
        symbol="AAPL",
        action="BUY",
        confidence=81.0,
        reasons=[
            "Uptrend confirmed (price > SMA20 > SMA50)",
            "Volume increasing vs recent average",
            "Similar trend_continuation setup won 14 of last 20 times",
        ],
    )

    alert = VoiceAlert()
    alert.announce(sample, force=True)
    time.sleep(6)  # give the background thread time to actually speak
    alert.stop()
