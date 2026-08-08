"""
friday_gesture.py — Friday 3.0
Gesture control, built on MediaPipe's modern **HandLandmarker Tasks API**
(mediapipe >= 0.10 removed the old mp.solutions.hands). The 21-point hand model
is bundled at core/io/models/hand_landmarker.task.

Discrete gestures (debounced + cooldown):
    Fist          → minimize all windowed apps
    Open palm     → restore all windows
    Call me 🤙    → launch friday_spine.py (voice mode)
    Point ☝       → bring Friday's window to the front
    Peace ✌       → "scout": ask Friday about what's on screen (via listener)
    Thumbs up 👍  → approve / acknowledge (via listener)

Continuous:
    Pinch 🤏      → thumb↔index distance sets system volume (needs pycaw; config-gated)

Design notes:
  • Heavy deps (cv2, mediapipe, pycaw) are imported lazily inside start()/_loop()
    so importing this module stays side-effect-free. Nothing runs at import time.
  • OS-level actions live here; "ask Friday" gestures are delivered to a listener
    (friday_face registers one) so the HUD can react and route to the brain.

Run standalone:
    python -m core.io.friday_gesture --preview
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("friday.gesture")

# ── Paths / config ────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]                              # project root
_CONFIG_PATH = _ROOT / "friday_config.json"
_MODEL_PATH = _HERE / "models" / "hand_landmarker.task"
SPINE_PATH = _ROOT / "friday_spine.py"
FRIDAY_WINDOW_TITLE = "Friday 3.0"

WEBCAM_INDEX   = 0
CAM_FPS        = 60          # ask the camera for a high frame rate (MJPG)
DETECT_CONF    = 0.5
PRESENCE_CONF  = 0.5
TRACK_CONF     = 0.5

# Low-latency trigger. We fire as soon as a gesture is held for a few tens of ms
# (not a fixed frame count), and we only throttle REPEATS of the same gesture —
# so two DIFFERENT commands fire back-to-back with no blanket cooldown.
STABLE_MS         = 90      # hold this long → fire (feels instant; ~2-3 frames)
SAME_COOLDOWN_MS  = 650     # min gap before the SAME gesture can re-fire
MIN_GAP_MS        = 120     # min gap between ANY two triggers (anti-double-fire)

# Pinch→volume tuning (thumb-tip↔index-tip distance, normalised by hand size)
PINCH_MIN      = 0.18
PINCH_MAX      = 0.95
PINCH_ENGAGE_FRAMES = 3


def _gesture_cfg() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("gesture") or {}
    except Exception:
        return {}


# ── Landmark indices ──────────────────────────────────────────────────────────

WRIST      = 0
THUMB_CMC  = 1
THUMB_MCP  = 2
THUMB_IP   = 3
THUMB_TIP  = 4
INDEX_MCP  = 5
INDEX_PIP  = 6
INDEX_DIP  = 7
INDEX_TIP  = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_MCP   = 13
RING_PIP   = 14
RING_TIP   = 16
PINKY_MCP  = 17
PINKY_PIP  = 18
PINKY_TIP  = 20

# 21-point skeleton (drawn manually — Tasks API has no drawing_utils helper).
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)


# ── Finger geometry (orientation-invariant) ──────────────────────────────────
# Instead of "tip is higher than pip" (which only works for an upright hand) we
# decide a finger is extended from the JOINT ANGLE (is it straight?) plus REACH
# (does the tip stretch further from the wrist than the knuckle?). That holds
# whether the hand points up, sideways, or is rotated in-plane.

def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _hand_size(lm) -> float:
    return max(_dist(lm[WRIST], lm[MIDDLE_MCP]), 1e-3)


def _angle(a, b, c) -> float:
    """Angle at point b (degrees) formed by a-b-c in the image plane."""
    v1x, v1y = a.x - b.x, a.y - b.y
    v2x, v2y = c.x - b.x, c.y - b.y
    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 * n2 < 1e-9:
        return 180.0
    cosv = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)))
    return math.degrees(math.acos(cosv))


def _finger_extended(lm, mcp: int, pip: int, tip: int, straight_deg: float = 158.0) -> bool:
    straight = _angle(lm[mcp], lm[pip], lm[tip]) > straight_deg
    reach = _dist(lm[tip], lm[WRIST]) > _dist(lm[pip], lm[WRIST])
    return straight and reach


def _thumb_extended(lm) -> bool:
    straight = _angle(lm[THUMB_MCP], lm[THUMB_IP], lm[THUMB_TIP]) > 150.0
    spread = _dist(lm[THUMB_TIP], lm[INDEX_MCP]) / _hand_size(lm) > 0.5
    return straight and spread


def _finger_states(lm) -> dict:
    return {
        "index":  _finger_extended(lm, INDEX_MCP,  INDEX_PIP,  INDEX_TIP),
        "middle": _finger_extended(lm, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP),
        "ring":   _finger_extended(lm, RING_MCP,   RING_PIP,   RING_TIP),
        "pinky":  _finger_extended(lm, PINKY_MCP,  PINKY_PIP,  PINKY_TIP),
        "thumb":  _thumb_extended(lm),
    }


def _is_thumb_up(lm) -> bool:
    """Thumb is the topmost point and sticks out — for 👍 (orientation: up)."""
    return (lm[THUMB_TIP].y < lm[WRIST].y - 0.05
            and lm[THUMB_TIP].y < lm[INDEX_MCP].y
            and _dist(lm[THUMB_TIP], lm[INDEX_MCP]) / _hand_size(lm) > 0.4)


def _thumb_engaged(lm) -> bool:
    """Thumb is raised/away from the palm (not folded across it). Looser than
    _thumb_extended so it still holds in a tight pinch where the thumb tip sits
    right next to the index tip — that's what separates pinch from point."""
    return _dist(lm[THUMB_TIP], lm[INDEX_MCP]) / _hand_size(lm) > 0.35


