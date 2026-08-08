"""
build_audio.py — the reel's soundtrack: FRIDAY's own voice (edge-tts AriaNeural,
the same voice the app speaks with) over a gentle synthesized music bed, mixed
and placed on the shared timeline so each answer is spoken as it appears.

    from build_audio import build; build(total_seconds)   # -> tools/reel/audio.wav

Voice needs network (AriaNeural is neural/cloud). If it's unavailable the build
degrades to music-only. Music is synthesised with numpy — no licensing.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from timeline import SPEAK_AT, plan

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "audio.wav"
SR = 44100
VOICE = "en-US-AriaNeural"
TAGLINE_SAY = "Answers to no one but you."


# ── FRIDAY's voice ───────────────────────────────────────────────────────────────
def _tts(text: str, path: Path) -> bool:
    try:
        import edge_tts

        async def go():
            await edge_tts.Communicate(text, VOICE, rate="+6%").save(str(path))
        asyncio.run(go())
        return path.exists() and path.stat().st_size > 0
    except Exception:  # noqa: BLE001 — no network / no edge-tts → music only
        return False


def _decode(mp3: Path) -> np.ndarray:
    """Decode an mp3 to float32 stereo at SR via ffmpeg. Returns (n, 2)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp3), "-ar", str(SR),
         "-ac", "2", "-f", "f32le", "-"],
        capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    return a.reshape(-1, 2) if a.size else np.zeros((0, 2), np.float32)


def _place(mix: np.ndarray, clip: np.ndarray, at_s: float, gain: float = 0.95):
    if clip.size == 0:
        return
    off = int(at_s * SR)
    end = min(len(mix), off + len(clip))
    seg = clip[: end - off] * gain
    # 8 ms fades so nothing clicks
    f = min(len(seg) // 2, int(0.008 * SR))
    if f > 0:
        seg[:f] *= np.linspace(0, 1, f)[:, None]
        seg[-f:] *= np.linspace(1, 0, f)[:, None]
    mix[off:end] += seg


# ── the music bed (soft ambient pad + bell arpeggio) ─────────────────────────────
def _music(total_s: float) -> np.ndarray:
    n = int(total_s * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    prog = [(261.63, 329.63, 392.00), (196.00, 246.94, 293.66),
            (220.00, 261.63, 329.63), (174.61, 220.00, 261.63)]  # C G Am F
    chords = 8
    clen = total_s / chords
    for k in range(chords):
        s0, s1 = int(k * clen * SR), int((k + 1) * clen * SR)
        seg = np.arange(s1 - s0) / SR
        L = len(seg)
        env = np.ones(L)
        a = int(0.25 * SR)
        env[:a] = np.linspace(0, 1, a) if a < L else env[:a]
        env[-a:] = np.linspace(1, 0, a) if a < L else env[-a:]
        for f in prog[k % 4]:
            out[s0:s1] += (0.20 * np.sin(2 * np.pi * f * seg) * env).astype(np.float32)
            out[s0:s1] += (0.05 * np.sin(2 * np.pi * f * 2 * seg) * env).astype(np.float32)
    # gentle bell arpeggio on top
    beat, bi = 0.5, 0
    while beat * bi < total_s:
        start = beat * bi
        s0 = int(start * SR)
        note = prog[int(start / clen) % 4][bi % 3] * 2
        dur = 0.9
        seg = np.arange(int(dur * SR)) / SR
        decay = np.exp(-4.5 * seg)
        s1 = min(n, s0 + len(seg))
        out[s0:s1] += (0.07 * np.sin(2 * np.pi * note * seg[: s1 - s0])
                       * decay[: s1 - s0]).astype(np.float32)
        bi += 1
    out *= (0.85 + 0.15 * np.sin(2 * np.pi * 0.08 * t)).astype(np.float32)  # slow swell
    # a little space (two soft echoes)
    for delay, g in ((0.14, 0.25), (0.28, 0.14)):
        d = int(delay * SR)
        out[d:] += g * out[:-d]
    m = float(np.max(np.abs(out)) or 1.0)
    out = (out / m) * 0.5
    return np.stack([out, out * 0.97], axis=1)


# ── build the full soundtrack ────────────────────────────────────────────────────
def build(total_s: float) -> Path | None:
    data = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
    local = data.get("local", [])
    layout, _ = plan(len(local))
    by = {s["name"]: s for s in layout}

    mix = _music(total_s) * 0.30                 # music bed, well under the voice
    tmp = HERE / "_vox.mp3"

    def say(text: str, at_s: float):
        if text and _tts(text, tmp):
            _place(mix, _decode(tmp), at_s)

    for i, qa in enumerate(local):
        sc = by[f"local{i}"]
        say(qa.get("say", qa["answer"]), sc["start"] + SPEAK_AT * sc["dur"])
    if "cloud" in by:
        cloud = data.get("cloud", {})
        sc = by["cloud"]
        say(cloud.get("say", cloud.get("answer", "")),
            sc["start"] + SPEAK_AT * sc["dur"])
    if "tag" in by:
        say(TAGLINE_SAY, by["tag"]["start"] + 0.7)

    if tmp.exists():
        tmp.unlink()

    mix = np.clip(mix, -1.0, 1.0)
    pcm = (mix * 32767).astype(np.int16)
    with wave.open(str(OUT_WAV), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return OUT_WAV


if __name__ == "__main__":
    from timeline import plan as _p
    _, total = _p(3)
    print(build(total))
