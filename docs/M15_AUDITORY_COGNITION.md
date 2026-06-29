# M15 — Auditory Cognition (FRIDAY V3)

> **Status:** complete. **Goal:** transform FRIDAY from a speech assistant into an AI
> that understands the *entire auditory environment*. M15 extends perception beyond
> speech and integrates with the existing Runtime, Memory, World Model, Attention, and
> Executive — **without redesigning M12.1**. The M12.1 listening pipeline is unmodified;
> M15 is purely additive (`core/audio/cognition/`).

---

## 1. Where M15 sits

```
Microphone frames ─► Audio Event Engine ─► Context Reasoner ─► Observation(AUDIO)
                       (features→detectors)        │                  │
                                                   ▼                  ▼
                                            Auditory Memory     Perception ─► Entity Resolver ─► World Model
                                                   │
                       Audio Attention ◄───────────┘  (emergency > wake > speech > environmental > background)

Speech path:  Transcript ─► De-duplication ─► Wake Control (confidence · cooldown · self-speech · resume)
```

The speech side builds on M12.1 (continuous listening, VAD, transcription, wake engine);
the environmental side is new. Both feed the same World Model / Memory / Attention.

---

## 2. Modules (`core/audio/cognition/`)

| Module | Role |
|---|---|
| `config.py` | `AudioCognitionConfig` (wake/speech/events/memory/attention). Accepts the flat `audio:` YAML block *or* nested sections. No hardcoded tunables. |
| `features.py` | Model-free acoustic features (numpy rFFT + time domain): energy, ZCR, spectral centroid/bandwidth/flatness/rolloff, band ratios, harmonicity, pitch, onsets, modulation rate. |
| `detector_base.py` | `AudioEventDetector` (never-raises), `ProfileDetector` (feature-template matching, always available), `MLEventDetector` (learned-classifier hook). |
| `profiles.py` | The 13 built-in sound profiles **as data** + `register_profile()` for new sounds at runtime. |
| `engine.py` | `AudioEventEngine` — rolling-window detection, confidence gate, per-type cooldown, emits `AuditoryEvent`. |
| `events.py` | Open `SoundCatalog` + `SoundType` + `SoundCategory`; `AuditoryEvent`; runtime event keys. |
| `context.py` | `AudioContextReasoner` — sound → contextual `AUDIO` Observation + reasoning, routed via Perception (no World-Model bypass). |
| `memory.py` | `AuditoryMemory` (SQLite) — meaningful events only, with optional Chronicle forwarding. |
| `attention.py` | `AudioAttention` — priority bands, dynamic boost/decay, M5 bridge. |
| `wake.py` | `WakeWordController` — confidence threshold, cooldown, self-speech suppression, resume. |
| `dedup.py` | `SpeechDeduplicator` — rejects identical/near-identical transcripts within a window. |
| `service.py` | `AuditoryCognition` facade composing everything + runtime/world/chronicle/executive/emotion wiring. |
| `benchmark.py` / `architecture.json` | Benchmarks + machine-readable manifest. |

---

## 3. Objectives → implementation

1. **Advanced speech recognition** — continuous listening (M12.1) + `SpeechDeduplicator`
   prevents duplicate recognition; partial sentences handled (min-char gate); graceful
   recovery (never-raises throughout); fast (dedup/wake are O(window)).
2. **Wake-word engine** — `WakeWordController`: ignores FRIDAY's own TTS
   (`speaking_started/finished` + guard), prevents repeat triggers (`cooldown_s`),
   resumes after speaking, confidence-based (`wake_confidence`).
3. **Environmental audio understanding** — `AudioEventEngine` + 13 detectors
   (door knock, doorbell, alarm, timer, phone ringing, keyboard, mouse, laughter,
   crying, glass breaking, running water, dog barking, cat meowing). **New sounds =
   register a `SoundType` + `FeatureProfile`** — no core change.
4. **Audio context reasoning** — `AudioContextReasoner` maps each sound to a
   plain-language interpretation (doorbell → "Someone may be at the door"; keyboard →
   "User is likely working"; running water → "kitchen/bathroom") as an `AUDIO`
   Observation fed into the World Model through Perception.
5. **Auditory memory** — `AuditoryMemory` stores meaningful events (timestamp, type,
   confidence, source, session id); routine sound is dropped by the significance gate.
6. **Audio attention** — `AudioAttention` enforces emergency > wake > speech >
   environmental > background, dynamically nudged by recent activity; bridges to M5.
