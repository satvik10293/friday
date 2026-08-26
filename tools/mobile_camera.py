"""
tools/mobile_camera.py — connect your phone's camera to FRIDAY (M64)

One command turns your phone into a FRIDAY camera over your home Wi-Fi:

    python tools/mobile_camera.py

It starts the vision transport (Flask + SocketIO) bound to the LAN, prints the
URL to open on your phone, and streams frames into FRIDAY's Camera Manager. On
the phone: open the printed URL in the browser, tap "START LIVE FEED", allow the
camera. Frames flow Transport → Camera Manager → decoded Frames, and the health
endpoint (…/api/vision/health) reports the live stream.

Nothing is exposed beyond your local network unless you pass --ngrok. Localhost
is the default binding; --lan is required to bind the routable interface (this
is the same explicit opt-in the server enforces).
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from collections import Counter
from pathlib import Path

# allow running as a bare script (python tools/mobile_camera.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.vision.transport.service import VisionTransport  # noqa: E402


def local_ip() -> str:
    """Best-effort LAN address of this machine (the one the phone must reach).
    Uses a throwaway UDP socket so it works without actually sending anything."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no packets sent; just picks the iface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Connect your phone camera to FRIDAY.")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--lan", action="store_true",
                    help="bind the LAN interface so your phone can reach it (default: on)")
    ap.add_argument("--localhost", action="store_true",
                    help="bind 127.0.0.1 only (no phone access; for local testing)")
    ap.add_argument("--ngrok", action="store_true",
                    help="also open an ngrok tunnel for off-network access")
    ap.add_argument("--http", action="store_true",
                    help="serve plain http (phone camera will NOT work; local testing only)")
    ap.add_argument("--see", action="store_true",
                    help="give her EYES: run the vision pipeline (scene/motion/faces), "
                         "describe what the camera sees, and record it into the world model")
    ap.add_argument("--tunnel", action="store_true",
                    help="serve plain http on localhost for a trusted tunnel "
                         "(cloudflared) — the reliable path for iPhone/Safari")
    args = ap.parse_args(argv)

    lan = not args.localhost            # LAN by default; --localhost to restrict
    ip = local_ip() if lan else "127.0.0.1"
    host = "0.0.0.0" if lan else "127.0.0.1"
    # Phones only allow camera access over HTTPS (or localhost), so LAN serving
    # uses a self-signed cert by default. --http opts out (localhost testing).
    https = lan and not args.http
    scheme = "https" if https else "http"
    cors = None
    # --tunnel: a trusted HTTPS tunnel (cloudflared) fronts a plain-http localhost
    # server. iPhone gets a real cert (no warning, camera allowed); the socket must
    # accept the tunnel's origin, so CORS opens to any (only localhost is exposed).
    if args.tunnel:
        lan, host, ip = False, "127.0.0.1", "127.0.0.1"
        https, scheme, cors = False, "http", "*"

    # --see gives her real EYES: the full vision pipeline (built over the SAME
    # transport the server ingests into), so frames become perceptions and land
    # in the world model. Without it, this is transport-only (frames flow, health
    # confirms, but nothing is "understood").
    vision = None
    if args.see:
        from core.vision.config import VisionConfig, ProcessingConfig
        from core.vision.service import VisionSystem
        cfg = VisionConfig()
        # If a YOLO model is present she NAMES objects (person, cup, laptop, ...);
        # otherwise she falls back to what runs with no download: scene, motion,
        # and faces (OpenCV Haar).
        yolo = Path(__file__).resolve().parents[1] / "data" / "vision" / "yolov8n.pt"
        if yolo.exists():
            cfg.processing = ProcessingConfig(
                enabled=["scene_stats", "objects", "face", "face_recognition",
                         "tracking"],
                object_backend="ultralytics", object_model_path=str(yolo),
                object_confidence=0.35)
            print("  [vision] object detection: YOLO + face memory")
        else:
            cfg.processing = ProcessingConfig(
                enabled=["scene_stats", "motion", "face", "face_recognition",
                         "tracking"])
            print("  [vision] object detection: off (scene / motion / faces only)")
        vision = VisionSystem(config=cfg)
        transport = vision.transport
        server = vision.server(host=host, port=args.port,
                               allow_lan=lan, use_ngrok=args.ngrok, use_https=https,
                               cors_origins=cors)
    else:
        transport = VisionTransport()
        server = transport.server(host=host, port=args.port,
                                  allow_lan=lan, use_ngrok=args.ngrok, use_https=https,
                               cors_origins=cors)

    url = f"{scheme}://{ip}:{args.port}"
    print("\n" + "=" * 60)
    print("  FRIDAY — mobile camera (give her eyes)")
    print("=" * 60)
    if args.tunnel:
        print("  TUNNEL MODE: serving locally at " + url)
        print("  Now run this in another terminal to get a trusted public URL:")
        print(f"\n      cloudflared tunnel --url {url}\n")
        print("  Open the https://<random>.trycloudflare.com URL it prints on your")
        print("  phone — a REAL cert, so no warning and the camera is allowed.")
    else:
        print("  On your phone (same Wi-Fi), open this in the browser:")
        print(f"\n      {url}\n")
        if https:
            print("  NOTE: it's a self-signed certificate, so the phone will warn")
            print("  'Your connection is not private' the first time — tap Advanced")
            print("  then 'Proceed'. (Required so the browser lets her use the camera.)")
    print("  Then tap START LIVE FEED and allow the camera.")
    print(f"  Live health: {url}/api/vision/health")
    if vision is not None:
        print("  EYES ON: I'll describe what the camera sees below, and remember")
        print("  it in my world model (scene / motion / faces).")
    print("  Press Ctrl+C to stop.")
    print("=" * 60 + "\n")

    stop = threading.Event()
    eyes = None
    if vision is not None:
        eyes = threading.Thread(target=_eyes_loop, args=(vision, stop),
                                daemon=True, name="friday-eyes")
        eyes.start()

    tunnel_proc = None
    if args.tunnel:
        tunnel_proc = _start_tunnel(args.port)

    try:
        server.run()                    # blocking; serves the page + ingests frames
    except KeyboardInterrupt:
        print("\n[mobile_camera] stopped.")
    finally:
        stop.set()
        if tunnel_proc is not None:
            try:
                tunnel_proc.terminate()
            except Exception:           # noqa: BLE001
                pass
        if vision is not None:
            try:
                vision.stop()
            except Exception:           # noqa: BLE001
                pass
        else:
            transport.stop()
    return 0


