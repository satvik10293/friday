# FRIDAY — Orb UI Integration Report (M20 revision)

> Milestone: **Orb UI & Interaction Integration**. The floating Orb becomes FRIDAY's primary
> interface; the cinematic HUD/dashboard becomes secondary. Additive — no cognitive
> architecture changed, no public API broken.

## 1. What was built

| Layer | File(s) | Role |
|---|---|---|
| Event vocabulary | `core/io/orb/events.py` | Orb signals on the shared `Signal` taxonomy + reflected-signal / notify maps |
| Data model | `core/io/orb/state.py` | 9 orb states, `Emotion`, `InteractionMode` (voice/text), `OrbSettings` + `SettingsStore` persistence |
| Config | `core/io/orb/config.py` | Typed `ui:` config block (tolerant, backward compatible) |
| Controller | `core/io/orb/controller.py` | `OrbController` — subscribes to the Runtime Event Bus, drives the view, handles interactions; **no AI logic, imports no cognitive module** |
| Native window | `core/io/orb/window.py` | `OrbWindow` (frameless/transparent/on-top pywebview + threaded static server), `OrbView` (controller → `window.FRIDAY.*`), `Api` (JS → controller) |
| Speech bridge | `core/io/orb/speech_bridge.py` | `SpeechBridge` — FRIDAY's TTS → real RMS amplitude envelope + speech panel signals |
| Front-end | `core/io/orb/ui/orb.{html,css,js}` | Self-contained reactive orb (ported 4D visual, 9 states, speech panel); **no browser TTS/demo** |
| Entry point | `friday_orb_app.py` | Native launcher: runtime + controller + window; bridges the live `friday_signal` bus |
| Config block | `friday_config.json` → `ui` | primary_interface, voice_mode_default, speech panel, always-on-top, remember position/size, animation quality |
| Docs | `docs/M20_ORB_UI.md` | Full architecture / event-flow / user + developer guide |

## 2. Directive compliance

| Requirement | Status | Notes |
|---|---|---|
| Floating orb = primary interface | ✅ | `friday_orb_app.py`; dashboard opens on demand |
| Frameless / transparent / on-top / draggable / cross-platform / single codebase | ✅ | pywebview native window; drag via `api.move`; per-OS handled by pywebview |
| Orb contains **no AI logic**; controlled only via Runtime Event Bus | ✅ | Controller imports no brain/executive/memory (test-enforced); UI is pure visualiser |
| Dedicated Orb Controller (events → animation/speech/amplitude/dashboard/interactions) | ✅ | `OrbController` |
| 9 states (idle/listening/thinking/speaking/happy/warning/error/offline/sleeping) | ✅ | `state.py` + `ui/orb.js STATE_CONFIG`; smooth transitions |
| Speaking: real amplitude animation + speech panel + auto-hide → idle | ✅ | `SpeechBridge` RMS envelope → `ORB_AMPLITUDE`; panel auto-hides |
| Remove browser speech synthesis / demo phrases / random audio | ✅ | Zero `speechSynthesis`/`PHRASES`/`Math.random` audio in the UI (verified) |
| Speech only from FRIDAY's Speech Service; orb only visualises | ✅ | `speech_bridge` wraps `core/voice/friday_tts` |
| Voice mode default; Text mode; persist across restarts | ✅ | `OrbSettings.mode`, persisted via `SettingsStore` |
| Mode switching via UI + 6 voice commands | ✅ | `handle_voice_command` (parses all 6) + right-click / mode toggle |
| Interactions: single=wake, double=dashboard, right=menu (Settings/Diagnostics/Plugins/Restart/Exit) | ✅ | UI → `api.wake/toggle_dashboard/command` |
| Dashboard secondary; closing it never shuts FRIDAY down | ✅ | Independent overlay in the UI |
| Persist X/Y/monitor/size/opacity; restore on startup | ✅ | `OrbSettings` + `on_move/on_resize` |
| Notifications as orb animations (blue/purple/amber/red) | ✅ | `NOTIFY_REACTION` → `FRIDAY.notify(kind, glow)` |
| Configurable `ui:` block | ✅ | `config.py` + `friday_config.json` |
| Tests + docs | ✅ | `tests/test_orb.py` (25) + `docs/M20_ORB_UI.md` |

## 3. Contract verification (UI ↔ Python)

- **Controller → UI:** `OrbView._call("setState"|"setEmotion"|"showSpeech"|"hideSpeech"|"setAmplitude"|"setMode"|"notify"|"openDashboard"|"closeDashboard"|"bootstrap", …)` emits `window.FRIDAY.<method>(json)`. The UI defines all 10 methods — **exact match**.
- **UI → Controller:** the UI calls `window.pywebview.api.{wake, toggle_dashboard, command, move, ready}` — all present on the `Api` class (plus `set_mode`, `resize`) — **match**.
- **Signals:** `ORB_*` added additively to the `Signal` enum; controller reflects existing `SPEAK_START/SPEAK_DONE/THINKING_START/THINKING_DONE/WAKE_WORD/MOOD_UPDATED` so it shows real cognition with no new brain wiring.

## 4. Test results

- `tests/test_orb.py`: **25 passed** (headless: reflected signals, interactions, mode persistence, all 6 voice commands, notify→glow, amplitude sync, snapshot, no-cognition-import invariant, window/bridge import guards).
- `orb.js`: `node --check` clean.
- Full suite (M1–M20 + orb): **1226 passed** (exit 0) — the additive `Signal` enum change and `ui:` config caused no regression.

## 5. Deviations (all minor, behaviour-preserving)

1. `OrbView` binds to an `OrbWindow` holder exposing `.evaluate(js)` (the pywebview window doesn't exist until `webview.start()`); the JS path is identical and no-ops safely before the window is live.
2. `SpeechBridge.emit_speech` has a `block` kwarg (default background thread) for deterministic tests.
3. `notify` also flashes the reaction state briefly without changing the tracked state.
4. A fresh install with `voice_mode_default:false` starts in text mode; a persisted mode always wins.

## 6. Backward compatibility

- The cinematic HUD (`friday_app.py` / `core/io/friday_face.py`) is unchanged and still runs as the secondary dashboard.
- `friday_orb.py` (the original stdlib launcher orb) is untouched.
- The `Signal` enum change is purely additive (appended members; existing values unchanged).

## 7. Live verification

The native window is best confirmed by launching `python friday_orb_app.py` (opens the frameless
orb; single-click wakes, double-click opens the dashboard, right-click shows the menu). Headless CI
verifies everything except the on-screen render.
