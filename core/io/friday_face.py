"""
friday_face.py — Friday 3.0
The UI. The cinematic JARVIS-style HUD ported from Friday 2.0: a WebGL neural
core in the centre, mood-tinted HUD rails, a live conversation timeline, the
mini-brain specialist roster, and gesture control (webcam) overlaid on the core.

Static assets live in  core/io/ui/  (friday_ui.html / .css / .js).
This module is the Flask backend that feeds them.

Endpoints
  GET  /                      → the HUD
  GET  /friday_ui.css|js      → static assets
  GET  /api/status            → full status snapshot (mood, system, brains…)
  POST /api/command           → talk to Friday  (async job → brain.respond)
  POST /api/agents            → deep answer      (async job, mini-brain framing)
  GET  /api/job/<id>          → poll an async job
  GET  /api/events            → SSE event stream (job_done, …)
  POST /gesture/start|stop    → toggle webcam gesture control
  GET  /gesture/status        → {running, label}
  GET  /gesture/stream        → MJPEG of the annotated webcam feed
  Legacy: /chat /greeting /stats /clear /status

    python -m core.io.friday_face        # serves http://127.0.0.1:7862
"""

import sys
import json
import time
import uuid
import queue
import socket
import logging
import threading
import webbrowser
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from typing import Optional

_HERE = Path(__file__).resolve().parent
_UI_DIR = _HERE / "ui"
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.face")

# ── Live state ────────────────────────────────────────────────────────────────

_voice_state = "idle"                       # idle | hearing | thinking | speaking
_events: deque = deque(maxlen=12)           # recent conversation/system events
_last_agents_run: Optional[dict] = None
_state_lock = threading.Lock()

# Async job store {job_id: {"status": "running"|"done"|"error", ...}}
_jobs: dict = {}
_jobs_lock = threading.Lock()

# SSE subscribers (one queue per connected client)
_sse_subscribers: list = []
_sse_lock = threading.Lock()

# Mini-brain specialists — Friday 3.0's real reasoning modules.
_ROSTER = [
    {"id": "neural",    "name": "Neural",    "role": "Cloud reasoning chain (Groq→Gemini→OpenAI)", "tier": "elite"},
    {"id": "local",     "name": "Local",     "role": "On-device retrieval QA (flan-t5)",           "tier": "elite"},
    {"id": "world",     "name": "World",     "role": "Vault knowledge + FAISS search",             "tier": "elite"},
    {"id": "codex",     "name": "Codex",     "role": "Code specialist",                            "tier": "standard"},
    {"id": "planner",   "name": "Planner",   "role": "Planning specialist",                        "tier": "standard"},
    {"id": "critic",    "name": "Critic",    "role": "Answer review",                              "tier": "standard"},
    {"id": "sovereign", "name": "Sovereign", "role": "Background fact extraction",                 "tier": "standard"},
    {"id": "visual",    "name": "Visual",    "role": "Maps / news / images",                       "tier": "standard"},
    {"id": "pdf",       "name": "PDF",       "role": "PDF → notes",                                "tier": "standard"},
]
_ROSTER_NAMES = {a["id"]: a["name"] for a in _ROSTER}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_voice(state: str) -> None:
    global _voice_state
    with _state_lock:
        _voice_state = state


def _record_event(kind: str, detail: str) -> None:
    with _state_lock:
        _events.append({"at": _now_iso(), "kind": kind, "detail": detail})


# ── SSE plumbing ──────────────────────────────────────────────────────────────

def push_event(event_type: str, data: Optional[dict] = None) -> None:
    """Fan an SSE event out to every connected client (local UI only)."""
    msg = f"event: {event_type}\ndata: {json.dumps(data or {})}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            if q in _sse_subscribers:
                _sse_subscribers.remove(q)


# ── Status snapshot (3.0 internals → 2.0 HUD schema) ──────────────────────────

def _battery() -> dict:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return {"percent": -1, "plugged": False}
        return {"percent": int(b.percent), "plugged": bool(b.power_plugged)}
    except Exception:
        return {"percent": -1, "plugged": False}


def _internet(timeout: float = 0.4) -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
        return True
    except Exception:
        return False


def _psyche() -> dict:
    try:
        from core.persona.friday_psyche import full_status
        return full_status()
    except Exception:
        return {}


def _scheduler_data() -> dict:
    try:
        from core.infra.friday_scheduler import list_jobs
        names = list_jobs() or []
        return {
            "enabled": True,
            "running": bool(names),
            "job_count": len(names),
            "jobs": [{"name": str(n), "description": "scheduled"} for n in names],
        }
    except Exception:
        return {"enabled": True, "running": False, "job_count": 0, "jobs": []}


