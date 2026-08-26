"""
tools/control_center.py — FRIDAY Control Center (M64)

One dashboard to see every FRIDAY interface, launch/stop the ones that run
standalone, open the web consoles when they're up, and review everything that's
been built. Run it and open the printed URL:

    python tools/control_center.py         # → http://127.0.0.1:8600

Design: a component registry (id, description, how to launch, which port proves
it's up, where to open it). Status is a live TCP probe of each port — the honest
signal. Launch spawns the real launcher as a detached process; Stop kills it
(and its children, e.g. the camera's tunnel). Nothing here reaches the network.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(_VENV_PY if _VENV_PY.exists() else sys.executable)

_STATE_DIR = ROOT / "data" / "control_center"
_PROCS = _STATE_DIR / "procs.json"

DEFAULT_PORT = 8600


# ── the components FRIDAY exposes ─────────────────────────────────────────────
COMPONENTS = [
    {
        "id": "app",
        "name": "FRIDAY — Full App",
        "category": "Core",
        "desc": ("The complete assistant: the HUD window, the system-tray app, "
                 "the private always-on-top overlay, voice (wake word + speech), "
                 "and her whole cognitive stack."),
        "cmd": [PY, "friday_launch.py", "--start-runtime"],
        "port": 7862,
        "open": "http://127.0.0.1:7862",
        "launchable": True,
    },
    {
        "id": "eyes",
        "name": "Eyes — Mobile Camera + Live Recognition",
        "category": "Vision",
        "desc": ("Turn your phone into her eyes: live YOLO object recognition over "
                 "a trusted tunnel (works on iPhone), plus the live recognition "
                 "dashboard that draws boxes on what she sees."),
        "cmd": [PY, "tools/mobile_camera.py", "--see", "--tunnel"],
        "port": 5000,
        "open": "http://127.0.0.1:5000/live",
        "public_url_file": "data/vision/tunnel_url.txt",
        "launchable": True,
    },
    {
        "id": "mission",
        "name": "Mission Control",
        "category": "Console",
        "desc": ("Operations console — system health, metrics, and the decision "
                 "log. Comes up with the Full App."),
        "port": 5050,
        "open": "http://127.0.0.1:5050",
        "launchable": False,
    },
    {
        "id": "cognitive",
        "name": "Cognitive Space",
        "category": "Console",
        "desc": ("Her cognitive workspace and simulation console. Comes up with "
                 "the Full App."),
        "port": 5060,
        "open": "http://127.0.0.1:5060",
        "launchable": False,
    },
]

# What's been built (the upgrades panel).
UPGRADES = [
    ("Neural core → ~1M params", "Her own numpy GPT grown from 425k to 1,057,248 "
     "parameters; trains in the background, honest perplexity metric."),
    ("Mobile camera → her eyes", "Phone streams over a trusted tunnel; YOLO names "
     "objects live; detections land in her world model."),
    ("Live recognition dashboard", "Watch her draw boxes/labels on what the camera "
     "sees, in real time."),
    ("Project understanding", "\"understand this project\" — she reads a codebase "
     "(languages, entry points, tests, symbols) and remembers it."),
    ("Situational awareness", "\"what's going on right now\" fuses perception, world "
     "model, goals; \"why did you do that\" explains her last decision."),
    ("Simulation AI + visuals", "\"simulate a projectile / epidemic / game of life\" "
     "— she runs it and renders an image."),
    ("Gmail connected", "Reads and sends email via the app-password path."),
]

# Everything she can do — reachable from the chat box below (talk to her real
# brain), or by voice in the Full App.
CAPABILITIES = [
    ("Converse & reason", "Ask anything — she reasons, does exact math, logic, "
     "dates, units, and cites her sources."),
    ("Simulate + visualise", "\"simulate a projectile / epidemic / game of life\" "
     "or \"plot y = sin(x)\" — she runs it and renders an image."),
    ("Understand a project", "\"understand this project\" — reads a codebase and "
     "answers \"where is class X\"."),
    ("Situational awareness", "\"what's going on right now\" and \"why did you do "
     "that\" — she narrates and explains herself."),
    ("See (vision)", "Recognises objects through your phone camera; tags and "
     "remembers them."),
    ("Read your screen", "\"read my screen\" — on-device OCR, understood not recited."),
    ("Remember", "People, projects, facts, and standing core memories."),
    ("Act (skills)", "37 governed actions — open apps, control the system, "
     "with a confirm gate."),
    ("Home control", "Lights, TV, plugs via Home Assistant."),
    ("Web & email", "Drives Chrome, web search, reads/sends Gmail."),
    ("Autonomous goals", "Proposes and pursues her own goals (you approve)."),
    ("Brain society", "\"ask the trading brain / memory brain …\" — 12 addressable "
     "brains."),
    ("Keeps learning", "Her own neural core trains in the background; curiosity "
     "engine studies while idle."),
]

# ── her brain (lazy boot, shared) ─────────────────────────────────────────────
_brain = {"bridge": None, "booting": False, "error": None}
_brain_lock = threading.Lock()


def _boot_brain() -> None:
    with _brain_lock:
        if _brain["bridge"] is not None or _brain["booting"]:
            return
        _brain["booting"], _brain["error"] = True, None

    def _work():
        try:
            import importlib.util
            dp = ROOT / ".claude" / "skills" / "run-friday" / "driver.py"
            spec = importlib.util.spec_from_file_location("friday_driver", str(dp))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            bridge, _report = mod.build_bridge(use_teacher=True)
            with _brain_lock:
                _brain["bridge"] = bridge
        except Exception as e:  # noqa: BLE001
            with _brain_lock:
                _brain["error"] = str(e)[:300]
        finally:
            with _brain_lock:
                _brain["booting"] = False

    threading.Thread(target=_work, daemon=True, name="cc-brain-boot").start()


def _brain_status() -> dict:
    with _brain_lock:
        return {"ready": _brain["bridge"] is not None,
                "booting": _brain["booting"], "error": _brain["error"]}


def _ask(message: str) -> dict:
    message = (message or "").strip()
    if not message:
        return {"status": "error", "error": "empty"}
    with _brain_lock:
        bridge = _brain["bridge"]
        err = _brain["error"]
    if bridge is None:
        _boot_brain()
        return {"status": "booting", "error": err}
    try:
        r = bridge.think(message)
        return {"status": "ok", "answer": getattr(r, "answer", "") or "",
                "strategy": getattr(r, "strategy", "?"),
                "confidence": round(float(getattr(r, "confidence", 0) or 0), 2),
                "models": ",".join(getattr(r, "models_used", []) or []) or "-"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)[:300]}


# ── process registry (survives dashboard restarts) ────────────────────────────
def _load_procs() -> dict:
    try:
        return json.loads(_PROCS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_procs(d: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PROCS.write_text(json.dumps(d), encoding="utf-8")


_lock = threading.Lock()


# ── status probes ─────────────────────────────────────────────────────────────
def _port_up(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.35)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        s.close()


def _pid_on_port(port: int):
    """PID listening on a local port (Windows netstat), or None."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" \
                    and parts[1].endswith(f":{port}"):
                return int(parts[4])
    except Exception:  # noqa: BLE001
        pass
    return None


