# M20 revision — Orb UI & Interaction Integration (FRIDAY V3)

> **Status:** complete (awaiting review). **Goal:** make a floating, always-on-top
> **Orb** FRIDAY's *primary* interface — a small living presence on the desktop that
> reflects her real cognition (listening / thinking / speaking / mood) and takes simple
> interactions — while the cinematic HUD/dashboard becomes a *secondary* surface opened
> on demand. Additive: the Orb UI contains **no AI logic**; it is driven entirely through
> the **Runtime Event Bus**. The existing HUD (`friday_app.py`) still works unchanged.

---

## 1. Overview & goals

The Orb replaces the always-open dashboard as the thing you see all day.

- **Primary interface.** The Orb is a frameless, semi-transparent, always-on-top,
  draggable native window (pywebview → Edge WebView2 on Windows — **not** a browser tab).
  Entry point: **`friday_orb_app.py`**.
- **Dashboard is secondary.** The cinematic HUD (`friday_app.py` / `core/io/friday_face.py`)
  is opened on demand (double-click, right-click menu, or a `ORB_DASHBOARD_OPEN` signal).
  **Closing the dashboard never shuts FRIDAY down** — the Orb keeps running.
- **Reflects real cognition.** The Orb shows *actual* state: it subscribes to FRIDAY's
  existing expression signals (`SPEAK_START`, `THINKING_START`, `WAKE_WORD`, `MOOD_UPDATED`, …)
  plus a few Orb-specific signals. It never guesses.
- **Speech is FRIDAY's, not the browser's.** Browser `speechSynthesis` is **removed**.
  Audio comes only from FRIDAY's Speech Service (`core/voice/friday_tts`); the Orb only
  *visualises* it — real audio amplitude drives the animation and a speech panel shows the
  spoken text.
- **Hard boundary.** The Orb UI never imports the Executive Brain, Memory, or any cognitive
  module. Its only channel to cognition — in both directions — is the Runtime Event Bus and
  the shared `core.infra.friday_signal.Signal` taxonomy.

---

## 2. UI architecture (`core/io/orb/`)

The Orb is a thin, reactive front-end plus a controller that translates signals into
JavaScript calls. All AI stays behind the bus.

| Module | Role |
|---|---|
| `events.py` | The Orb's **Signal vocabulary** on the Runtime Event Bus: outbound (FRIDAY → Orb), inbound (Orb → FRIDAY), the reflected expression signals (`EXPRESSION_TO_STATE`), and the `MOOD_TO_EMOTION` / `NOTIFY_REACTION` maps. Import is side-effect free. |
| `state.py` | The **data model**: the 9 `OrbState`s, `Emotion` overlays, `InteractionMode` (voice/text), state labels + accent colours, and `OrbSettings` + `SettingsStore` (persistence). Pure data + validation, no UI, no cognition. |
| `config.py` | Typed, tolerant reader for the `ui:` block of `friday_config.json` (`OrbConfig`). All keys optional; old configs without a `ui` block still work. |
| `controller.py` | **`OrbController`** — the bridge. Subscribes to inbound/reflected signals, pushes UI updates via `OrbView`, and emits interaction signals back onto the bus. Holds no AI logic. |
| `window.py` | **`OrbWindow`** + **`OrbView`** — the pywebview window (frameless, transparent, always-on-top, draggable) and the JS bridge (`evaluate_js` → `window.FRIDAY.*`; exposes the `pywebview.api` surface). |
| `speech_bridge.py` | **`SpeechBridge`** — connects FRIDAY's Speech Service to the Orb: turns spoken text + real audio amplitude into `ORB_SPEECH_SHOW` / `ORB_AMPLITUDE` / `ORB_SPEECH_HIDE`. |
| `ui/orb.html`, `ui/orb.css`, `ui/orb.js` | The reactive front-end: the WebGL orb renderer, per-state shader config, speech panel, right-click menu, and the `window.FRIDAY.*` API the controller calls. |
| `friday_orb_app.py` (root) | Entry point: builds config → controller → window and starts the runtime bridge. |

```
core/io/orb/
├── events.py         # Signal vocabulary (bus contract)
├── state.py          # OrbState / Emotion / InteractionMode / OrbSettings / SettingsStore
├── config.py         # OrbConfig  (the `ui:` block)
├── controller.py     # OrbController  (bus <-> UI bridge)
├── window.py         # OrbWindow + OrbView  (pywebview native window)
├── speech_bridge.py  # SpeechBridge  (Speech Service -> orb visualisation)
└── ui/
    ├── orb.html
    ├── orb.css
    └── orb.js        # renderer + window.FRIDAY.* + pywebview.api calls
```

---

## 3. Runtime event flow

Everything crosses the **Runtime Event Bus**. The controller is the only component that
touches both the bus and the WebView.

