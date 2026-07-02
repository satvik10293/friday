"""
core/io/orb/controller.py -- FRIDAY V3 (M20 revision: Orb UI)

The Orb Controller. It is the ONLY bridge between FRIDAY's Runtime Event Bus and the Orb
window. It contains NO AI logic and imports NO cognitive module (no brain / executive /
memory / neural). It:

  * subscribes to the Runtime Event Bus and reflects FRIDAY's expression signals
    (SPEAK_START / SPEAK_DONE / THINKING_* / WAKE_WORD / MOOD_UPDATED) plus the orb-specific
    signals (amplitude, speech text, notifications, dashboard, mode) onto a reactive view,
  * receives user interactions from the window (single/double/right click, mode switch,
    move/resize) and emits them back onto the bus as inbound signals,
  * owns the interaction mode (voice/text) and persists window settings.

Every bus handler and every view call is guarded and never raises -- a UI or bus hiccup can
never take down FRIDAY.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from core.infra.friday_signal import Signal

from . import events as E
from .config import OrbConfig
from .state import (VALID_MODES, InteractionMode, OrbSettings, SettingsStore,
                    coerce_amplitude, coerce_state)

log = logging.getLogger("friday.orb.controller")

_DEFAULT_STORE = Path(__file__).resolve().parents[3] / "data" / "orb_state.json"


class OrbController:
    def __init__(self, bus=None, *, view=None, settings: Optional[OrbSettings] = None,
                 settings_store: Optional[SettingsStore] = None,
                 config: Optional[OrbConfig] = None) -> None:
        self._bus = bus if bus is not None else _default_runtime()
        self._view = view
        self._store = settings_store or SettingsStore(_DEFAULT_STORE)
        self._settings = (settings or self._store.load()).sanitized()
        self._config = config or OrbConfig.load()

        # honour the configured default mode on a fresh install (no persisted mode yet)
        if not self._config.voice_mode_default and self._settings.mode == InteractionMode.VOICE.value:
            self._settings.mode = InteractionMode.TEXT.value

        self._state = "idle"
        self._emotion = "neutral"
        self._mode = self._settings.mode
        self._dashboard_open = False
        self._amplitude = 0.0
        self._started = False
        self._registry = self._build_registry()
        self._subscribed: list = []          # (bus, signal, handler) for stop()

    # -- properties ----------------------------------------------------------------
    @property
    def state(self) -> str: return self._state

    @property
    def mode(self) -> str: return self._mode

    @property
    def emotion(self) -> str: return self._emotion

    @property
    def dashboard_open(self) -> bool: return self._dashboard_open

    @property
    def amplitude(self) -> float: return self._amplitude

    @property
    def settings(self) -> OrbSettings: return self._settings

    @property
    def config(self) -> OrbConfig: return self._config

    def snapshot(self) -> dict:
        """Bootstrap payload for the UI (see Api.ready)."""
        return {
            "state": self._state,
            "mode": self._mode,
            "emotion": self._emotion,
            "dashboard_open": self._dashboard_open,
            "always_on_top": bool(self._settings.always_on_top),
            "config": self._config.to_dict(),
        }

    # -- lifecycle -----------------------------------------------------------------
    def attach_view(self, view) -> None:
        self._view = view

    def start(self) -> "OrbController":
        """Subscribe all handlers to the primary bus. Idempotent."""
        if not self._started:
            self._subscribe(self._bus)
            self._started = True
        return self

    def add_source_bus(self, bus) -> None:
        """Also reflect FRIDAY's expression/orb signals from another bus (e.g. the live
        3.0 global bus where SPEAK_*/THINKING_*/WAKE_WORD are emitted)."""
        if bus is not None and bus is not self._bus:
            self._subscribe(bus)

    def stop(self) -> None:
        for bus, sig, handler in self._subscribed:
            try:
                bus.off(sig, handler)
            except Exception:  # noqa: BLE001
                pass
        self._subscribed.clear()
        self._started = False

    # -- subscription plumbing -----------------------------------------------------
    def _build_registry(self) -> list:
        reg = [(sig, self._on_expression) for sig in E.REFLECTED_SIGNALS]
        reg += [
            (E.ORB_AMPLITUDE, self._on_amplitude),
            (E.ORB_SPEECH_SHOW, self._on_speech_show),
            (E.ORB_SPEECH_HIDE, self._on_speech_hide),
            (E.ORB_NOTIFY, self._on_notify),
            (E.ORB_STATE, self._on_state),
            (E.ORB_EMOTION, self._on_emotion),
            (E.ORB_DASHBOARD_OPEN, self._on_dashboard_open),
            (E.ORB_DASHBOARD_CLOSE, self._on_dashboard_close),
            (E.ORB_MODE, self._on_mode),
        ]
        return reg

    def _subscribe(self, bus) -> None:
        if bus is None:
            return
        for sig, handler in self._registry:
            try:
                bus.on(sig, handler)
                self._subscribed.append((bus, sig, handler))
            except Exception:  # noqa: BLE001
                log.debug("[Orb] could not subscribe %s", getattr(sig, "name", sig))

    # -- inbound handlers (FRIDAY -> orb); all async (bus contract) -----------------
    async def _on_expression(self, event) -> None:
        sig = getattr(event, "signal", None)
        data = getattr(event, "data", None)
        if sig == Signal.MOOD_UPDATED:
            mood = data.get("mood") if isinstance(data, dict) else data
            self.set_emotion(E.MOOD_TO_EMOTION.get(str(mood or "").lower(), "neutral"))
            return
        if sig == Signal.SPEAK_START:
            if isinstance(data, str) and data:
                self._show_speech(data)
            self._set_state("speaking")
        elif sig == Signal.SPEAK_DONE:
            self._hide_speech()
            self._set_state("idle")
        elif sig == Signal.THINKING_DONE:
            if self._state != "speaking":
                self._set_state("idle")
        else:                                        # THINKING_START / WAKE_WORD / USER_VOICE
            st, _ = E.EXPRESSION_TO_STATE.get(sig, ("idle", False))
            self._set_state(st)

    async def _on_amplitude(self, event) -> None:
        self._set_amplitude(coerce_amplitude(getattr(event, "data", 0.0)))

    async def _on_speech_show(self, event) -> None:
        self._show_speech(str(getattr(event, "data", "") or ""))
        self._set_state("speaking")

    async def _on_speech_hide(self, event) -> None:
        self._hide_speech()
        self._set_state("idle")

    async def _on_notify(self, event) -> None:
        self._notify(getattr(event, "data", None))

    async def _on_state(self, event) -> None:
        self._set_state(coerce_state(str(getattr(event, "data", "idle"))))

    async def _on_emotion(self, event) -> None:
        self.set_emotion(str(getattr(event, "data", "neutral") or "neutral"))

    async def _on_dashboard_open(self, event) -> None:
        self._set_dashboard(True)

    async def _on_dashboard_close(self, event) -> None:
        self._set_dashboard(False)

    async def _on_mode(self, event) -> None:
        m = str(getattr(event, "data", "") or "").lower()
        if m in VALID_MODES and m != self._mode:
            self._apply_mode(m, emit=False)

    # -- outbound interactions (orb -> FRIDAY); sync, called by Api / voice / tests --
    def wake(self) -> None:
        if self._mode == InteractionMode.VOICE.value:
            self._set_state("listening")
        self._emit(E.ORB_WAKE)

    def toggle_dashboard(self) -> None:
        self._set_dashboard(not self._dashboard_open)
        self._emit(E.ORB_DASHBOARD_TOGGLE, {"open": self._dashboard_open})

    def command(self, action: str) -> None:
        action = str(action or "").lower()
        if action == "restart":
            self._hide_speech()
            self._set_state("idle")
            self._set_amplitude(0.0)
        self._emit(E.ORB_COMMAND, {"action": action})

    def set_mode(self, mode: str) -> bool:
        mode = str(mode or "").lower()
        if mode not in VALID_MODES:
            return False
        self._apply_mode(mode, emit=True)
        return True

    def on_move(self, x, y) -> None:
        try:
            self._settings.x, self._settings.y = int(x), int(y)
            if self._config.remember_position:
                self._store.save(self._settings)
        except (TypeError, ValueError):
            pass

    def on_resize(self, w, h) -> None:
        try:
            self._settings.width, self._settings.height = int(w), int(h)
            if self._config.remember_size:
                self._store.save(self._settings)
        except (TypeError, ValueError):
            pass

    def handle_voice_command(self, text: str) -> bool:
        """Parse the six supported spoken mode/dashboard commands. Returns whether one
        matched and was applied. NO general NLU here -- only the fixed control phrases."""
        low = str(text or "").lower()
        if "text mode" in low or "disable voice" in low:
            self.set_mode(InteractionMode.TEXT.value)
        elif "voice mode" in low or "enable voice" in low:
            self.set_mode(InteractionMode.VOICE.value)
        elif "open dashboard" in low:
            self._set_dashboard(True)
        elif "close dashboard" in low:
            self._set_dashboard(False)
        else:
            return False
        return True

    # -- internal state mutations (sync; drive the view) ----------------------------
    def _apply_mode(self, mode: str, *, emit: bool) -> None:
        self._mode = mode
        self._settings.mode = mode
        self._store.save(self._settings)
        self._view_call("set_mode", mode)
        if emit:
            self._emit(E.ORB_MODE, mode)

    def _set_state(self, state: str) -> None:
        state = coerce_state(state)
        self._state = state
        self._view_call("set_state", state)

    def set_emotion(self, emotion: str) -> None:
        self._emotion = str(emotion or "neutral")
        self._view_call("set_emotion", self._emotion)

    def _show_speech(self, text: str) -> None:
        if self._config.speech_panel_enabled:
            self._view_call("show_speech", text)

    def _hide_speech(self) -> None:
        self._view_call("hide_speech")

    def _set_amplitude(self, value: float) -> None:
        self._amplitude = value
        self._view_call("set_amplitude", value)

    def _set_dashboard(self, open_: bool) -> None:
        self._dashboard_open = bool(open_)
        self._view_call("open_dashboard" if open_ else "close_dashboard")

    def _notify(self, data) -> None:
        kind = (data.get("kind") if isinstance(data, dict) else str(data or "")).lower()
        reaction = E.NOTIFY_REACTION.get(kind, {"glow": "#4f80ff", "state": "happy"})
        self._view_call("notify", kind, reaction["glow"])
        self._view_call("set_state", reaction["state"])     # brief pulse; not the tracked state

    # -- helpers -----------------------------------------------------------------
    def _view_call(self, method: str, *args) -> None:
        view = self._view
        if view is None:
            return
        fn = getattr(view, method, None)
        if not callable(fn):
            return
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 -- the UI can never break the controller
            log.debug("[Orb] view.%s failed", method, exc_info=True)

    def _emit(self, signal, data=None) -> None:
        """Publish an inbound signal on the bus, tolerating either a sync Runtime bus, an
        async EventBus (via emit_sync), or a coroutine emit. Never blocks, never raises."""
        bus = self._bus
        if bus is None:
            return
        try:
            emit_sync = getattr(bus, "emit_sync", None)
            if callable(emit_sync):
                emit_sync(signal, data, "orb")
                return
            emit = getattr(bus, "emit", None)
            if emit is None:
                return
            if asyncio.iscoroutinefunction(emit):
                coro = emit(signal, data=data, source="orb")
                try:
                    asyncio.get_running_loop().create_task(coro)
                except RuntimeError:
                    coro.close()                      # no loop: drop cleanly (no warning)
            else:
                emit(signal, data=data, source="orb")
        except Exception:  # noqa: BLE001
            log.debug("[Orb] emit %s failed", getattr(signal, "name", signal), exc_info=True)


def _default_runtime():
    try:
        from core.runtime import get_runtime
        return get_runtime()
    except Exception:  # noqa: BLE001
        return None