# ── Classifier (10 gestures + pinch) ──────────────────────────────────────────

def classify_gesture(lm, handedness: str = "") -> str:
    s = _finger_states(lm)
    index, middle, ring, pinky, thumb = (
        s["index"], s["middle"], s["ring"], s["pinky"], s["thumb"])
    n = sum((index, middle, ring, pinky))
    hs = _hand_size(lm)

    # OK sign: thumb tip pinches index tip while the other three stay extended.
    if (_dist(lm[THUMB_TIP], lm[INDEX_TIP]) / hs < 0.3
            and middle and ring and pinky):
        return "ok"
    # Open palm: all four fingers extended (thumb optional → reliable restore).
    if n == 4:
        return "open_palm"
    # All fingers curled → fist, or thumbs-up if the thumb points up.
    if n == 0:
        return "thumbs_up" if _is_thumb_up(lm) else "fist"
    # Call me: thumb + pinky out, the middle three curled.
    if thumb and pinky and not index and not middle and not ring:
        return "call_me"
    # Rock / horns: index + pinky out, middle + ring curled.
    if index and pinky and not middle and not ring:
        return "rock"
    # Peace: index + middle out, ring + pinky curled.
    if index and middle and not ring and not pinky:
        return "peace"
    # Three: index + middle + ring out, pinky curled.
    if index and middle and ring and not pinky:
        return "three"
    # Point: index only, thumb folded in (index + raised thumb = pinch, below).
    if index and not middle and not ring and not pinky and not _thumb_engaged(lm):
        return "point"
    return "none"


def _is_pinch_pose(lm) -> bool:
    """Index extended, the other three curled, thumb raised toward it → a
    'measure' pinch. Uses thumb-engagement (not strict extension) so it stays
    detected even when fully pinched closed (low-volume end)."""
    s = _finger_states(lm)
    return (s["index"] and not s["middle"] and not s["ring"] and not s["pinky"]
            and _thumb_engaged(lm))


def _pinch_fraction(lm) -> float:
    d = _dist(lm[THUMB_TIP], lm[INDEX_TIP]) / _hand_size(lm)
    frac = (d - PINCH_MIN) / (PINCH_MAX - PINCH_MIN)
    return max(0.0, min(1.0, frac))


# ── Debounce + cooldown ───────────────────────────────────────────────────────