def _gesture_data() -> dict:
    try:
        from core.io import friday_gesture
        return {"running": friday_gesture.is_running(),
                "label": friday_gesture.get_latest_gesture_label()}
    except Exception:
        return {"running": False, "label": "—"}


def _memory_count() -> Optional[int]:
    try:
        from core.knowledge.friday_chronicle import stats as chron_stats
        return int(chron_stats().get("total_memories", 0))
    except Exception:
        return None


def status_snapshot() -> dict:
    psyche = _psyche()
    mood = psyche.get("mood", "neutral")
    trust = float(psyche.get("trust", 0.0) or 0.0)
    focus = float(psyche.get("focus", 0.0) or 0.0)
    turns = int(psyche.get("total_turns", 0) or 0)

    indep = 0
    facts = 0
    try:
        from core.knowledge.friday_sovereign import get_status as sov_status
        ss = sov_status()
        indep = int(ss.get("independence_pct", 0) or 0)
        facts = int(ss.get("facts_extracted", 0) or 0)
    except Exception:
        pass

    confidence = max(trust, indep / 100.0)

    with _state_lock:
        voice = _voice_state
        events = list(_events)
        agents_last = dict(_last_agents_run) if _last_agents_run else None

    agents = {
        "enabled": True,
        "always_active": False,
        "running": 0,
        "active_agents": [],
        "roster": _ROSTER,
        "tier": "elite",
    }
    if agents_last:
        agents["last_run"] = agents_last

    summary = (f"Mood {mood} · {turns} turns · {facts} facts extracted · "
               f"{indep}% independent.")

    return {
        "voice_state": voice,
        "autonomy": {
            "mode": mood,
            "goal": "Stand by and assist Satvik.",
            "confidence": round(confidence, 2),
            "source": "local",
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "class": "Ready",
        },
        "system": {
            "battery": _battery(),
            "wifi": {},
            "internet": _internet(),
            "focus_active": False,
        },
        "agents": agents,
        "scheduler": _scheduler_data(),
        "gesture": _gesture_data(),
        "memory_count": _memory_count(),
        "recent_events": events,
        "system_summary": summary,
    }


# ── Brain access ──────────────────────────────────────────────────────────────

_brain = None


def _get_brain(explicit=None):
    global _brain
    if explicit is not None:
        _brain = explicit
    if _brain is None:
        try:
            from core.brain.friday_brain import get_brain
            _brain = get_brain()
        except Exception as e:
            log.warning("Brain not available: %s", e)
    return _brain


def _build_stats(b) -> dict:
    try:
        from core.knowledge.friday_chronicle import stats as chron_stats
        from core.knowledge.friday_sovereign import get_status as sov_status
        from core.persona.friday_psyche import get_mood
        cs = chron_stats()
        ss = sov_status()
        return {
            "turns":  getattr(b, "_session_len", 0),
            "memory": cs.get("total_memories", 0),
            "facts":  ss.get("facts_extracted", 0),
            "indep":  ss.get("independence_pct", 0),
            "mood":   get_mood(),
        }
    except Exception:
        return {"turns": 0, "memory": 0, "facts": 0, "indep": 0, "mood": "neutral"}


# ── Job runners ───────────────────────────────────────────────────────────────

def _run_command(command: str) -> dict:
    b = _get_brain()
    if not b:
        return {"ok": False, "message": "Brain offline."}
    _record_event("You", command[:120])
    _set_voice("thinking")
    try:
        answer = b.respond(command)
    finally:
        _set_voice("idle")
    if answer == "__EXIT__":
        answer = "Going quiet. Call me when you need me."
    _record_event("Friday", answer[:160])
    return {"ok": True, "command": command, "message": answer}