```
  Executive Brain / Speech Service
            │  emit(Signal.*)
            ▼
     Runtime Event Bus  ──────────────►  OrbController
            ▲                                  │  OrbView.evaluate_js(...)
            │  emit(inbound Signal.*)          ▼
            │                            window.FRIDAY.*   (orb.js renders)
     OrbController  ◄───── pywebview.api ─────  UI (click / menu / mode toggle)
```

### 3.1 Outbound — FRIDAY → Orb (controller subscribes; visualisation only)

| Signal | Data | Effect in the Orb |
|---|---|---|
| `ORB_STATE` | `str` state | Switch the orb to one of the 9 states. |
| `ORB_EMOTION` | `str` emotion | Apply an emotional overlay (`neutral/happy/curious/concerned/focused`). |
| `ORB_SPEECH_SHOW` | `str` text | Show the speech panel with the spoken text. |
| `ORB_SPEECH_HIDE` | — | Hide the speech panel; return the orb to idle. |
| `ORB_AMPLITUDE` | `float [0,1]` | Real audio amplitude → drives the speaking animation. |
| `ORB_NOTIFY` | `{"kind": message\|reminder\|warning\|error}` | Play a notification animation (glow/pulse — see §9). |
| `ORB_DASHBOARD_OPEN` | — | Open the secondary HUD/dashboard. |
| `ORB_DASHBOARD_CLOSE` | — | Close the dashboard (Orb keeps running). |
| `ORB_MODE` | `str` `voice\|text` | Reflect the active interaction mode in the UI. |

### 3.2 Reflected — existing expression signals the Orb mirrors

No new wiring is needed in the brain; the controller subscribes to signals FRIDAY already
emits and maps them to states (`events.EXPRESSION_TO_STATE`, `events.MOOD_TO_EMOTION`):

| Signal | Reflected as |
|---|---|
| `WAKE_WORD` | → `listening` |
| `USER_VOICE` | → `listening` |
| `THINKING_START` | → `thinking` |
| `THINKING_DONE` | → `idle` (unless speech follows immediately) |
| `SPEAK_START` | → `speaking` (+ show speech panel; data may carry the text) |
| `SPEAK_DONE` | → `idle` (+ hide speech panel) |
| `MOOD_UPDATED` | → `ORB_EMOTION` overlay via `MOOD_TO_EMOTION` |

### 3.3 Inbound — Orb → FRIDAY (controller emits from user interactions)

| Signal | Data | Raised by |
|---|---|---|
| `ORB_WAKE` | — | Single click (voice mode) — wake / start listening. |
| `ORB_DASHBOARD_TOGGLE` | — | Double click — toggle the dashboard. |
| `ORB_COMMAND` | `{"action": settings\|diagnostics\|plugins\|restart\|exit}` | Right-click quick menu. |
| `ORB_MODE_SET` | `str` `voice\|text` | Mode toggle (menu) or a voice command. |

### 3.4 Text flow (single turn)

```
click ─► pywebview.api.wake() ─► OrbController.emit(ORB_WAKE)
      ─► [Executive / Voice pipeline listens, thinks, speaks]
      ─► THINKING_START ─► ORB_STATE=thinking
      ─► SPEAK_START("Hi Satvik") ─► ORB_STATE=speaking + ORB_SPEECH_SHOW
      ─► ORB_AMPLITUDE(0.0..1.0) …            (audio drives the animation)
      ─► SPEAK_DONE ─► ORB_SPEECH_HIDE ─► ORB_STATE=idle
```

---

## 4. Orb Controller (`controller.py`)

`OrbController` is the single bridge between the bus and the WebView. Responsibilities:

- **Subscribe** to the inbound + reflected signals (`events.REFLECTED_SIGNALS` and the Orb
  signals) on the Runtime Event Bus.
- **Translate** each signal into a `window.FRIDAY.*` call via `OrbView.evaluate_js(...)`
  (state changes, emotion overlays, speech panel, amplitude frames, notifications).
- **Coerce** untrusted values so the UI never breaks: `state.coerce_state()` maps arbitrary
  state / voice-state strings onto a valid orb state; `state.coerce_amplitude()` clamps to
  `[0,1]`.
- **Emit interactions** back onto the bus when the UI calls `pywebview.api.*`
  (`ORB_WAKE`, `ORB_DASHBOARD_TOGGLE`, `ORB_COMMAND`, `ORB_MODE_SET`).
- **Own mode + settings**: applies `OrbConfig`, persists `OrbSettings` through
  `SettingsStore`, and reflects mode changes with `ORB_MODE`.

The controller holds **no AI logic** and imports **no** cognitive module — only the bus, the
Signal taxonomy, and the Orb's own data model.

---

## 5. Orb states

