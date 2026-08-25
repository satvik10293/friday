"""
core/vision/transport/server.py — FRIDAY 6.1 (M14)
The browser-camera ingress: a productionized version of the owner's Flask + SocketIO
receiver. It is the **permanent transport foundation** — not replaced, but
modularized and integrated:

  • Flask + SocketIO are kept (and imported lazily, so the transport core needs
    neither installed).
  • The original `frame` protocol (a base64 JPEG data-URL) is preserved for backward
    compatibility; an optional `register` event lets a client claim a *permanent*
    camera id (survives refresh).
  • The handler does NO decoding or cognition — it routes raw payloads to the Camera
    Manager (`submit_raw`), which decodes off the socket thread.
  • M10 security headers are applied; ngrok is optional and lazily imported.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from .manager import CameraManager
from .adapters.browser_adapter import BrowserAdapter

log = logging.getLogger("friday.vision.server")

_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_HOST = "127.0.0.1"   # localhost by default — LAN exposure is explicit opt-in
DEFAULT_PORT = 5000


def _is_localhost(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _vision_headers() -> dict:
    """Security headers for the camera page. Unlike the generic cockpit headers
    (which DISABLE the camera and forbid external/socket connects), these:
      · ALLOW the camera for this same origin (getUserMedia works),
      · allow the self-hosted socket.io client + inline bootstrap,
      · allow the same-origin websocket the stream rides on.
    Still same-origin, still no framing — just fit for a camera."""
    csp = ("default-src 'self'; "
           "script-src 'self' 'unsafe-inline'; "
           "style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data: blob:; "
           "media-src 'self' blob:; "
           "connect-src 'self' ws: wss:; "
           "frame-ancestors 'none'; base-uri 'self'")
    return {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        # camera=(self) lets THIS page use the camera; mic stays off.
        "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    }


def _ensure_socketio_js() -> Optional[Path]:
    """Vendor the socket.io browser client next to the app so the page loads it
    from the SAME origin (no CDN, no phone-internet needed, CSP 'self' covers it).
    Downloaded once from cdnjs (the PC has internet); reused after."""
    p = _ROOT / "data" / "vision" / "friday_sio.min.js"
    if p.exists() and p.stat().st_size > 1000:
        return p
    try:
        import urllib.request
        p.parent.mkdir(parents=True, exist_ok=True)
        url = ("https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/"
               "socket.io.min.js")
        urllib.request.urlretrieve(url, p)
        return p if p.exists() and p.stat().st_size > 1000 else None
    except Exception:  # noqa: BLE001 - offline PC: fall back handled by caller
        log.warning("could not vendor socket.io client (no internet?)")
        return None

# Backward-compatible client page; adds a localStorage camera token + capture_time.
HTML_PAGE = r"""<!doctype html><html><head><title>FRIDAY Vision — Stream Engine</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>body{text-align:center;font-family:sans-serif;background:#111;color:#0f0;margin:0;padding:18px}
canvas{width:92%;border:2px solid #0f0;border-radius:10px}video{display:none}
button{padding:18px 36px;font-size:18px;margin:16px;background:#0f0;color:#000;border:0;border-radius:6px;font-weight:bold}</style>
</head><body><h1>◆ FRIDAY VISION</h1><p id="status">Ready</p>
<video id="v" autoplay playsinline></video><canvas id="c"></canvas><br>
<button id="b">START LIVE FEED</button>
<script src="/friday-sio.js"></script>
<script>
const s=io(),v=document.getElementById('v'),c=document.getElementById('c'),x=c.getContext('2d'),b=document.getElementById('b'),st=document.getElementById('status');
let token=localStorage.getItem('friday_cam'); if(!token){token='cam-'+Math.random().toString(36).slice(2);localStorage.setItem('friday_cam',token);}
s.on('connect',()=>{ s.emit('register',{token:token,label:navigator.userAgent.slice(0,40)}); });
b.onclick=async()=>{try{const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
v.srcObject=stream;b.style.display='none';st.innerText='Streaming…';
v.onloadedmetadata=()=>{c.width=v.videoWidth;c.height=v.videoHeight;setInterval(send,100);};}catch(e){alert('Camera error: '+e);}};
function send(){x.drawImage(v,0,0,c.width,c.height);s.emit('frame',{data:c.toDataURL('image/jpeg',0.5),capture_time:Date.now()/1000});}
</script></body></html>"""


# The live recognition dashboard — open on a laptop/second screen while the phone
# streams. Shows the annotated feed (boxes drawn by the eyes loop) plus what she
# is seeing now and everything she has recognised so far.
LIVE_HTML = r"""<!doctype html><html><head><title>FRIDAY — Live Recognition</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
:root{--bg:#0a0e14;--card:#121821;--ink:#e6edf3;--dim:#7d8590;--accent:#3fb950}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:14px 20px;border-bottom:1px solid #1f2630;display:flex;
align-items:center;gap:12px}
header h1{font-size:18px;margin:0;font-weight:600}
.dot{width:10px;height:10px;border-radius:50%;background:#f85149}
.dot.on{background:var(--accent);box-shadow:0 0 8px var(--accent)}
#status{color:var(--dim);font-size:13px;margin-left:auto}
.wrap{display:grid;grid-template-columns:1fr 320px;gap:16px;padding:16px;
max-width:1200px;margin:0 auto}
@media(max-width:820px){.wrap{grid-template-columns:1fr}}
.feed{background:#000;border:1px solid #1f2630;border-radius:12px;overflow:hidden;
position:relative;min-height:240px;display:flex;align-items:center;justify-content:center}
.feed img{width:100%;display:block}
.hint{position:absolute;color:var(--dim);font-size:14px;padding:20px;text-align:center}
.panel{background:var(--card);border:1px solid #1f2630;border-radius:12px;padding:14px}
.panel h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;
color:var(--dim);margin:0 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:8px;min-height:32px}
.chip{background:#1b2a1e;border:1px solid #2ea04326;color:#7ee787;padding:5px 10px;
border-radius:999px;font-size:13px;font-weight:600}
.chip.person{background:#12233a;border-color:#388bfd33;color:#79c0ff}
.chip .c{opacity:.6;font-weight:400;margin-left:4px}
.grid{display:flex;flex-wrap:wrap;gap:8px}
.seen{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:6px 10px;
font-size:13px;color:var(--ink)}.seen .n{color:var(--dim);margin-left:6px}
.empty{color:var(--dim);font-size:13px}
</style></head><body>
<header><span class="dot" id="dot"></span><h1>◆ FRIDAY — Live Recognition</h1>
<span id="status">waiting for the camera…</span></header>
<div class="wrap">
  <div class="feed"><img id="cam" alt=""/><div class="hint" id="hint">
    No frames yet. Start the phone camera (tap START LIVE FEED) and point it at things.
  </div></div>
  <div>
    <div class="panel"><h2>Seeing now</h2><div class="chips" id="now">
      <span class="empty">nothing in view</span></div></div>
    <div class="panel" style="margin-top:14px">
      <h2>Remembered objects <span id="memcount" class="c"></span></h2>
      <div class="grid" id="seen"><span class="empty">—</span></div></div>
  </div>
</div>
<script>
const cam=document.getElementById('cam'),hint=document.getElementById('hint'),
dot=document.getElementById('dot'),status=document.getElementById('status'),
nowEl=document.getElementById('now'),seenEl=document.getElementById('seen'),
memcount=document.getElementById('memcount');
let lastFrames=-1;
function ago(ts){const s=Math.max(0,Date.now()/1000-ts);
  if(s<60)return 'just now';if(s<3600)return Math.floor(s/60)+'m ago';
  if(s<86400)return Math.floor(s/3600)+'h ago';return Math.floor(s/86400)+'d ago';}
setInterval(()=>{cam.src='/live/frame.jpg?t='+Date.now();},120);
cam.onload=()=>{hint.style.display='none';};
async function poll(){
  try{
    const r=await fetch('/live/objects.json'); const d=await r.json();
    const live=d.frames>lastFrames; lastFrames=d.frames;
    dot.className='dot'+((d.has_frame&&live)?' on':'');
    status.textContent=d.has_frame?('recognising — '+d.frames+' frames'):'waiting for the camera…';
    if(!d.objects||!d.objects.length){nowEl.innerHTML='<span class="empty">nothing in view</span>';}
    else{
      const counts={};
      d.objects.forEach(o=>{counts[o.label]=(counts[o.label]||0)+1;});
      nowEl.innerHTML=Object.entries(counts).map(([l,n])=>{
        const p=l==='person'?' person':'';
        return '<span class="chip'+p+'">'+l+(n>1?'<span class="c">×'+n+'</span>':'')+'</span>';
      }).join('');
    }
  }catch(e){status.textContent='reconnecting…';}
}
async function pollCatalog(){
  try{
    const r=await fetch('/live/catalog.json'); const d=await r.json();
    memcount.textContent=d.count?('· '+d.count+' tagged'):'';
    seenEl.innerHTML=d.objects&&d.objects.length? d.objects.map(o=>
      '<span class="seen" title="first seen '+ago(o.first_seen)+', '+o.sightings+
      ' sighting(s)"><b style="color:#79c0ff">'+o.tag+'</b> '+o.label+
      '<span class="n">×'+o.sightings+'</span></span>').join('')
      : '<span class="empty">— point the camera at things —</span>';
  }catch(e){}
}
setInterval(poll,300); poll();
setInterval(pollCatalog,1200); pollCatalog();
</script></body></html>"""


class VisionTransportServer:
    def __init__(self, manager: CameraManager, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, use_ngrok: bool = False,
                 allow_lan: bool = False, use_https: bool = False,
                 cors_origins=None) -> None:
        self._manager = manager
        # Mobile browsers only expose the camera (getUserMedia) in a "secure
        # context" — HTTPS or localhost. A phone hitting a plain-http LAN address
        # can't stream, so LAN serving defaults to a self-signed HTTPS cert.
        self._https = use_https
        # Override for tunnel mode: a trusted tunnel (cloudflared) serves a random
        # public origin, so the socket CORS must accept it (use "*" behind the
        # tunnel — it only reaches localhost anyway).
        self._cors_origins = cors_origins
        # LAN binding (0.0.0.0 / a routable host) requires an explicit opt-in;
        # otherwise the camera stream stays on localhost. This closes an
        # unauthenticated-camera-server-on-the-LAN hole.
        if not _is_localhost(host) and not allow_lan:
            log.warning("vision transport: refusing to bind %s without allow_lan=True; "
                        "falling back to 127.0.0.1", host)
            host = DEFAULT_HOST
        if not _is_localhost(host):
            log.warning("vision transport bound to %s — the camera stream is reachable "
                        "on your local network", host)
        self.host = host
        self.port = port
        self._lan = not _is_localhost(host)
        self._use_ngrok = use_ngrok
        self._app = None
        self._socketio = None
        self._sid_camera: dict[str, str] = {}      # socket session → camera id

    @property
    def manager(self) -> CameraManager:
        return self._manager

    def build_app(self):
        if self._app is not None:
            return self._app
        try:
            from flask import Flask, request
            from flask_socketio import SocketIO
        except ImportError as e:  # pragma: no cover - optional dep
            raise RuntimeError("Flask + flask-socketio are required to run the vision "
                               "transport server (pip install flask-socketio)") from e
        app = Flask("friday_vision_transport")
        # Same-origin only: the client page is self-served, so it needs no
        # cross-origin access. A wildcard would let any website drive the socket.
        socketio = SocketIO(app,
                            cors_allowed_origins=self._cors_origins or self._allowed_origins())
        mgr = self._manager

        @app.after_request
        def _secure(resp):  # pragma: no cover - needs the running app
            # The camera page needs headers the generic cockpit set forbids:
            # camera must be ALLOWED (the cockpit disables it), and the socket
            # client must be loadable + able to open a websocket.
            for k, v in _vision_headers().items():
                resp.headers[k] = v
            return resp

        @app.get("/")
        def index():  # pragma: no cover
            return HTML_PAGE

        @app.get("/friday-sio.js")
        def _sio_js():  # pragma: no cover - self-hosted socket.io client
            from flask import Response
            js = _ensure_socketio_js()
            body = js.read_bytes() if js else b"// socket.io client unavailable"
            return Response(body, mimetype="application/javascript")

        # ── live recognition dashboard ───────────────────────────────────────────
        @app.get("/live")
        def _live_page():  # pragma: no cover - needs a browser
            return LIVE_HTML

        @app.get("/live/frame.jpg")
        def _live_frame():  # pragma: no cover
            from flask import Response
            from .live_view import get_live_view
            jpg = get_live_view().frame()
            if not jpg:
                # 1x1 gray placeholder until the first annotated frame arrives
                jpg = bytes.fromhex(
                    "ffd8ffe000104a46494600010100000100010000ffdb004300"
                    "080606070605080707070909080a0c140d0c0b0b0c1912130f14"
                    "1d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434"
                    "1f27393d38323c2e333432ffc0000b080001000101011100ffc4"
                    "001f0000010501010101010100000000000000000102030405060"
                    "708090a0bffc400b5100002010303020403050504040000017d01"
                    "020300ffda0008010100003f00d2cf20ffd9")
            return Response(jpg, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store"})

        @app.get("/live/objects.json")
        def _live_objects():  # pragma: no cover
            from flask import jsonify
            from .live_view import get_live_view
            return jsonify(get_live_view().state())

        @app.get("/live/catalog.json")
        def _live_catalog():  # pragma: no cover - the remembered, tagged objects
            from flask import jsonify
            from core.vision.memory.object_catalog import get_object_catalog
            cat = get_object_catalog()
            return jsonify({"objects": cat.all(), "count": cat.count()})

        @socketio.on("register")
        def _register(payload):  # pragma: no cover - needs socket clients
            token = (payload or {}).get("token") or request.sid
            label = (payload or {}).get("label", "")
            cid = mgr.register(BrowserAdapter(key=str(token), label=str(label)))
            self._sid_camera[request.sid] = cid

        @socketio.on("frame")
        def _frame(payload):  # pragma: no cover - needs socket clients
            cid = self._sid_camera.get(request.sid)
            if cid is None:                            # legacy client without register
                cid = mgr.register(BrowserAdapter(key=request.sid, label="legacy"))
                self._sid_camera[request.sid] = cid
            if isinstance(payload, dict):
                data, cap = payload.get("data"), float(payload.get("capture_time") or 0.0)
            else:
                data, cap = payload, 0.0               # legacy: bare data-URL string
            mgr.submit_raw(cid, data, capture_time=cap, recv_time=time.time())

        @app.get("/api/vision/health")
        def _health():  # pragma: no cover
            from flask import jsonify
            return jsonify(mgr.health())

        @app.get("/api/vision/dashboard")
        def _dashboard():  # pragma: no cover
            from flask import jsonify
            return jsonify(mgr.dashboard())

        self._app = app
        self._socketio = socketio
        return app

    def _allowed_origins(self) -> list:
        scheme = "https" if self._https else "http"
        origins = [f"{scheme}://127.0.0.1:{self.port}",
                   f"{scheme}://localhost:{self.port}"]
        if self._lan:
            origins.append(f"{scheme}://{self.host}:{self.port}")
        return origins

    def _ssl_context(self):
        """A persistent self-signed cert (data/vision/cam_cert.*) so the phone
        gets a secure context. Self-signed → the browser warns once; you tap
        'proceed'. Reused across runs so it only warns the first time."""
        base = _ROOT / "data" / "vision"
        base.mkdir(parents=True, exist_ok=True)
        crt, key = base / "cam_cert.crt", base / "cam_cert.key"
        if not (crt.exists() and key.exists()):
            from werkzeug.serving import make_ssl_devcert
            make_ssl_devcert(str(base / "cam_cert"), host=self.host)
        return (str(crt), str(key))

    def run(self, *, debug: bool = False) -> None:  # pragma: no cover - blocking server
        # The Werkzeug debugger is a remote-code-execution surface; it must never
        # run on a server that can accept camera frames. Force it off.
        if debug:
            log.warning("vision transport: debug mode is not permitted; ignoring")
        app = self.build_app()
        self._manager.start()
        if self._use_ngrok:
            self._open_ngrok()
        kwargs = {}
        if self._https:
            kwargs["ssl_context"] = self._ssl_context()
        scheme = "https" if self._https else "http"
        log.info("Vision transport on %s://%s:%d", scheme, self.host, self.port)
        self._socketio.run(app, host=self.host, port=self.port, debug=False,
                           allow_unsafe_werkzeug=True, **kwargs)

    def _open_ngrok(self) -> None:  # pragma: no cover - optional + network
        try:
            from pyngrok import ngrok
            url = ngrok.connect(self.port).public_url
            log.info("ngrok tunnel: %s", url)
            print(f"[FRIDAY VISION] open on your phone: {url}")
        except Exception as e:  # noqa: BLE001
            log.warning("ngrok unavailable: %s", e)