def _run_agents(task: str, agent_ids: Optional[list]) -> dict:
    global _last_agents_run
    b = _get_brain()
    if not b:
        return {"ok": False, "kind": "agents", "message": "Brain offline."}
    if agent_ids:
        names = [_ROSTER_NAMES.get(i, i) for i in agent_ids if i in _ROSTER_NAMES]
    else:
        low = task.lower()
        names = ["Neural", "World", "Local"]
        if any(w in low for w in ("code", "bug", "python", "function", "refactor")):
            names = ["Codex", "Critic", "Neural"]
        elif any(w in low for w in ("plan", "schedule", "organize", "steps")):
            names = ["Planner", "Neural", "World"]
        elif any(w in low for w in ("screen", "see", "scout", "what is on")):
            names = ["Visual", "Neural", "World"]
    names = names or ["Neural"]

    _record_event("Deploy", f"{', '.join(names)} · {task[:80]}")
    _set_voice("thinking")
    t0 = time.time()
    try:
        answer = b.respond(task)
    finally:
        _set_voice("idle")
    elapsed = round((time.time() - t0) * 1000)

    with _state_lock:
        _last_agents_run = {
            "agent_names": names,
            "answer_preview": answer[:400],
            "elapsed_ms": elapsed,
        }
    _record_event("Friday", answer[:160])
    push_event("agents.completed", {})
    return {
        "ok": True,
        "kind": "agents",
        "message": answer,
        "agents": names,
        "elapsed_ms": elapsed,
        "command": f"use agents {task}",
    }


def _scout_screen() -> None:
    """'Peace' gesture → ask Friday about the current screen, grounded by the
    active window title when available."""
    title = ""
    try:
        from core.io.friday_proactive import active_window_title
        title = (active_window_title() or "").strip()
    except Exception:
        pass
    if title:
        q = (f"I'm looking at \"{title}\" on my screen right now. "
             f"In one or two sentences, what should I do next?")
    else:
        q = "Give me a quick, useful nudge for what to focus on next."
    _run_command(q)


def on_gesture(gesture: str, label: str) -> None:
    """Listener registered with friday_gesture — surfaces gestures on the HUD and
    routes the 'ask Friday' ones to the brain."""
    _record_event("Gesture", label or gesture)
    push_event("gesture", {"gesture": gesture, "label": label})
    push_event("job_done", {})   # nudge the HUD to refresh the timeline
    if gesture == "peace":
        threading.Thread(target=_scout_screen, daemon=True, name="gesture-scout").start()


# ── Flask app ─────────────────────────────────────────────────────────────────

