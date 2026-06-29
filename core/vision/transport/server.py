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
from typing import Optional

from .manager import CameraManager
from .adapters.browser_adapter import BrowserAdapter

log = logging.getLogger("friday.vision.server")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000

# Backward-compatible client page; adds a localStorage camera token + capture_time.
HTML_PAGE = r"""<!doctype html><html><head><title>FRIDAY Vision — Stream Engine</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>body{text-align:center;font-family:sans-serif;background:#111;color:#0f0;margin:0;padding:18px}
canvas{width:92%;border:2px solid #0f0;border-radius:10px}video{display:none}
button{padding:18px 36px;font-size:18px;margin:16px;background:#0f0;color:#000;border:0;border-radius:6px;font-weight:bold}</style>
</head><body><h1>◆ FRIDAY VISION</h1><p id="status">Ready</p>
<video id="v" autoplay playsinline></video><canvas id="c"></canvas><br>
<button id="b">START LIVE FEED</button>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
<script>
const s=io(),v=document.getElementById('v'),c=document.getElementById('c'),x=c.getContext('2d'),b=document.getElementById('b'),st=document.getElementById('status');
let token=localStorage.getItem('friday_cam'); if(!token){token='cam-'+Math.random().toString(36).slice(2);localStorage.setItem('friday_cam',token);}
s.on('connect',()=>{ s.emit('register',{token:token,label:navigator.userAgent.slice(0,40)}); });
b.onclick=async()=>{try{const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
v.srcObject=stream;b.style.display='none';st.innerText='Streaming…';
v.onloadedmetadata=()=>{c.width=v.videoWidth;c.height=v.videoHeight;setInterval(send,100);};}catch(e){alert('Camera error: '+e);}};
function send(){x.drawImage(v,0,0,c.width,c.height);s.emit('frame',{data:c.toDataURL('image/jpeg',0.5),capture_time:Date.now()/1000});}
</script></body></html>"""


class VisionTransportServer:
    def __init__(self, manager: CameraManager, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, use_ngrok: bool = False) -> None:
        self._manager = manager
        self.host = host
        self.port = port
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
        from core.security.auth import security_headers

        app = Flask("friday_vision_transport")
        socketio = SocketIO(app, cors_allowed_origins="*")
        mgr = self._manager

        @app.after_request
        def _secure(resp):  # pragma: no cover - needs the running app
            for k, v in security_headers().items():
                resp.headers[k] = v
            return resp

        @app.get("/")
        def index():  # pragma: no cover
            return HTML_PAGE

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

    def run(self, *, debug: bool = False) -> None:  # pragma: no cover - blocking server
        app = self.build_app()
        self._manager.start()
        if self._use_ngrok:
            self._open_ngrok()
        log.info("Vision transport on http://%s:%d", self.host, self.port)
        self._socketio.run(app, host=self.host, port=self.port, debug=debug,
                           allow_unsafe_werkzeug=True)

    def _open_ngrok(self) -> None:  # pragma: no cover - optional + network
        try:
            from pyngrok import ngrok
            url = ngrok.connect(self.port).public_url
            log.info("ngrok tunnel: %s", url)
            print(f"[FRIDAY VISION] open on your phone: {url}")
        except Exception as e:  # noqa: BLE001
            log.warning("ngrok unavailable: %s", e)
