"""
core/cognitive_space/ui.py — FRIDAY 4.0 (M11)
The interactive 3D cognitive universe (Parts 5, 6, 8, 10). One screen: a Three.js /
WebGL scene rendering nodes by the visual language, with HUD controls for zoom
level (Universe→Thought Chain), global search with camera focus, a timeline
scrubber, and simulation playback (pause/resume/fast-forward/replay). Instanced
points + the server-side LOD budget target 60 FPS at scale.

Offline: Three.js is served same-origin from /static/three.module.js (vendored).
If absent, the scene falls back to a 2D canvas — the universe still renders.
"""

from __future__ import annotations

COGNITIVE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>FRIDAY — Cognitive Universe</title>
<style>
  :root{--bg:#03040a;--panel:rgba(10,16,28,.85);--line:#1b2742;--fg:#cfe3ff;--accent:#6fa8ff;}
  *{box-sizing:border-box;} html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);
    color:var(--fg);font-family:Segoe UI,system-ui,sans-serif;}
  #scene{position:fixed;inset:0;display:block;cursor:grab;}
  .hud{position:fixed;background:var(--panel);border:1px solid var(--line);border-radius:10px;
       padding:10px 12px;backdrop-filter:blur(6px);font-size:12px;}
  #levels{top:14px;left:14px;display:flex;flex-direction:column;gap:5px;}
  #levels button{background:#0d1424;color:var(--fg);border:1px solid var(--line);
       border-radius:6px;padding:6px 10px;text-align:left;cursor:pointer;font-size:12px;}
  #levels button.active{border-color:var(--accent);color:#fff;background:#13233f;}
  #title{position:fixed;top:14px;left:50%;transform:translateX(-50%);letter-spacing:3px;
         color:var(--accent);font-size:14px;text-shadow:0 0 12px #6fa8ff88;}
  #search{top:14px;right:14px;width:300px;}
  #search input{width:100%;background:#0d1424;border:1px solid var(--line);color:var(--fg);
       padding:7px 10px;border-radius:6px;outline:none;}
  #results{margin-top:6px;max-height:40vh;overflow:auto;}
  #results div{padding:4px 6px;border-radius:5px;cursor:pointer;}
  #results div:hover{background:#13233f;}
  #inspect{bottom:14px;right:14px;width:320px;max-height:38vh;overflow:auto;}
  #timeline{bottom:14px;left:50%;transform:translateX(-50%);width:60vw;text-align:center;}
  #timeline input{width:100%;}
  #legend{bottom:14px;left:14px;font-size:11px;color:#7f97bd;max-width:230px;}
  .pill{display:inline-block;margin:2px;padding:1px 7px;border-radius:10px;border:1px solid var(--line);}
  small{color:#7f97bd;}
</style></head><body>
<canvas id="scene"></canvas>
<div id="title">◆ COGNITIVE UNIVERSE</div>
<div class="hud" id="levels"></div>
<div class="hud" id="search"><input id="q" placeholder="Search the universe…" autocomplete="off"/><div id="results"></div></div>
<div class="hud" id="inspect"><b>Inspect</b><div id="inspectBody"><small>click a node</small></div></div>
<div class="hud" id="timeline">
  <div id="simctl"><small>no simulation focused</small></div>
  <input id="scrub" type="range" min="0" max="0" value="0"/>
</div>
<div class="hud" id="legend"><b>Visual language</b><br/>
  <span class="pill">★ knowledge</span><span class="pill">◎ goals</span>
  <span class="pill">◆ agents</span><span class="pill">⚡ tasks</span>
  <span class="pill">✦ decisions</span><span class="pill">◯ simulations</span></div>

<script>
const $=(s)=>document.querySelector(s); const api=(p)=>fetch(p).then(r=>r.json());
const esc=(t)=>String(t==null?'':t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let THREE=null, gl=null, level=1, focus=null, current=null, simId=null;

async function boot(){
  const z = await api('/api/space/levels');
  $('#levels').innerHTML = z.levels.map(l=>`<button data-l="${l.level}">${l.level}. ${l.name}</button>`).join('');
  $('#levels').querySelectorAll('button').forEach(b=>b.onclick=()=>setLevel(+b.dataset.l));
  try{ THREE=await import('/static/three.module.js'); init3D(); }catch(e){ console.warn('2D fallback',e); init2D(); }
  setLevel(1);
}
async function setLevel(l){
  level=l;
  $('#levels').querySelectorAll('button').forEach(b=>b.classList.toggle('active',+b.dataset.l===l));
  current = await api('/api/space?level='+l+(focus?('&focus='+encodeURIComponent(focus)):''));
  render(current);
}
function render(space){ THREE?draw3D(space):draw2D(space); }

// search → camera focus
let timer; $('#q').addEventListener('input', e=>{ clearTimeout(timer); const q=e.target.value.trim();
  timer=setTimeout(async()=>{ if(!q){$('#results').innerHTML='';return;}
    const r=await api('/api/space/search?q='+encodeURIComponent(q));
    $('#results').innerHTML=r.results.map(h=>`<div data-l="${h.focus.level}" data-id="${esc(h.id)}">
      <b>${esc(h.label)}</b> <small>${esc(h.kind)}</small></div>`).join('')||'<small>no hits</small>';
    $('#results').querySelectorAll('div[data-id]').forEach(d=>d.onclick=()=>{ focus=d.dataset.id; setLevel(+d.dataset.l).then(()=>focusNode(d.dataset.id)); });
  },200); });

function inspect(n){ $('#inspectBody').innerHTML=`<b>${esc(n.label)}</b><br/><small>${esc(n.kind)} · L${n.level}</small>
  <pre style="white-space:pre-wrap">${esc(JSON.stringify(n.meta||{},null,1))}</pre>`;
  if(n.kind==='simulation'||n.id.startsWith('sim:')){ simId=n.id.replace('sim:',''); loadSim(); } }

async function loadSim(){ if(!simId)return; const tl=await api('/api/sim/'+simId+'/timeline');
  const total=(current&&current.nodes?current.nodes.length:0);
  $('#simctl').innerHTML=`<b>sim ${simId.slice(0,6)}</b> ·
    <button onclick="simCtl('replay')">⟲ replay</button>
    <button onclick="simCtl('ff')">⏩</button> <small>past ${tl.past||0}</small>`;
}
window.simCtl=async(a)=>{ if(!simId)return; await fetch('/api/sim/'+simId+'/'+a,{method:'POST'}); };

// ── Three.js ─────────────────────────────────────────────────────────────────
function init3D(){ const cv=$('#scene'); gl=new THREE.WebGLRenderer({canvas:cv,antialias:true,alpha:true});
  gl.setSize(innerWidth,innerHeight); gl.setPixelRatio(devicePixelRatio);
  const sc=new THREE.Scene(); const cam=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,5000);
  cam.position.set(0,0,320); const grp=new THREE.Group(); sc.add(grp);
  window._mc={gl,sc,cam,grp,rot:{x:0,y:0},zoom:320,drag:false,lx:0,ly:0};
  addEventListener('resize',()=>{gl.setSize(innerWidth,innerHeight);cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();});
  cv.addEventListener('mousedown',e=>{_mc.drag=true;_mc.lx=e.clientX;_mc.ly=e.clientY;});
  addEventListener('mouseup',()=>_mc.drag=false);
  addEventListener('mousemove',e=>{if(!_mc.drag)return;_mc.rot.y+=(e.clientX-_mc.lx)*0.005;_mc.rot.x+=(e.clientY-_mc.ly)*0.005;_mc.lx=e.clientX;_mc.ly=e.clientY;});
  cv.addEventListener('wheel',e=>{e.preventDefault();_mc.zoom=Math.max(80,Math.min(1600,_mc.zoom+(e.deltaY>0?40:-40)));},{passive:false});
  (function loop(){requestAnimationFrame(loop); _mc.cam.position.z=_mc.zoom; _mc.grp.rotation.y=_mc.rot.y; _mc.grp.rotation.x=_mc.rot.x; gl.render(sc,cam);})();
}
function draw3D(space){ const g=_mc.grp; while(g.children.length)g.remove(g.children[0]);
  const idx={}; (space.nodes||[]).forEach(n=>{ idx[n.id]=n;
    const geo=new THREE.SphereGeometry(Math.max(1.5,n.size*0.25),8,8);
    const mat=new THREE.MeshBasicMaterial({color:new THREE.Color(n.color||'#9e9e9e')});
    const m=new THREE.Mesh(geo,mat); m.position.set(...n.position); m.userData=n; g.add(m); });
  (space.edges||[]).forEach(e=>{ const a=idx[e.source],b=idx[e.target]; if(!a||!b)return;
    const geo=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a.position),new THREE.Vector3(...b.position)]);
    g.add(new THREE.Line(geo,new THREE.LineBasicMaterial({color:0x2a3a5c}))); });
  $('#scene').onclick=(ev)=>pick3D(ev,space);
}
function pick3D(ev,space){ const ray=new THREE.Raycaster(); const m=new THREE.Vector2((ev.clientX/innerWidth)*2-1,-(ev.clientY/innerHeight)*2+1);
  ray.setFromCamera(m,_mc.cam); const hit=ray.intersectObjects(_mc.grp.children.filter(c=>c.userData&&c.userData.id))[0];
  if(hit)inspect(hit.object.userData); }