class FastTrigger:
    """Low-latency gesture confirmation.

    Fires the instant a gesture has been held continuously for `stable_ms`
    (time-based → independent of frame rate). A DIFFERENT gesture can fire
    immediately afterwards (gated only by a tiny global `min_gap_ms`), so
    distinct commands recognise back-to-back — there is no blanket cooldown.

    Re-firing the SAME gesture:
      • edge mode (default): you must RELEASE the pose (hand opens / changes /
        leaves frame) before it can fire again. One command per deliberate hold —
        ideal for actions like "minimize all" that you don't want to repeat.
      • hold mode (`retrigger_on_hold=True`): auto-repeats every
        `same_cooldown_ms` while the pose is held."""

    def __init__(self, stable_ms: int = STABLE_MS,
                 same_cooldown_ms: int = SAME_COOLDOWN_MS,
                 min_gap_ms: int = MIN_GAP_MS,
                 retrigger_on_hold: bool = False):
        self.stable_ms = stable_ms
        self.same_cooldown_ms = same_cooldown_ms
        self.min_gap_ms = min_gap_ms
        self.retrigger_on_hold = retrigger_on_hold
        self.candidate = "none"
        self.candidate_since = 0
        self.last_fired = "none"
        self.last_fire_ms = 0
        self.released = True       # have we seen a release since the last fire?

    def update(self, gesture: str) -> Optional[str]:
        now = int(time.time() * 1000)
        if gesture != self.candidate:
            self.candidate = gesture
            self.candidate_since = now
        # A release is any frame whose gesture isn't the one we last fired.
        if gesture != self.last_fired:
            self.released = True
        if gesture == "none":
            return None
        if now - self.candidate_since < self.stable_ms:
            return None
        if now - self.last_fire_ms < self.min_gap_ms:
            return None
        if gesture == self.last_fired:
            if self.retrigger_on_hold:
                if now - self.last_fire_ms < self.same_cooldown_ms:
                    return None
            elif not self.released:
                return None        # edge mode: must release before re-firing
        self.last_fired = gesture
        self.last_fire_ms = now
        self.released = False
        return gesture


# ── Action guard ──────────────────────────────────────────────────────────────

_action_lock = threading.Lock()


def _fire_action(fn):
    if _action_lock.locked():
        return

    def _run():
        with _action_lock:
            try:
                fn()
            except Exception as e:
                log.error("Action %s failed: %s", getattr(fn, "__name__", fn), e)

    threading.Thread(target=_run, daemon=True,
                     name=f"gesture-{getattr(fn, '__name__', 'action')}").start()


# ── Built-in OS actions ───────────────────────────────────────────────────────

def _minimize_all():
    try:
        import ctypes
        import pygetwindow as gw
        user32 = ctypes.windll.user32
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        for w in gw.getAllWindows():
            try:
                if w.title.strip() and not w.isMinimized:
                    is_full = w.isMaximized or (w.width >= sw and w.height >= sh)
                    if not is_full:
                        w.minimize()
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        _status("Fist → minimized windowed apps")
    except Exception as e:
        _status(f"Minimize error: {e}")


def _restore_all():
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            try:
                if w.title.strip() and w.isMinimized:
                    w.restore()
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        _status("Open palm → restored all windows")
    except Exception as e:
        _status(f"Restore error: {e}")


def _focus_friday():
    try:
        import pygetwindow as gw
        wins = gw.getWindowsWithTitle(FRIDAY_WINDOW_TITLE)
        if not wins:
            _status("Point → Friday window not found")
            return
        w = wins[0]
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        _status("Point → brought Friday to the front")
    except Exception as e:
        _status(f"Focus error: {e}")


_spine_process: Optional[subprocess.Popen] = None