Nine canonical states (`state.OrbState`), each with a label and CSS accent
(`STATE_LABELS` / `STATE_ACCENT`); full shader parameters live in `ui/orb.js`.

| State | Meaning |
|---|---|
| `idle` | At rest, waiting. Gentle ambient motion. The resting state after speech/thinking. |
| `listening` | Actively hearing the user (after wake word / single click / `USER_VOICE`). |
| `thinking` | Reasoning / awaiting a response (`THINKING_START`). |
| `speaking` | FRIDAY is talking; amplitude-driven animation + speech panel (`SPEAK_START`). |
| `happy` | Positive acknowledgement / a "message" notification. |
| `warning` | A non-fatal warning (amber). |
| `error` | An error occurred (red). |
| `offline` | Cognition/services unavailable; the orb dims to a dormant look. |
| `sleeping` | Low-power / muted presence (e.g. voice disabled or user away). |

---

## 6. Speaking & the speech panel

Speech is produced only by FRIDAY's Speech Service (`core/voice/friday_tts`) and routed to
the Orb through `speech_bridge.py`. The Orb never synthesises audio — browser
`speechSynthesis` is removed.

1. Speech Service begins speaking → `SPEAK_START` (+ text) → controller emits
   `ORB_SPEECH_SHOW` and sets state `speaking`. The panel shows the spoken text.
2. While audio plays, `SpeechBridge` streams **real audio amplitude** as `ORB_AMPLITUDE`
   frames (`[0,1]`); `ui/orb.js` maps them onto the orb's pulse so the animation tracks the
   actual voice.
3. Speech finishes → `SPEAK_DONE` → controller emits `ORB_SPEECH_HIDE`; the panel
   **auto-hides** and the orb returns to `idle`.

The panel is governed by config: `speech_panel_enabled` (show it at all) and
`speech_panel_auto_hide` (hide automatically when speech finishes).

---

## 7. Voice Mode vs Text Mode

Two interaction modes (`state.InteractionMode`), persisted across restarts.

- **Voice Mode (default).** Voice recognition is active; a single click wakes FRIDAY and
  starts listening. This is the primary, hands-free experience.
- **Text Mode.** Voice recognition is disabled; you type in the dashboard chat instead. The
  orb still reflects state and speaks visualisation, but does not listen for a wake word.

**Switching modes**

- **From the UI:** the right-click menu / mode toggle → `ORB_MODE_SET` (`voice` | `text`).
- **By voice command** (handled upstream, reflected to the orb via `ORB_MODE` /
  `ORB_DASHBOARD_OPEN` / `ORB_DASHBOARD_CLOSE`):
  - "FRIDAY, switch to text mode" / "…switch to voice mode"
  - "FRIDAY, enable voice" / "…disable voice"
  - "FRIDAY, open dashboard" / "…close dashboard"

**Persistence.** The active mode is stored in `OrbSettings.mode` and restored on startup, so
FRIDAY comes back in whichever mode you left her.

---

## 8. Interactions

| Gesture | Result |
|---|---|
| **Single click** | Wake / start listening (voice mode) — emits `ORB_WAKE`. |
| **Double click** | Open the dashboard — emits `ORB_DASHBOARD_TOGGLE`. |
| **Right click** | Quick menu → `ORB_COMMAND`: **Settings**, **Diagnostics**, **Plugins**, **Restart FRIDAY**, **Exit**. |
| **Drag** | Move the orb (frameless window); new position persists. |

All interactions leave the UI through `window.pywebview.api.*`, reach `OrbController`, and
become inbound signals — the UI itself decides nothing about cognition.

---

## 9. Notifications

Notifications are **orb animations, not popups** (`events.NOTIFY_REACTION`). An `ORB_NOTIFY`
with a `kind` maps to a glow colour and a brief state:

| Kind | Reaction |
|---|---|
| `message` | Blue glow (`#4f80ff`), brief `happy`. |
| `reminder` | Purple pulse (`#a78bfa`), brief `thinking`. |
| `warning` | Amber pulse (`#fbbf24`), `warning` state. |
| `error` | Red pulse (`#f87171`), `error` state. |

---

## 10. Configuration (the `ui` block)

Read by `OrbConfig` from `friday_config.json` (non-secret settings). All keys are optional
and fall back to the defaults below, so a config without a `ui` block still works.

```json
"ui": {
  "primary_interface":     "orb",
  "voice_mode_default":    true,
  "speech_panel_enabled":  true,
  "speech_panel_auto_hide": true,
  "orb_always_on_top":     true,
  "remember_position":     true,
  "remember_size":         true,
  "animation_quality":     "high"
}
```