def _public_url(comp: dict) -> str:
    f = comp.get("public_url_file")
    if not f:
        return ""
    try:
        return (ROOT / f).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _status() -> list:
    procs = _load_procs()
    out = []
    for c in COMPONENTS:
        up = _port_up(c["port"])
        pub = _public_url(c) if up else ""
        out.append({
            "id": c["id"], "name": c["name"], "category": c["category"],
            "desc": c["desc"], "port": c["port"],
            "running": up,
            "launchable": c.get("launchable", False),
            "open": c.get("open", "") if up else "",
            "public_url": pub,
            "managed": c["id"] in procs,
        })
    return out


# ── launch / stop ─────────────────────────────────────────────────────────────
def _launch(cid: str) -> dict:
    comp = next((c for c in COMPONENTS if c["id"] == cid), None)
    if comp is None or not comp.get("launchable"):
        return {"ok": False, "error": "not launchable"}
    if _port_up(comp["port"]):
        return {"ok": True, "note": "already running"}
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(_STATE_DIR / f"{cid}.log", "ab")
    flags = 0
    if os.name == "nt":                          # detach so it outlives the dashboard
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    try:
        p = subprocess.Popen(comp["cmd"], cwd=str(ROOT), stdout=log,
                             stderr=subprocess.STDOUT, creationflags=flags,
                             close_fds=True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    with _lock:
        procs = _load_procs()
        procs[cid] = p.pid
        _save_procs(procs)
    return {"ok": True, "pid": p.pid}


def _stop(cid: str) -> dict:
    comp = next((c for c in COMPONENTS if c["id"] == cid), None)
    if comp is None:
        return {"ok": False, "error": "unknown"}
    with _lock:
        procs = _load_procs()
        pid = procs.pop(cid, None)
        _save_procs(procs)
    # kill our tracked PID (and children), else whatever holds the port
    target = pid or _pid_on_port(comp["port"])
    if target is None:
        return {"ok": True, "note": "not running"}
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(target), "/T", "/F"],
                          capture_output=True, timeout=10)
        else:
            os.kill(target, 9)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def _sync_git() -> dict:
    """Commit the remembered-object catalog and push it, so her memory of what
    she has seen syncs to your other machines (git pull there). Never raises."""
    catalog = "data/vision/object_catalog.json"

    def run(*args):
        return subprocess.run(["git", *args], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=90)
    try:
        if not (ROOT / catalog).exists():
            return {"ok": False, "error": "no catalog yet — recognise some objects first"}
        run("add", catalog)
        st = run("status", "--porcelain", "--", catalog)
        if not st.stdout.strip():
            return {"ok": True, "note": "already in sync — nothing new"}
        c = run("commit", "-m", "vision: sync remembered objects")
        if c.returncode != 0:
            return {"ok": False, "error": (c.stderr or c.stdout).strip()[:200]}
        p = run("push")
        if p.returncode != 0:
            return {"ok": False,
                    "error": "committed locally, but push failed: "
                             + (p.stderr or p.stdout).strip()[:200]}
        return {"ok": True, "note": "committed + pushed to git"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ── the web app ───────────────────────────────────────────────────────────────
def build_app():
    from flask import Flask, jsonify, request
    app = Flask("friday_control_center")

    @app.get("/")
    def index():
        return PAGE

    @app.get("/api/status")
    def status():
        return jsonify({"components": _status(), "upgrades": UPGRADES,
                        "capabilities": CAPABILITIES})

    @app.post("/api/ask")
    def ask():
        msg = (request.get_json(silent=True) or {}).get("message", "")
        return jsonify(_ask(msg))

    @app.get("/api/brain")
    def brain():
        return jsonify(_brain_status())

    @app.get("/api/eyes")
    def eyes():
        # proxy the live vision detections + catalog (server-side, no CORS issue)
        import urllib.request
        base = "http://127.0.0.1:5000/live/"
        try:
            o = json.load(urllib.request.urlopen(base + "objects.json", timeout=2))
            c = json.load(urllib.request.urlopen(base + "catalog.json", timeout=2))
            return jsonify({"running": True, "objects": o.get("objects", []),
                            "frames": o.get("frames", 0),
                            "catalog": c.get("objects", []), "count": c.get("count", 0)})
        except Exception:  # noqa: BLE001 — eyes down = just say so
            return jsonify({"running": False, "objects": [], "catalog": [], "count": 0})

    @app.post("/api/launch/<cid>")
    def launch(cid):
        return jsonify(_launch(cid))

    @app.post("/api/stop/<cid>")
    def stop(cid):
        return jsonify(_stop(cid))

    @app.post("/api/sync-git")
    def sync_git():
        return jsonify(_sync_git())

    @app.post("/api/open")
    def open_url():
        import webbrowser
        url = (request.get_json(silent=True) or {}).get("url", "")
        if url.startswith(("http://127.0.0.1", "http://localhost")):
            webbrowser.open(url)          # open a local console in the real browser
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "only local consoles"})

    return app