def create_app(brain=None):
    try:
        from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
    except ImportError:
        raise ImportError("Flask not installed. Run: pip install flask")

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "friday-face-secret"
    if brain is not None:
        _get_brain(brain)

    MAX_LEN = 2000

    def _enqueue(label: str, runner):
        job_id = str(uuid.uuid4())
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "command": label}

        def _work(jid):
            try:
                outcome = {"status": "done", **runner()}
            except Exception as exc:
                log.error("Job %s failed: %s", jid, exc, exc_info=True)
                outcome = {"status": "error", "ok": False, "message": str(exc)}
            with _jobs_lock:
                _jobs[jid] = outcome
            push_event("job_done", {"job_id": jid})

        threading.Thread(target=_work, args=(job_id,), daemon=True,
                         name=f"face-job-{job_id[:8]}").start()
        return jsonify({"ok": True, "status": "running", "job_id": job_id})

    # ── Static HUD ────────────────────────────────────────────────────────────

    @app.route("/")
    @app.route("/friday_ui.html")
    def index():
        return send_from_directory(_UI_DIR, "friday_ui.html")

    @app.route("/friday_ui.css")
    def ui_css():
        return send_from_directory(_UI_DIR, "friday_ui.css", mimetype="text/css")

    @app.route("/friday_ui.js")
    def ui_js():
        return send_from_directory(_UI_DIR, "friday_ui.js",
                                   mimetype="application/javascript")

    # ── Status + commands ─────────────────────────────────────────────────────

    @app.route("/api/status")
    def api_status():
        return jsonify(status_snapshot())

    @app.route("/api/command", methods=["POST"])
    def api_command():
        payload = request.get_json(silent=True) or {}
        command = str(payload.get("command", "")).strip()
        if not command:
            return jsonify({"ok": False, "message": "No command provided."}), 400
        if len(command) > MAX_LEN:
            return jsonify({"ok": False, "message": f"Too long (max {MAX_LEN})."}), 400
        return _enqueue(command, lambda: _run_command(command))

    @app.route("/api/agents", methods=["POST"])
    def api_agents():
        payload = request.get_json(silent=True) or {}
        task = str(payload.get("task", "")).strip()
        if not task:
            return jsonify({"ok": False, "message": "No task provided."}), 400
        if len(task) > MAX_LEN:
            return jsonify({"ok": False, "message": f"Too long (max {MAX_LEN})."}), 400
        agent_ids = payload.get("agents")
        if agent_ids is not None and not isinstance(agent_ids, list):
            agent_ids = None
        return _enqueue(f"use agents {task}", lambda: _run_agents(task, agent_ids))

    @app.route("/api/job/<job_id>")
    def api_job(job_id):
        with _jobs_lock:
            job = _jobs.get(job_id)
        if job is None:
            return jsonify({"ok": False, "message": "Job not found."}), 404
        return jsonify(job)

    @app.route("/api/events")
    def api_events():
        def generate():
            q: queue.Queue = queue.Queue(maxsize=50)
            with _sse_lock:
                _sse_subscribers.append(q)
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        yield q.get(timeout=20)
                    except queue.Empty:
                        yield ": ping\n\n"
            finally:
                with _sse_lock:
                    if q in _sse_subscribers:
                        _sse_subscribers.remove(q)
        return Response(stream_with_context(generate()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Gesture control ───────────────────────────────────────────────────────

    @app.route("/gesture/start", methods=["POST"])
    def gesture_start():
        try:
            from core.io import friday_gesture
        except Exception as e:
            return jsonify({"ok": False, "message": f"Gesture unavailable: {e}"}), 500
        try:
            friday_gesture.set_listener(on_gesture)
            ok = friday_gesture.start()
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500
        if not ok:
            return jsonify({"ok": False,
                            "message": "Gesture control could not start "
                                       "(need a webcam + the bundled hand model)."}), 503
        return jsonify({"ok": True,
                        "message": "Gesture control online — fist · palm · "
                                   "call-me · point · peace · thumbs-up · pinch."})

    @app.route("/gesture/stop", methods=["POST"])
    def gesture_stop():
        try:
            from core.io import friday_gesture
            friday_gesture.stop()
        except Exception:
            pass
        return jsonify({"ok": True})

    @app.route("/gesture/status")
    def gesture_status():
        return jsonify(_gesture_data())

    @app.route("/gesture/stream")
    def gesture_stream():
        try:
            import cv2
            from core.io import friday_gesture
        except Exception as e:
            return Response(f"stream unavailable: {e}", status=503)

        def frames():
            boundary = b"--frame\r\n"
            blank_until = time.time() + 8  # tolerate camera warm-up
            while friday_gesture.is_running() or time.time() < blank_until:
                frame = friday_gesture.get_latest_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue
                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if not ok:
                    continue
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                time.sleep(1 / 20)

        return Response(stream_with_context(frames()),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    # ── Legacy chat API (kept for compatibility) ──────────────────────────────

    @app.route("/chat", methods=["POST"])
    def chat():
        data = request.get_json(silent=True) or {}
        text = data.get("message", "").strip()
        if not text:
            return jsonify({"error": "empty message"}), 400
        b = _get_brain()
        if not b:
            return jsonify({"response": "Brain offline.", "stats": {}, "mood": "neutral"})
        _set_voice("thinking")
        try:
            response = b.respond(text)
        finally:
            _set_voice("idle")
        stats = _build_stats(b)
        return jsonify({"response": response, "stats": stats,
                        "mood": stats.get("mood", "neutral")})

    @app.route("/greeting")
    def greeting():
        b = _get_brain()
        return jsonify({"greeting": b.greeting() if b else "Friday 3.0 online."})

    @app.route("/stats")
    def stats():
        b = _get_brain()
        if not b:
            return jsonify({"turns": 0, "memory": 0, "facts": 0, "indep": 0, "mood": "neutral"})
        return jsonify(_build_stats(b))

    @app.route("/clear", methods=["POST"])
    def clear():
        try:
            from core.brain.friday_neural import clear_history
            clear_history()
        except Exception:
            pass
        return jsonify({"ok": True})

    @app.route("/status")
    def status():
        b = _get_brain()
        return jsonify(b.status() if b else {"ready": False})

    return app


# ── Runner ─────────────────────────────────────────────────────────────────────

def run(host: str = "127.0.0.1", port: int = 7862, brain=None,
        debug: bool = False, open_browser: bool = False) -> None:
    """Serve the HUD backend. By default it does NOT open a browser — the UI is
    meant to run as a native desktop window (see friday_app.py). Pass
    open_browser=True only if you explicitly want a browser tab."""
    app = create_app(brain)
    url = f"http://{host}:{port}"
    log.info("Friday Face (cinematic HUD) on %s", url)
    print(f"\n[FridayFace] HUD backend → {url}  (launch the app with: python friday_app.py)\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


def run_background(host: str = "127.0.0.1", port: int = 7862, brain=None) -> threading.Thread:
    t = threading.Thread(
        target=run,
        kwargs={"host": host, "port": port, "brain": brain, "open_browser": False},
        daemon=True, name="friday-face",
    )
    t.start()
    return t


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("\n[friday_face] Starting cinematic HUD...\n")
    try:
        run(debug=False)
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install flask")