def _cloudflared_path():
    """Locate the cloudflared binary (PATH or the winget install location)."""
    import shutil
    p = shutil.which("cloudflared")
    if p:
        return p
    for c in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
              r"C:\Program Files\cloudflared\cloudflared.exe"):
        if Path(c).exists():
            return c
    return None


def _start_tunnel(port: int):
    """Auto-start a Cloudflare quick tunnel so the phone gets a trusted public
    URL (no cert warning — the reliable path for iPhone). Writes the URL to
    data/vision/tunnel_url.txt (the Control Center reads it) and prints it."""
    import re
    import subprocess
    exe = _cloudflared_path()
    if not exe:
        print("  [tunnel] cloudflared not found — install: "
              "winget install Cloudflare.cloudflared")
        return None
    url_file = Path(__file__).resolve().parents[1] / "data" / "vision" / "tunnel_url.txt"
    url_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        url_file.unlink()
    except OSError:
        pass
    proc = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)

    def _reader():
        for line in proc.stdout:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m:
                url = m.group(0)
                try:
                    url_file.write_text(url, encoding="utf-8")
                except OSError:
                    pass
                print(f"\n  [tunnel] PUBLIC URL: {url}")
                print(f"  Open  {url}/live  on any device (trusted cert, camera OK).\n")
                break

    threading.Thread(target=_reader, daemon=True).start()
    return proc