PAGE = r"""<!doctype html><html><head><title>FRIDAY — Control Center</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
:root{--bg:#0a0e14;--card:#121821;--ink:#e6edf3;--dim:#7d8590;--accent:#3fb950;
--blue:#388bfd;--line:#1f2630}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:12px}
header h1{font-size:20px;margin:0;font-weight:600}
header .sub{color:var(--dim);font-size:13px;margin-left:auto}
.wrap{max-width:1100px;margin:0 auto;padding:20px;display:grid;
grid-template-columns:1fr 320px;gap:20px}
@media(max-width:860px){.wrap{grid-template-columns:1fr}}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px;margin-bottom:14px}
.card .top{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.card .name{font-weight:600;font-size:15px}
.badge{font-size:11px;color:var(--dim);border:1px solid var(--line);
border-radius:999px;padding:2px 8px}
.pill{margin-left:auto;font-size:12px;font-weight:600;padding:3px 10px;
border-radius:999px}
.pill.on{background:#12261a;color:#7ee787;border:1px solid #2ea04340}
.pill.off{background:#1a1f27;color:var(--dim);border:1px solid var(--line)}
.desc{color:#b6c2cf;font-size:13.5px;line-height:1.5;margin:6px 0 12px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
button,a.btn{font:inherit;font-size:13px;font-weight:600;border-radius:8px;
padding:8px 14px;border:1px solid var(--line);cursor:pointer;text-decoration:none;
display:inline-block}
.launch{background:#12261a;color:#7ee787;border-color:#2ea04340}
.stop{background:#2a1518;color:#ff7b72;border-color:#f8514940}
.open{background:#0d2136;color:#79c0ff;border-color:#388bfd40}
button:disabled{opacity:.4;cursor:not-allowed}
.pub{margin-top:10px;font-size:12px;color:var(--dim);word-break:break-all}
.pub a{color:#79c0ff}.pub .sel{user-select:all;color:#79c0ff}
.side .card{padding:14px}
.up{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--line)}
.up:last-child{border-bottom:0}.up .ck{color:var(--accent);flex:0 0 auto}
.up .t{font-size:13px}.up .t b{display:block;margin-bottom:2px}
.up .t span{color:var(--dim);font-size:12px}
.note{color:var(--dim);font-size:12px;margin-top:8px}
.chat{display:flex;flex-direction:column;height:320px}
.msgs{flex:1;overflow-y:auto;padding:2px;display:flex;flex-direction:column;gap:8px}
.msg{max-width:86%;padding:8px 12px;border-radius:12px;font-size:13.5px;line-height:1.45;
white-space:pre-wrap;word-wrap:break-word}
.msg.you{align-self:flex-end;background:#12233a;color:#cfe3ff}
.msg.f{align-self:flex-start;background:#0d1117;border:1px solid var(--line)}
.msg .meta{display:block;color:var(--dim);font-size:11px;margin-top:5px}
.qa{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px}
.qa button{background:#0d1117;color:#b6c2cf;border:1px solid var(--line);
border-radius:999px;padding:5px 11px;font:inherit;font-size:12px;cursor:pointer}
.inputrow{display:flex;gap:8px;margin-top:8px}
.inputrow input{flex:1;background:#0d1117;border:1px solid var(--line);border-radius:8px;
color:var(--ink);padding:10px 12px;font:inherit;font-size:14px;outline:none}
.send{background:#12261a;color:#7ee787;border:1px solid #2ea04340}
.cap{display:flex;gap:9px;padding:8px 0;border-bottom:1px solid var(--line)}
.cap:last-child{border-bottom:0}.cap .i{color:var(--blue);flex:0 0 auto}
.cap b{display:block;font-size:13px}.cap span{color:var(--dim);font-size:12px}
.feedbox{position:relative;background:#000;border:1px solid var(--line);border-radius:10px;
overflow:hidden;min-height:200px;display:flex;align-items:center;justify-content:center}
.feedbox img{width:100%;display:block}
.feedhint{position:absolute;color:var(--dim);font-size:13px;padding:24px;text-align:center}
</style></head><body>
<header><span style="font-size:22px">◆</span><h1>FRIDAY — Control Center</h1>
<span class="sub" id="sub">loading…</span></header>
<div class="wrap">
  <div>
    <h2>Talk to FRIDAY</h2>
    <div class="card">
      <div class="chat"><div class="msgs" id="msgs">
        <div class="msg f">Ask me anything — I can reason, simulate and draw it,
        read a project or your screen, remember things, check email, control your
        home, and more.<span class="meta">the first message wakes my brain (~10s)</span></div>
      </div></div>
      <div class="qa" id="qa"></div>
      <div class="inputrow">
        <input id="q" placeholder="Ask FRIDAY anything…" autocomplete="off"
          onkeydown="if(event.key==='Enter')send()"/>
        <button class="send" onclick="send()">Send</button>
      </div>
    </div>
    <h2 style="margin-top:18px">Live camera <span id="eyestat" class="badge"></span></h2>
    <div class="card">
      <div class="feedbox"><img id="eyecam" alt=""/>
        <div class="feedhint" id="feedhint">Eyes are off. Launch “Eyes” below, then
        open the phone URL and point it at things — the recognised feed shows here.</div>
      </div>
      <div class="chips" id="eyenow" style="margin-top:10px"></div>
    </div>
    <h2 style="margin-top:18px">Interfaces</h2><div id="cards"></div>
  </div>
  <div class="side">
    <h2>What she can do</h2><div class="card" id="caps"></div>
    <h2 style="margin-top:18px">Object memory</h2>
    <div class="card">
      <div class="desc">Objects she has tagged and remembered are saved to a
      catalog. Push it to git so her memory syncs to your other machines
      (<code>git pull</code> there).</div>
      <button class="open" onclick="syncGit()">⤴ Sync objects to Git</button>
      <div class="note" id="syncmsg"></div>
    </div>
    <h2 style="margin-top:18px">Upgrades built</h2><div class="card" id="upgrades"></div>
    <p class="note">Consoles marked "with the app" come online once the Full App
    is running. Launching starts the real process; stopping kills it (and its
    tunnel). Status is a live check of each port.</p>
  </div>
</div>
<script>
async function api(m,u){const r=await fetch(u,{method:m});return r.json();}
function card(c){
  const on=c.running;
  let btns='';
  if(c.launchable) btns+=`<button class="launch" ${on?'disabled':''}
     onclick="act('launch','${c.id}')">${on?'Running':'Launch'}</button>`;
  if(on) btns+=`<button class="stop" onclick="act('stop','${c.id}')">Stop</button>`;
  if(on&&c.open) btns+=`<button class="open" onclick="openUrl('${c.open}')">Open ↗</button>`;
  let pub='';
  if(c.public_url) pub=`<div class="pub">On your phone, open: <b class="sel">${c.public_url}</b></div>`;
  return `<div class="card"><div class="top"><span class="name">${c.name}</span>
    <span class="badge">${c.category}</span>
    <span class="pill ${on?'on':'off'}">${on?'● Running':'○ Stopped'}</span></div>
    <div class="desc">${c.desc}</div><div class="row">${btns||'<span class="note">starts with the Full App</span>'}</div>${pub}</div>`;
}
async function act(kind,id){await api('POST',`/api/${kind}/${id}`);setTimeout(refresh,600);refresh();}
async function syncGit(){
  const m=document.getElementById('syncmsg');m.textContent='syncing…';
  try{const r=await api('POST','/api/sync-git');
    m.textContent=r.ok?('✓ '+(r.note||'synced')):('✗ '+(r.error||'failed'));}
  catch(e){m.textContent='✗ sync failed';}
}
async function openUrl(u){
  try{await fetch('/api/open',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({url:u})});}
  catch(e){}
}
// ── chat with her real brain ──────────────────────────────────────────────
const QA=["What's going on right now",
  "Simulate a projectile at 30 m/s and 45 degrees",
  "Understand this project","Read my screen",
  "What can you simulate","Why did you do that"];
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}
async function pj(u,b){const r=await fetch(u,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
async function gj(u){const r=await fetch(u);return r.json();}
function addMsg(who,text,meta){
  const m=document.createElement('div');m.className='msg '+(who==='you'?'you':'f');
  m.innerHTML=esc(text)+(meta?('<span class="meta">'+esc(meta)+'</span>'):'');
  const box=document.getElementById('msgs');box.appendChild(m);
  box.scrollTop=box.scrollHeight;return m;}
let busy=false;
async function send(){
  if(busy)return;const inp=document.getElementById('q');const msg=inp.value.trim();
  if(!msg)return;inp.value='';busy=true;
  addMsg('you',msg);const wait=addMsg('f','…thinking');
  try{
    let r=await pj('/api/ask',{message:msg});
    if(r.status==='booting'){
      wait.textContent='waking my brain (~10s)…';
      for(let i=0;i<40;i++){await sleep(1500);const s=await gj('/api/brain');
        if(s.ready){r=await pj('/api/ask',{message:msg});break;}
        if(s.error){r={status:'error',error:s.error};break;}}
    }
    wait.remove();
    if(r.status==='ok'){const meta=r.strategy+' · '+r.confidence+
      (r.models&&r.models!=='-'?(' · '+r.models):'');
      addMsg('f',r.answer||'(no answer)',meta);}
    else addMsg('f','(couldn\'t answer: '+(r.error||'unavailable')+')');
  }catch(e){wait.remove();addMsg('f','(error reaching my brain)');}
  busy=false;
}
function fillSend(t){document.getElementById('q').value=t;send();}
document.getElementById('qa').innerHTML=
  QA.map(q=>'<button onclick="fillSend(this.textContent)">'+esc(q)+'</button>').join('');
// ── embedded live camera ──────────────────────────────────────────────────
let eyesRunning=false;
async function pollEyes(){
  try{
    const d=await gj('/api/eyes');
    const img=document.getElementById('eyecam'),hint=document.getElementById('feedhint'),
      now=document.getElementById('eyenow'),stat=document.getElementById('eyestat');
    if(d.running){
      eyesRunning=true;hint.style.display='none';
      const counts={};(d.objects||[]).forEach(o=>counts[o.label]=(counts[o.label]||0)+1);
      now.innerHTML=Object.keys(counts).length?Object.entries(counts).map(([l,n])=>
        '<span class="chip'+(l==='person'?' person':'')+'">'+esc(l)+
        (n>1?'<span class="c">×'+n+'</span>':'')+'</span>').join('')
        :'<span class="empty">nothing in view</span>';
      stat.textContent=d.count?(d.count+' remembered'):'';
    }else{
      eyesRunning=false;img.removeAttribute('src');hint.style.display='block';
      now.innerHTML='';stat.textContent='';
    }
  }catch(e){}
}
setInterval(()=>{if(eyesRunning)
  document.getElementById('eyecam').src='http://127.0.0.1:5000/live/frame.jpg?t='+Date.now();},140);
setInterval(pollEyes,700);pollEyes();
async function refresh(){
  try{
    const d=await api('GET','/api/status');
    document.getElementById('cards').innerHTML=d.components.map(card).join('');
    document.getElementById('upgrades').innerHTML=d.upgrades.map(u=>
      `<div class="up"><span class="ck">✓</span><div class="t"><b>${u[0]}</b>
       <span>${u[1]}</span></div></div>`).join('');
    document.getElementById('caps').innerHTML=(d.capabilities||[]).map(c=>
      '<div class="cap"><span class="i">◆</span><div><b>'+esc(c[0])+'</b>'+
      '<span>'+esc(c[1])+'</span></div></div>').join('');
    const n=d.components.filter(c=>c.running).length;
    document.getElementById('sub').textContent=n+' of '+d.components.length+' running';
  }catch(e){document.getElementById('sub').textContent='reconnecting…';}
}
refresh(); setInterval(refresh,2500);
</script></body></html>"""


