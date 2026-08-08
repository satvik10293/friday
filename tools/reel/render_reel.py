"""
render_reel.py — FRIDAY reel as the OS she is, not an app.

Full-screen on-device operating system: an OS status bar, the voice orb as the
system's presence (Listening -> Thinking -> Speaking), the heard command and her
answer rendered as OS-level responses, a mic waveform, and a bold close. No app
window, no title bar, no taskbar — this is the OS running on your laptop.

Answers are her REAL pipeline output (answers.json). Audio (her AriaNeural voice
+ a music bed) is built by build_audio.py and muxed in. Needs system ffmpeg.

    python tools/reel/render_reel.py            # -> tools/reel/friday_reel.mp4
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from timeline import FPS, SPEAK_AT, plan

HERE = Path(__file__).resolve().parent
OUT_MP4 = HERE / "friday_reel.mp4"
SILENT = HERE / "_reel_silent.mp4"

W, H = 1080, 1920

INK = (238, 243, 250)
DIM = (156, 168, 184)
FAINT = (96, 108, 124)
BLUE = (74, 138, 246)
GREEN = (46, 204, 128)
AMBER = (245, 176, 66)
CYAN = (60, 208, 226)
RED = (240, 96, 96)


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{n}", size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def bold(s): return _font(["segoeuib.ttf", "arialbd.ttf"], s)
def semi(s): return _font(["seguisb.ttf", "segoeui.ttf", "arial.ttf"], s)
def reg(s):  return _font(["segoeui.ttf", "arial.ttf"], s)
def mono(s): return _font(["consola.ttf", "cour.ttf"], s)


def ease(t): return t * t * (3 - 2 * t)
def clamp(t): return max(0.0, min(1.0, t))
def typed(text, prog): return text[:max(0, min(len(text), int(round(len(text) * prog))))]


def wrap(draw, text, font, max_w):
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            t = (line + " " + word).strip()
            if draw.textlength(t, font=font) <= max_w:
                line = t
            else:
                if line:
                    out.append(line)
                line = word
        out.append(line)
    return out


def center(d, cx, y, text, font, fill, gap=14):
    for ln in (text if isinstance(text, list) else [text]):
        d.text((cx - d.textlength(ln, font=font) / 2, y), ln, font=font, fill=fill)
        y += font.size + gap
    return y


def wallpaper():
    img = Image.new("RGB", (W, H))
    px = img.load()
    top, bot = (16, 20, 32), (5, 7, 12)
    for y in range(H):
        t = y / H
        row = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = row
    blob = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    for cx, cy, r, col in [(230, 360, 520, (40, 74, 156, 78)),
                           (880, 1520, 620, (28, 116, 128, 66)),
                           (600, 980, 420, (86, 52, 140, 48))]:
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    blob = blob.filter(ImageFilter.GaussianBlur(130))
    return Image.alpha_composite(img.convert("RGBA"), blob).convert("RGB")


def orb(frame, cx, cy, r, color, pulse):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(7, 0, -1):
        rr = int(r * (0.42 + 0.58 * i / 7) * (1 + 0.11 * pulse))
        a = int(48 * (i / 7) ** 2)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (a,))
    core = int(r * 0.5)
    d.ellipse([cx - core, cy - core, cx + core, cy + core], fill=color + (240,))
    hr = max(5, int(core * 0.26))
    hx, hy = cx - int(core * 0.34), cy - int(core * 0.40)
    d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255, 120))
    frame.paste(Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB"), (0, 0))


def waveform(d, cx, cy, w, n, level, color, seed):
    rnd = random.Random(seed)
    gap = w / n
    for i in range(n):
        x = cx - w / 2 + i * gap + gap / 2
        env = math.sin((i / n) * math.pi)
        h = 6 + env * 48 * level * (0.4 + rnd.random())
        d.rounded_rectangle([x - 4, cy - h, x + 4, cy + h], radius=4, fill=color)


def status_bar(f, gt, wifi_on, accent):
    """The OS status bar — this is the operating system, not an app window."""
    d = ImageDraw.Draw(f)
    d.ellipse([44, 40, 44 + 22, 40 + 22], fill=accent)
    d.text((78, 36), "FRIDAY", font=bold(30), fill=INK)
    d.text((78 + bold(30).getlength("FRIDAY") + 10, 40), "OS", font=bold(30), fill=accent)
    # right: wifi glyph + clock
    col = GREEN if not wifi_on else CYAN
    ax, ay = W - 210, 52
    for rr in (7, 14, 21):
        d.arc([ax - rr, ay - rr, ax + rr, ay + rr], 215, 325, fill=col, width=3)
    d.ellipse([ax - 3, ay - 3, ax + 3, ay + 3], fill=col)
    if not wifi_on:
        d.line([ax - 20, ay - 22, ax + 20, ay + 8], fill=RED, width=4)
    base = 9 * 3600 + 41 * 60 + int(gt)
    d.text((W - 150, 34), f"{(base//3600)%24}:{(base//60)%60:02d}",
           font=semi(30), fill=INK)


def lower_third(f, text, sub, color):
    d = ImageDraw.Draw(f)
    fnt = bold(50)
    y = 1660
    for ln in wrap(d, text, fnt, W - 160):
        d.text((W / 2 - d.textlength(ln, font=fnt) / 2, y), ln, font=fnt, fill=color)
        y += 60
    if sub:
        d.text((W / 2 - d.textlength(sub, font=reg(34)) / 2, y + 8), sub,
               font=reg(34), fill=DIM)


# ── scenes ───────────────────────────────────────────────────────────────────────
def scene_cold(stage, p, gt):
    f = stage.copy()
    orb(f, W // 2, 600, 138, BLUE, pulse=math.sin(p * math.pi * 2) * 0.5 + 0.5)
    d = ImageDraw.Draw(f)
    a = ease(clamp(p / 0.3))
    col = tuple(int(INK[i] * a + (5, 7, 12)[i] * (1 - a)) for i in range(3))
    center(d, W // 2, 980, "FRIDAY", bold(150), col)
    if p > 0.4:
        center(d, W // 2, 1200, "the AI operating system", semi(46), DIM)
        center(d, W // 2, 1270, "on your laptop — private by default", reg(36), FAINT)
    status_bar(f, gt, False, BLUE)
    return f


def scene_turn(stage, p, gt, beat):
    f = stage.copy()
    listen, think = 0.24, 0.40
    if p < listen:
        state, sc, lvl = "Listening", GREEN, ease(clamp(p / listen))
    elif p < think:
        state, sc, lvl = "Thinking", AMBER, 0.16
    else:
        state, sc, lvl = "Speaking", CYAN, 0.6 + 0.4 * math.sin(p * 42)
    orb(f, W // 2, 470, 120, sc, pulse=math.sin(p * math.pi * 6) * 0.5 + 0.5)
    d = ImageDraw.Draw(f)
    center(d, W // 2, 650, state + "…", semi(38), sc)

    # heard command (as the OS transcribes it)
    up = clamp(p / (listen * 0.9))
    heard = typed(beat["prompt"], up)
    if heard:
        center(d, W // 2, 740, f"“{heard}”", semi(44), INK)

    # her answer — large, centred, streaming — the OS answering
    if p >= think:
        ap = clamp((p - think) / 0.40)
        show = typed(beat["answer"], ap)
        if show:
            lines = wrap(d, show, bold(62), W - 200)
            y = center(d, W // 2, 900, lines, bold(62), INK, gap=12)
            # via chip
            rf = mono(30)
            rt = f"via: {beat['route']}"
            rw = d.textlength(rt, font=rf)
            cx = W / 2
            d.rounded_rectangle([cx - rw / 2 - 22, y + 24, cx + rw / 2 + 22, y + 80],
                                radius=28, fill=(sc[0] // 7, sc[1] // 7, sc[2] // 7),
                                outline=sc, width=2)
            d.text((cx - rw / 2, y + 32), rt, font=rf, fill=sc)

    waveform(d, W // 2, 1500, 420, 30, lvl, sc, seed=int(p * 120))
    status_bar(f, gt, beat["wifi"], sc)
    lower_third(f, beat.get("caption", ""), beat.get("sub", ""), sc)
    return f


def scene_tag(stage, p, gt):
    f = Image.blend(stage, Image.new("RGB", (W, H), (4, 5, 9)),
                    ease(clamp(p / 0.25)) * 0.85)
    orb(f, W // 2, 560, 126, CYAN, pulse=math.sin(p * math.pi * 2) * 0.5 + 0.5)
    d = ImageDraw.Draw(f)
    a = ease(clamp((p - 0.15) / 0.3))
    col = tuple(int(INK[i] * a + (4, 5, 9)[i] * (1 - a)) for i in range(3))
    center(d, W // 2, 900, ["Runs on your laptop.", "Answers to no one but you."],
           bold(90), col, gap=26)
    if p > 0.5:
        center(d, W // 2, 1200, "Local by default. Yours alone.", reg(38), DIM)
        center(d, W // 2, 1310, "@friday.os", bold(44), CYAN)
    return f


def build_timeline(stage, data):
    layout, total = plan(len(data["local"]))
    scenes = []
    for entry in layout:
        name, dur = entry["name"], int(entry["dur"] * FPS)
        if name == "cold":
            scenes.append((name, dur, lambda p, gt: scene_cold(stage, p, gt)))
        elif name == "tag":
            scenes.append((name, dur, lambda p, gt: scene_tag(stage, p, gt)))
        elif name == "cloud":
            c = dict(data["cloud"], wifi=True)
            scenes.append((name, dur,
                           lambda p, gt, c=c: scene_turn(stage, p, gt, c)))
        else:
            qa = dict(data["local"][int(name[5:])], wifi=False)
            scenes.append((name, dur,
                           lambda p, gt, qa=qa: scene_turn(stage, p, gt, qa)))
    return scenes, total


def fade(img, k, total):
    fin = fout = 7
    a = 1.0
    if k < fin:
        a = k / fin
    elif k > total - fout:
        a = max(0.0, (total - k) / fout)
    if a < 1.0:
        img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, a)
    return img


def main():
    data = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
    stage = wallpaper()
    scenes, total_s = build_timeline(stage, data)
    total = sum(dur for _, dur, _ in scenes)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg required")
        return None

    proc = subprocess.Popen(
        [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt",
         "yuv420p", "-crf", "18", "-preset", "medium", str(SILENT)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    done = 0
    for name, dur, fn in scenes:
        for k in range(dur):
            p = k / max(1, dur - 1)
            proc.stdin.write(fade(fn(p, done / FPS), k, dur).tobytes())
            done += 1
        print(f"  {name:8} ({done}/{total})", flush=True)
    proc.stdin.close()
    proc.wait()

    # soundtrack: her voice + music bed
    audio = None
    try:
        import build_audio
        audio = build_audio.build(total / FPS)
        print(f"  audio -> {audio}")
    except Exception as e:  # noqa: BLE001 — a silent reel still ships
        print(f"  audio build failed ({type(e).__name__}); shipping silent")

    if audio and Path(audio).exists():
        subprocess.run(
            [ffmpeg, "-y", "-i", str(SILENT), "-i", str(audio), "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT_MP4)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        SILENT.unlink(missing_ok=True)
    else:
        SILENT.replace(OUT_MP4)
    print(f"OK  {OUT_MP4}  ({total} frames, {total/FPS:.1f}s)")
    return str(OUT_MP4)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