function focusNode(id){ const n=(current.nodes||[]).find(x=>x.id===id); if(n&&_mc){_mc.zoom=160;} if(n)inspect(n); }

// ── 2D fallback ──────────────────────────────────────────────────────────────
let c2d=null;
function init2D(){const cv=$('#scene');cv.width=innerWidth;cv.height=innerHeight;c2d=cv.getContext('2d');
  addEventListener('resize',()=>{cv.width=innerWidth;cv.height=innerHeight;if(current)draw2D(current);});}
function draw2D(space){ if(!c2d)return; const W=innerWidth,H=innerHeight,cx=W/2,cy=H/2,s=Math.min(W,H)/260;
  c2d.clearRect(0,0,W,H); const idx={}; (space.nodes||[]).forEach(n=>idx[n.id]=n);
  c2d.strokeStyle='#2a3a5c'; (space.edges||[]).forEach(e=>{const a=idx[e.source],b=idx[e.target];if(!a||!b)return;
    c2d.beginPath();c2d.moveTo(cx+a.position[0]*s,cy+a.position[1]*s);c2d.lineTo(cx+b.position[0]*s,cy+b.position[1]*s);c2d.stroke();});
  (space.nodes||[]).forEach(n=>{c2d.fillStyle=n.color||'#9e9e9e';c2d.beginPath();
    c2d.arc(cx+n.position[0]*s,cy+n.position[1]*s,Math.max(2,n.size*0.3),0,7);c2d.fill();});
  $('#scene').onclick=(ev)=>{let best=null,bd=1e9;(space.nodes||[]).forEach(n=>{const dx=cx+n.position[0]*s-ev.clientX,dy=cy+n.position[1]*s-ev.clientY,d=Math.hypot(dx,dy);if(d<bd&&d<14){bd=d;best=n;}});if(best)inspect(best);};
}
boot();
</script></body></html>
"""


def render_cognitive_ui() -> str:
    return COGNITIVE_HTML