def _launch_friday():
    global _spine_process
    if _spine_process and _spine_process.poll() is None:
        _status("Friday voice mode already running")
        return
    try:
        import psutil
        for proc in psutil.process_iter(["cmdline"]):
            try:
                if "friday_spine.py" in " ".join(proc.info.get("cmdline") or []).lower():
                    _status("Friday voice mode already running")
                    return
            except Exception:
                log.debug("suppressed exception", exc_info=True)
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    try:
        _spine_process = subprocess.Popen(
            [sys.executable, str(SPINE_PATH)],
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        _status("Call me → Friday voice mode launched")
    except Exception as e:
        _status(f"Launch error: {e}")


def _media_playpause():
    try:
        import ctypes
        VK_MEDIA_PLAY_PAUSE = 0xB3
        KEYEVENTF_KEYUP = 0x0002
        u = ctypes.windll.user32
        u.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        u.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
        _status("Rock → media play/pause")
    except Exception as e:
        _status(f"Media key error: {e}")


def _screenshot():
    try:
        out = _ROOT / "data" / "screenshots"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"shot_{time.strftime('%Y%m%d-%H%M%S')}.png"
        try:
            import mss
            with mss.mss() as sct:
                sct.shot(output=str(path))
        except Exception:
            from PIL import ImageGrab
            ImageGrab.grab().save(str(path))
        _status(f"Three → screenshot saved ({path.name})")
    except Exception as e:
        _status(f"Screenshot error: {e}")


def _status(msg: str):
    log.info("%s", msg)


# ── Action registry + config-driven map ───────────────────────────────────────

_BUILTIN_ACTIONS = {
    "minimize_all":   _minimize_all,
    "restore_all":    _restore_all,
    "launch_friday":  _launch_friday,
    "focus_friday":   _focus_friday,
    "media_playpause": _media_playpause,
    "screenshot":     _screenshot,
    "none":           None,
    # "scout" and "approve" have no built-in; the listener handles them.
}

_DEFAULT_MAP = {
    "fist":      "minimize_all",
    "open_palm": "restore_all",
    "call_me":   "launch_friday",
    "point":     "focus_friday",
    "peace":     "scout",
    "thumbs_up": "approve",
    "rock":      "media_playpause",
    "three":     "screenshot",
    "ok":        "approve",
}

GESTURE_LABELS = {
    "fist":      "Fist — minimize all",
    "open_palm": "Open palm — restore all",
    "call_me":   "Call me — launch Friday",
    "point":     "Point — focus Friday",
    "peace":     "Peace — scout screen",
    "thumbs_up": "Thumbs up — approve",
    "rock":      "Rock — play/pause",
    "three":     "Three — screenshot",
    "ok":        "OK — approve",
    "pinch":     "Pinch — volume",
    "none":      "",
}


def _resolve_action_map() -> dict:
    cfg = _gesture_cfg()
    mapping = dict(_DEFAULT_MAP)
    mapping.update({k: v for k, v in (cfg.get("actions") or {}).items()})
    if cfg.get("window_actions", True) is False:
        for g in ("fist", "open_palm"):
            mapping[g] = "none"
    return mapping


# ── System volume (pinch control) ─────────────────────────────────────────────

class _VolumeControl:
    """Absolute system volume via pycaw; no-op if pycaw/comtypes are unavailable."""

    def __init__(self):
        self._iface = None
        self._ok = False
        try:
            import comtypes
            comtypes.CoInitialize()
            from pycaw.pycaw import AudioUtilities
            # pycaw >= 2025 exposes the endpoint interface as a property.
            self._iface = AudioUtilities.GetSpeakers().EndpointVolume
            self._iface.GetMasterVolumeLevelScalar()   # probe it works
            self._ok = True
        except Exception as e:
            log.info("Pinch→volume disabled (pycaw unavailable): %s", e)

    @property
    def ok(self) -> bool:
        return self._ok

    def set_fraction(self, frac: float) -> None:
        if not self._ok:
            return
        try:
            self._iface.SetMasterVolumeLevelScalar(max(0.0, min(1.0, frac)), None)
        except Exception:
            log.debug("suppressed exception", exc_info=True)


# ── Runtime state ─────────────────────────────────────────────────────────────

_running    = False
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_frame_lock = threading.Lock()
_latest_frame = None
_latest_gesture_label = "Idle"
_frame_queue: Optional[queue.Queue] = None
_listener: Optional[Callable[[str, str], None]] = None
_max_num_hands: int = 1


def set_listener(fn: Optional[Callable[[str, str], None]]) -> None:
    """Register a callback fn(gesture_id, label) fired on every confirmed gesture.
    Lets the HUD react (toast / timeline) and route 'ask Friday' gestures."""
    global _listener
    _listener = fn


def set_max_hands(n: int) -> None:
    global _max_num_hands
    _max_num_hands = max(1, min(2, int(n)))


# Back-compat no-op (older callers).
def set_mimic_callback(_fn=None) -> None:
    return None


def is_running() -> bool:
    return _running


def get_latest_frame():
    with _frame_lock:
        return None if _latest_frame is None else _latest_frame.copy()


def get_latest_gesture_label() -> str:
    with _frame_lock:
        return _latest_gesture_label


def _publish_frame(frame, gesture_label: str = "") -> None:
    global _latest_frame, _latest_gesture_label
    with _frame_lock:
        _latest_frame = frame.copy()
        _latest_gesture_label = gesture_label or "Watching"
    if _frame_queue is not None:
        try:
            _frame_queue.put_nowait(_latest_frame)
        except queue.Full:
            try:
                _frame_queue.get_nowait()
                _frame_queue.put_nowait(_latest_frame)
            except (queue.Empty, queue.Full):
                pass


def _draw_hand(cv2, frame, lm, w: int, h: int, accent=(242, 238, 114)):
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], accent, 2, cv2.LINE_AA)
    for (x, y) in pts:
        cv2.circle(frame, (x, y), 4, (255, 255, 255), -1, cv2.LINE_AA)