| Key | Type / values | Meaning |
|---|---|---|
| `primary_interface` | `orb` \| `dashboard` | Which surface FRIDAY opens first (defaults to `orb`). |
| `voice_mode_default` | bool | Start in Voice Mode when no persisted mode exists. |
| `speech_panel_enabled` | bool | Show the speech panel with spoken text. |
| `speech_panel_auto_hide` | bool | Auto-hide the panel when speech finishes. |
| `orb_always_on_top` | bool | Keep the orb above other windows. |
| `remember_position` | bool | Restore the last orb position on startup. |
| `remember_size` | bool | Restore the last orb size on startup. |
| `animation_quality` | `low` \| `medium` \| `high` | Renderer quality tier in `ui/orb.js`. |

Invalid values are sanitised back to safe defaults (`OrbConfig.sanitized()`).

---

## 11. Persistence (`OrbSettings`)

Window/mode state is persisted as JSON via `SettingsStore` and restored on startup, so the
orb reappears exactly where you left it. `SettingsStore` is best-effort — it never raises.

| Field | Default | Meaning |
|---|---|---|
| `x`, `y` | `None` | Last window position (screen coordinates). |
| `monitor` | `0` | Monitor index the orb lives on. |
| `width`, `height` | `340`, `340` | Last window size (min 120). |
| `opacity` | `1.0` | Window opacity (clamped `0.15–1.0`). |
| `mode` | `voice` | Persisted interaction mode (`voice` \| `text`). |
| `always_on_top` | `true` | Whether the orb stays on top. |

`remember_position` / `remember_size` in the `ui` config gate whether position/size are
restored.

---

## 12. Running it

```powershell
python friday_orb_app.py        # the Orb: frameless, always-on-top native window (primary)
python friday_app.py            # the cinematic HUD/dashboard (secondary; still works)
```

- Launch `friday_orb_app.py` for normal use — the orb appears where you last left it, in the
  last interaction mode.
- **Opening the dashboard:** double-click the orb, choose it from the right-click menu, or
  emit `ORB_DASHBOARD_OPEN`. The dashboard is the existing HUD (`core/io/friday_face.py` +
  `core/io/ui/`). **Closing it does not stop FRIDAY** — the orb (and cognition) keep
  running.

---

## 13. Developer guide

### Drive the orb from code — emit a Signal

The orb is driven **only** by the bus. From anywhere in the runtime, emit an Orb signal; the
controller reflects it into the UI. Do **not** call the UI directly and do **not** import the
Orb package from a cognitive module.

```python
from core.runtime import get_runtime
from core.infra.friday_signal import Signal

rt = get_runtime()

rt.emit(Signal.ORB_STATE, data="thinking")            # switch the orb to a state
rt.emit(Signal.ORB_EMOTION, data="curious")           # emotional overlay
rt.emit(Signal.ORB_SPEECH_SHOW, data="On it, Satvik") # show the speech panel
rt.emit(Signal.ORB_NOTIFY, data={"kind": "reminder"}) # purple reminder pulse
```

`emit()` is thread-safe (callable from any thread) and fire-and-forget.

### Add a new orb state

1. **`state.py`** — add the value to `OrbState`, plus entries in `STATE_LABELS` and
   `STATE_ACCENT`. (Update `VOICE_STATE_TO_ORB` if a voice-state string should map to it.)
2. **`ui/orb.js`** — add the state's shader/animation parameters to the per-state config
   (colours, vibration, pulse, spin) so the renderer knows how to draw it.
3. **Drive it** — emit `Signal.ORB_STATE` with the new value (or map an existing expression
   signal to it in `events.EXPRESSION_TO_STATE`). No controller changes are needed; unknown
   states are coerced to a safe default by `coerce_state()`.

### Add a new notification kind

Add an entry to `events.NOTIFY_REACTION` (`{"glow": "#…", "state": "…"}`) and a matching
animation in `ui/orb.js`; emit `Signal.ORB_NOTIFY` with the new `kind`.

### Invariants (do not break)

- The Orb UI contains **no AI logic** and imports **no** Executive Brain / Memory / cognitive
  module. Its only dependency toward FRIDAY is the bus + the `Signal` taxonomy.
- All FRIDAY → Orb communication is **visualisation only**; all Orb → FRIDAY communication is
  a small set of interaction signals.
- Speech is FRIDAY's (`core/voice/friday_tts`); the orb never synthesises audio.

---

## 14. Backward compatibility

- The cinematic HUD (`friday_app.py` / `core/io/friday_face.py` / `core/io/ui/`) is
  **unchanged** and still runs on its own; it is now the *secondary* surface reached from the
  orb.
- A `friday_config.json` **without** a `ui` block still loads — `OrbConfig` and `OrbSettings`
  supply defaults.
- The Orb reuses FRIDAY's **existing** expression signals, so no changes to the brain, voice,
  or coordinator were required to light it up. Everything here is additive.