7. **Runtime integration** — `AuditoryCognition` wires Runtime (events + health), World
   Model, Chronicle, Executive (emergency notifications), and Emotion (human vocal
   sounds). No duplicate processing, no circular dependencies (one-way: audio →
   cognition).
8. **Configuration** — the milestone's YAML maps 1:1 onto `AudioCognitionConfig`.
9. **Logging** — structured `[Audio]` logs (`Wake word detected`, `Doorbell detected
   (92%)`, `Speech recognized`, …).
10. **Testing** — see §6.

---

## 4. Configuration

```yaml
audio:
  wake_word: friday
  continuous_listening: true
  wake_confidence: 0.85
  noise_filter: true
  audio_event_detection: true
  store_audio_events: true
```

```python
from core.audio.cognition import AudioCognitionConfig, AuditoryCognition
cfg = AudioCognitionConfig.from_dict({"wake_word": "friday", "wake_confidence": 0.85})
ac = AuditoryCognition(cfg, runtime=runtime, perception=perception,
                       world_model=world_model, attention_system=attention,
                       chronicle=chronicle, executive=executive, emotion=emotion)
```

Full per-section control is available too (`events.window_s`, `events.min_confidence`,
`events.emergency_sounds`, `memory.significance_threshold`, `attention.*`, …). See the
manifest for the complete surface.

---

## 5. Integration explanation

- **World Model** — environmental sounds become `Observation(type=AUDIO)` and are routed
  through the injected `PerceptionManager.ingest` (preferred — entity resolution, no
  bypass) or a `WorldFeed` over the World Model. Vision and audio reach the World Model
  through the same sanctioned path.
- **Memory / Chronicle** — `AuditoryMemory` persists meaningful events; significant ones
  are forwarded to a duck-typed Chronicle sink.
- **Attention** — `AudioAttention` ranks signals and projects them into M5's
  `rank_observations`, so audio competes alongside goals, memories, and vision.
- **Executive** — emergencies (glass breaking, alarm, crying) notify the Executive Brain
  via a duck-typed hook and raise an `audio.emergency` runtime event.
- **Emotion** — human vocal sounds (laughter/crying) nudge the Emotion system (optional).
- **M12.1 Listening** — `bind_listening(service)` subscribes to the existing bus's
  `TRANSCRIPT_READY` so recognized speech flows through de-dup + wake control. The M12.1
  pipeline is **not** modified.

All collaborators are injected and optional; with none wired, FRIDAY still detects sounds
and reasons locally. Every external call is guarded — an audio failure can never crash
the Cognitive Core.

---

## 6. Test results

`tests/test_audio_cognition.py`, `test_audio_wake_control.py`,
`test_audio_memory_attention.py`, `test_audio_cognition_integration.py` cover:
wake-word detection, background-noise rejection (silence → no event), continuous/windowed
listening, audio-event detection + extensibility, runtime integration, memory storage
(meaningful-only), duplicate prevention, self-speech suppression, the exact attention
priority order, and the no-bypass World-Model path. Benchmark
(`python -m core.audio.cognition.benchmark`): feature extraction ≈4.7 ms/window,
≈230 detections/s, ≈3500 frame fps, dedup precision 1.0.

---

## 7. Remaining limitations

- **Model-free detectors are heuristic.** Profile/feature-template detectors separate the
  classes by acoustic signature and are deliberately broad; among overlapping tonal
  alerts (doorbell vs timer vs phone) the exact label can be fuzzy (the *category* is
  robust). The `MLEventDetector` hook is the upgrade path — drop in an AudioSet/YAMNet
  classifier without touching the engine.
- **No sound-source localization** — `source` is a passthrough field; direction-of-arrival
  needs multi-mic input (future).
- **Speaker identity for non-speech vocal sounds** (whose laughter/crying) is out of scope.
- **Wake-word spotting is text-based** (post-transcription); a true on-audio KWS model
  plugs into the M12.1 `detect_audio` seam.

---

## 8. Suggestions for M16 preparation

- **Sensor fusion (audio + vision):** correlate `audio.sound.detected` (doorbell) with
  `vision.object.appeared` (person at door) in the World Model for higher-confidence
  events — a natural M16 "Multimodal Perception / Sensor Fusion" milestone.
- **Learned audio models:** wire a YAMNet/AudioSet classifier through `MLEventDetector`
  and add an on-audio KWS model; benchmark against the heuristic baseline.
- **Sound-source localization** with a mic array; populate `AuditoryEvent.source` and the
  Scene Graph's spatial model.
- **Temporal/event reasoning:** sequences (alarm → silence → motion) as episodic memories
  feeding prediction/simulation.

See **architecture.json** for the machine-readable manifest.