def _eyes_loop(vision, stop) -> None:
    """Drive the vision pipeline over the live phone stream: draw detection boxes
    for the live dashboard, narrate what she sees, and mirror detections into the
    world model. Never crashes the server."""
    import cv2
    import numpy as np
    from core.world.world_model import WorldModel
    from core.vision.transport.live_view import get_live_view
    from core.vision.memory.object_catalog import get_object_catalog
    from core.vision.memory.face_memory import get_face_gallery, simple_embedding
    world = WorldModel()
    live = get_live_view()
    catalog = get_object_catalog()
    faces = get_face_gallery()
    try:
        vision.warmup()              # load YOLO up front so the first frame isn't slow
    except Exception:                # noqa: BLE001
        pass
    # wire the face recognizer with our no-install embedder + the saved gallery,
    # so enrolled people are named live.
    frproc = None
    try:
        for _p in vision.pipeline.processors():
            if getattr(_p, "name", "") == "face_recognition":
                _p.set_embedder(simple_embedding, gallery=faces.vectors(), threshold=0.86)
                frproc = _p
    except Exception:                # noqa: BLE001
        pass
    font = cv2.FONT_HERSHEY_SIMPLEX
    last_desc = ""
    last_sync = 0.0
    last_person = 0.0
    while not stop.is_set():
        try:
            cam_ids = vision.transport.manager.camera_ids()
            if not cam_ids:
                time.sleep(0.4)
                continue
            for cid in cam_ids:
                # the vision system is the sole frame driver: pull one frame
                frame = vision.transport.consume(cid)
                if frame is None:
                    vision.transport.pump(cid, max_frames=1)
                    frame = vision.transport.consume(cid)
                if frame is None or frame.data is None:
                    continue

                result = vision.pipeline.process(frame)
                observations = vision.builder.build(result, frame)
                vision.bridge.process(result, observations, frame)   # scene/world

                img = frame.data.copy()
                objs = []
                for d in result.detections():
                    label = getattr(d, "label", "thing")
                    conf = float(getattr(d, "confidence", 0.0) or 0.0)
                    kind = getattr(d, "kind", "object")
                    objs.append({"label": label, "confidence": round(conf, 2),
                                 "kind": kind})
                    bb = getattr(d, "bbox", None)
                    if bb is not None:
                        person = kind == "person" or label == "person"
                        color = (80, 220, 80) if person else (40, 180, 255)
                        cv2.rectangle(img, (bb.x, bb.y), (bb.x + bb.w, bb.y + bb.h),
                                      color, 2)
                        cv2.putText(img, f"{label} {int(conf * 100)}%",
                                    (bb.x, max(14, bb.y - 6)), font, 0.5, color, 2,
                                    cv2.LINE_AA)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    live.update(buf.tobytes(), objs)   # → the dashboard

                # narrate + remember, but throttled (don't hammer SQLite per frame)
                now = time.time()
                if now - last_sync >= 1.0:
                    last_sync = now
                    desc = _describe(objs)
                    if desc != last_desc:
                        print(f"  \N{EYE} she sees: {desc}")
                        last_desc = desc
                    # learn a face on request: capture the biggest face in view now
                    pend = faces.take_pending()
                    if pend:
                        fb = None
                        for d in result.detections():
                            if getattr(d, "kind", "") == "face" and getattr(d, "bbox", None):
                                if fb is None or d.bbox.w * d.bbox.h > fb.w * fb.h:
                                    fb = d.bbox
                        if fb is not None:
                            crop = frame.data[max(0, fb.y):fb.y + fb.h,
                                              max(0, fb.x):fb.x + fb.w]
                            vec = simple_embedding(crop)
                            faces.enroll(pend, vec)
                            if frproc is not None:
                                frproc.enroll(pend, vec)
                            live.add_event(f"Learned {pend}'s face", "new")
                            print(f"     \N{PENCIL} learned {pend}'s face")
                        else:
                            faces.request_enroll(pend)   # re-queue until a face is in view
                            live.add_event(f"To learn {pend}: put a face in view", "info")

                    # proactive: someone appearing (after a gap) is worth flagging —
                    # by name if she recognises them
                    named = [o["label"] for o in objs
                             if o["kind"] in ("face", "person")
                             and o["label"] not in ("person", "face", "motion_region")]
                    person_now = named or any(
                        o["kind"] in ("face", "person") or o["label"] == "person"
                        for o in objs)
                    if person_now and (now - last_person > 12):
                        who = named[0] if named else "Someone"
                        live.add_event(f"{who} appeared in view", "person")
                        print(f"     \N{WAVING HAND SIGN} {who} appeared")
                    if person_now:
                        last_person = now
                    for o in objs:
                        label = o["label"]
                        if label == "motion_region":
                            continue
                        res = catalog.observe(label, o["confidence"], o["kind"])
                        if res == "new":
                            print(f"     \N{PENCIL} tagged a new object: {label}")
                            live.add_event(f"New: {label}", "new")
                        # keep the world model in sync — by NAME when recognised
                        if o["kind"] in ("face", "person") or label == "person":
                            is_named = label not in ("person", "face")
                            if is_named:
                                faces.note_seen(label)
                            world.observe(
                                "person", label if is_named else "person (seen on camera)",
                                state={"source": "camera", "last_seen": frame.timestamp})
                        else:
                            world.observe("visual_object", label,
                                          state={"source": "camera", "label": label,
                                                 "last_seen": frame.timestamp})
        except Exception:  # noqa: BLE001 — eyes never crash the server
            time.sleep(0.3)
        time.sleep(0.12)
    try:
        catalog.flush()                  # persist the catalog on shutdown
    except Exception:                    # noqa: BLE001
        pass


_FRIENDLY = {                       # label -> (singular, plural) irregulars
    "motion_region": ("area of movement", "areas of movement"),
    "person": ("person", "people"),
}


def _plural(word: str, n: int) -> str:
    if n == 1:
        return word
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _describe(objects) -> str:
    if not objects:
        return "nothing distinct yet -- no motion or objects in view"
    counts = Counter(o.get("label", "thing") for o in objects)
    parts = []
    for label, n in counts.items():
        base = label.replace("_", " ")
        if label in _FRIENDLY:
            word = _FRIENDLY[label][0] if n == 1 else _FRIENDLY[label][1]
        else:
            word = _plural(base, n)
        parts.append(f"{n} {word}")
    return ", ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
