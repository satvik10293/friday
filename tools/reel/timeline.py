"""Shared reel timeline — imported by render_reel.py (video) and build_audio.py
(voice + music) so the two stay frame-aligned."""

FPS = 30
SPEAK_AT = 0.40          # fraction into a turn scene where FRIDAY starts speaking
DUR = {"cold": 2.6, "local": 3.1, "cloud": 4.4, "tag": 3.6}


def plan(n_local: int):
    """Return ([{name, start, dur}], total_seconds) for the whole reel."""
    seq = [("cold", DUR["cold"])]
    seq += [(f"local{i}", DUR["local"]) for i in range(n_local)]
    seq += [("cloud", DUR["cloud"]), ("tag", DUR["tag"])]
    out, t = [], 0.0
    for name, d in seq:
        out.append({"name": name, "start": t, "dur": d})
        t += d
    return out, t