def _loop(show_preview: bool = False):
    global _running, _latest_frame, _latest_gesture_label

    try:
        import cv2
        import numpy as np  # noqa: F401  (mediapipe needs a real ndarray)
        import mediapipe as mp
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
    except Exception as e:
        log.error("Gesture deps missing (cv2 / mediapipe): %s", e)
        _running = False
        return

    if not _MODEL_PATH.exists():
        log.error("Hand model missing: %s", _MODEL_PATH)
        _running = False
        return

    cfg = _gesture_cfg()
    pinch_enabled = bool(cfg.get("pinch_volume", True))
    volume = _VolumeControl() if pinch_enabled else None

    try:
        options = vision.HandLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(_MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=_max_num_hands,
            min_hand_detection_confidence=DETECT_CONF,
            min_hand_presence_confidence=PRESENCE_CONF,
            min_tracking_confidence=TRACK_CONF,
        )
        landmarker = vision.HandLandmarker.create_from_options(options)
    except Exception as e:
        log.error("Could not create HandLandmarker: %s", e)
        _running = False
        return

    cap = None
    for idx in (WEBCAM_INDEX, 1, 2):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            log.info("Webcam opened on index %d", idx)
            break
        cap.release()
        cap = None
    if cap is None:
        log.error("Could not open any webcam — gesture detection disabled.")
        landmarker.close()
        _running = False
        return

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # higher cam FPS
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    cap.set(cv2.CAP_PROP_FPS,          CAM_FPS)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # Dedicated capture thread: keep only the FRESHEST frame so inference never
    # works on a stale image and never blocks on camera I/O. This is the single
    # biggest latency win — the processing loop always sees "now".
    grab_lock = threading.Lock()
    grab = {"frame": None}

    def _grabber():
        while _running and not _stop_event.is_set():
            ok, f = cap.read()
            if not ok:
                time.sleep(0.005)
                continue
            with grab_lock:
                grab["frame"] = f

    grab_thread = threading.Thread(target=_grabber, daemon=True, name="FridayGesture-cap")
    grab_thread.start()

    trigger = FastTrigger(
        stable_ms=int(cfg.get("stable_ms", STABLE_MS)),
        same_cooldown_ms=int(cfg.get("same_cooldown_ms", cfg.get("cooldown_ms", SAME_COOLDOWN_MS))),
        min_gap_ms=int(cfg.get("min_gap_ms", MIN_GAP_MS)),
        retrigger_on_hold=bool(cfg.get("retrigger_on_hold", False)),
    )
    action_map   = _resolve_action_map()
    ts_ms        = 0
    pinch_frames = 0
    banner       = ""
    banner_until = 0

    log.info("Gesture detection ready (low-latency) — fist / palm / call-me / point / "
             "peace / thumbs-up / rock / three / ok%s",
             " / pinch-volume" if (volume and volume.ok) else "")

    while _running and not _stop_event.is_set():
        with grab_lock:
            frame = grab["frame"]
            grab["frame"] = None
        if frame is None:
            time.sleep(0.002)        # nothing new yet — don't busy-wait
            continue

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts_ms = max(ts_ms + 1, int(time.monotonic() * 1000))   # strictly increasing
        try:
            result = landmarker.detect_for_video(mp_image, ts_ms)
        except Exception as e:
            log.debug("detect error: %s", e)
            result = None

        gesture_this_frame = "none"
        pinching = False

        if result and result.hand_landmarks:
            lm = result.hand_landmarks[0]
            _draw_hand(cv2, frame, lm, w, h)

            if volume and volume.ok and _is_pinch_pose(lm):
                pinch_frames += 1
                if pinch_frames >= PINCH_ENGAGE_FRAMES:
                    pinching = True
                    frac = _pinch_fraction(lm)
                    volume.set_fraction(frac)
                    gesture_this_frame = "pinch"
                    cv2.putText(frame, f"VOLUME {int(frac * 100)}%", (10, 78),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (168, 246, 137), 2, cv2.LINE_AA)
            else:
                pinch_frames = 0

            if not pinching:
                gesture_this_frame = classify_gesture(lm)
        else:
            pinch_frames = 0

        if not pinching:
            confirmed = trigger.update(gesture_this_frame)
            if confirmed:
                action_name = action_map.get(confirmed, "none")
                fn = _BUILTIN_ACTIONS.get(action_name)
                if fn:
                    _fire_action(fn)
                if _listener:
                    try:
                        _listener(confirmed, GESTURE_LABELS.get(confirmed, confirmed))
                    except Exception as e:
                        log.debug("listener error: %s", e)
                banner = GESTURE_LABELS.get(confirmed, "")
                banner_until = int(time.time() * 1000) + 1500

        # On-frame HUD
        raw = GESTURE_LABELS.get(gesture_this_frame, "")
        if raw:
            cv2.putText(frame, raw, (10, 38), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (242, 238, 114), 2, cv2.LINE_AA)
        if int(time.time() * 1000) < banner_until and banner:
            cv2.putText(frame, f"> {banner}", (10, h - 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (114, 101, 255), 2, cv2.LINE_AA)

        label = ("Pinch · volume" if pinching
                 else raw.split("—")[0].strip() if raw else "Watching")
        _publish_frame(frame, label)

        if show_preview:
            cv2.imshow("Friday Gesture", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    _running = False
    try:
        grab_thread.join(timeout=1.0)
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    landmarker.close()
    cap.release()
    if show_preview:
        cv2.destroyAllWindows()
    with _frame_lock:
        _latest_frame = None
        _latest_gesture_label = "Idle"
    log.info("Gesture detection stopped.")


# ── Public API ────────────────────────────────────────────────────────────────

def start(show_preview: bool = False, frame_queue: Optional[queue.Queue] = None) -> bool:
    global _running, _thread, _frame_queue
    if _running:
        return True
    if _gesture_cfg().get("enabled", True) is False:
        log.info("Gesture detection disabled in config")
        return False
    _frame_queue = frame_queue
    _stop_event.clear()
    _running = True
    _thread = threading.Thread(target=_loop, args=(show_preview,),
                               daemon=True, name="FridayGesture")
    _thread.start()
    time.sleep(0.6)   # fail fast on missing webcam / deps / model
    return _running


def stop(timeout: float = 2.0) -> None:
    global _running, _frame_queue
    _running = False
    _stop_event.set()
    if _thread and _thread.is_alive() and timeout > 0:
        _thread.join(timeout=timeout)
    _frame_queue = None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Friday 3.0 gesture control")
    parser.add_argument("--preview", action="store_true", help="Show webcam window with overlay")
    args = parser.parse_args()

    print("[FridayGesture] Starting.")
    print("  Fist        — minimize all windows")
    print("  Open palm   — restore all windows")
    print("  Call me     — launch Friday voice mode")
    print("  Point       — bring Friday to the front")
    print("  Peace       — scout the screen")
    print("  Thumbs up   — approve")
    print("  Rock (horns)— media play / pause")
    print("  Three       — screenshot")
    print("  OK sign     — approve")
    print("  Pinch       — thumb/index distance sets volume")
    print("Each gesture fires once per hold (open your hand to re-trigger).")
    print("Press Q in the preview window (or Ctrl+C) to quit.\n")

    if not start(show_preview=args.preview):
        print("[FridayGesture] Could not start (no webcam, deps, model, or disabled).")
        sys.exit(1)
    try:
        while _running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop()
        print("\nStopped.")