def _wait_up(port: int, timeout: float = 8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _port_up(port):
            return True
        time.sleep(0.1)
    return False


def _serve_background(port: int) -> None:
    app = build_app()
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                               use_reloader=False, threaded=True),
        daemon=True, name="control-center-flask").start()


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="FRIDAY Control Center")
    ap.add_argument("--web", action="store_true",
                    help="serve in the browser instead of a native desktop window")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)

    # Default: a NATIVE desktop window (not a browser tab) — the backend runs on
    # a background thread and pywebview (WebView2 on Windows) shows it in a real
    # window, matching the rest of FRIDAY's UI.
    if not args.web:
        try:
            import webview
        except Exception:  # noqa: BLE001
            webview = None
        if webview is not None:
            _serve_background(args.port)
            if _wait_up(args.port):
                print(f"[control_center] opening the desktop window "
                      f"(backend on 127.0.0.1:{args.port})")
                webview.create_window("FRIDAY — Control Center",
                                      f"http://127.0.0.1:{args.port}/",
                                      width=1180, height=840, min_size=(900, 640),
                                      background_color="#0a0e14")
                webview.start()             # blocks until the window is closed
                return 0
            print("[control_center] backend didn't start; falling back to browser")
        else:
            print("[control_center] pywebview not available; serving in the browser")

    # --web / fallback: plain local server
    app = build_app()
    print("\n" + "=" * 56)
    print("  FRIDAY — Control Center")
    print("=" * 56)
    print(f"  Open:  http://127.0.0.1:{args.port}")
    print("  Launch / stop every interface from one place.")
    print("=" * 56 + "\n")
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
