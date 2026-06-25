"""
core/mission_control/ui.py — FRIDAY 4.0 (M10)
The single-screen Mission Control HUD. Hybrid architecture: a full-viewport WebGL
3D scene (Three.js) for cognitive structures — the knowledge galaxy and goal
network — with 2D overlay panels anchored to the edges for cognitive state,
resources, security, the event stream, and alerts. No tabs, no page switching,
nothing hidden: everything is visible at once.

Offline by contract: Three.js is loaded from a same-origin `/static/three.min.js`
(vendored locally, no CDN). If it isn't present, the HUD degrades to a 2D canvas
renderer so the cockpit still works — resilience extends to the front end.
"""

from __future__ import annotations

HUD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>FRIDAY — Mission Control</title>
<style>
  :root{--bg:#05070d;--panel:rgba(13,20,33,.82);--line:#1c2740;--fg:#cfe3ff;
        --accent:#4da3ff;--ok:#37d39b;--warn:#ffcc55;--crit:#ff5d6c;}
  *{box-sizing:border-box;}
  html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);
            color:var(--fg);font-family:Segoe UI,system-ui,sans-serif;}
  #scene{position:fixed;inset:0;display:block;}
  .panel{position:fixed;background:var(--panel);border:1px solid var(--line);
         border-radius:10px;padding:10px 12px;backdrop-filter:blur(6px);
         font-size:12px;max-height:42vh;overflow:auto;box-shadow:0 0 24px #0008;}
  .panel h2{margin:0 0 8px;font-size:11px;letter-spacing:.7px;text-transform:uppercase;
            color:var(--accent);}
  #pCognitive{top:14px;left:14px;width:280px;}
  #pResources{top:14px;right:14px;width:260px;}
  #pSecurity{bottom:14px;left:14px;width:300px;}
  #pEvents{bottom:14px;right:14px;width:320px;}
  #pAlerts{top:50%;left:50%;transform:translate(-50%,-50%);width:360px;display:none;
           border-color:var(--crit);}
  #title{position:fixed;top:14px;left:50%;transform:translateX(-50%);
         font-size:14px;letter-spacing:3px;color:var(--accent);text-shadow:0 0 12px #4da3ff88;}
  .kv{display:flex;justify-content:space-between;gap:8px;padding:2px 0;}
  .kv span{color:#8aa6cc;}
  .bar{height:5px;border-radius:3px;background:#13203a;margin:3px 0 7px;overflow:hidden;}
  .bar>i{display:block;height:100%;background:var(--accent);}
  .ev{padding:3px 0;border-bottom:1px solid #142037;}
  .ev b{color:var(--accent);} .ev.warning b{color:var(--warn);} .ev.critical b{color:var(--crit);}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ok);margin-right:6px;}
  .dot.deg{background:var(--warn);} .dot.off{background:#54627a;}
  #legend{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);font-size:11px;
          color:#6f86a8;}
</style>
</head>
<body>
<canvas id="scene"></canvas>
<div id="title">◆ FRIDAY MISSION CONTROL</div>

<div class="panel" id="pCognitive"><h2>Cognitive State</h2><div id="cogBody" class="empty">…</div></div>
<div class="panel" id="pResources"><h2>Resources</h2><div id="resBody">…</div></div>
<div class="panel" id="pSecurity"><h2>Security Center</h2><div id="secBody">…</div></div>
<div class="panel" id="pEvents"><h2>Event Stream</h2><div id="evBody">…</div></div>
<div class="panel" id="pAlerts"><h2>⚠ Critical</h2><div id="alertBody"></div></div>
<div id="legend">drag = orbit · scroll = zoom · knowledge galaxy (blue) + goal network (amber) · 3D via Three.js, 2D fallback otherwise</div>

<script>
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t==null?'':t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let THREE=null, three=null;

async function boot(){
  try { THREE = await import('/static/three.module.js'); init3D(); }
  catch(e){ console.warn('Three.js unavailable, 2D fallback', e); init2D(); }
  tick();
  setInterval(tick, 2000);
}

// ── data ──────────────────────────────────────────────────────────────────────
async function tick(){
  let s; try { s = await fetch('/api/state').then(r=>r.json()); } catch(e){ return; }
  const p = s.panels||{};
  renderCognitive(p.cognitive_state||{});
  renderResources(p.resource_monitor||{});
  renderSecurity(p.security_center||{});
  renderEvents(p.event_stream||{});
  updateScene(p.knowledge_space||{}, p.goal_network||{});
}

function statusDot(st){ const c = st==='ok'?'':(st==='degraded'?'deg':'off'); return `<span class="dot ${c}"></span>`; }

function renderCognitive(c){
  $('cogBody').innerHTML = statusDot(c.status) +
    row('Brain', c.brain_status||c.status||'—') + row('Focus', c.current_focus||'—') +
    row('Goal', (c.current_goal&&(c.current_goal.title||c.current_goal))||'—') +
    row('Confidence', c.confidence!=null?(c.confidence*100|0)+'%':'—');
}
function renderResources(r){
  const sys = r.system||{}; let h='';
  if(sys.available){ h += meter('CPU', sys.cpu_percent) + meter('RAM', sys.ram_percent) + meter('Disk', sys.disk_percent);
    h += row('GPU', (sys.gpu&&sys.gpu.present)?'present':'CPU-only'); }
  else h += '<div class="empty">psutil unavailable</div>';
  const db=r.databases||{}, m=r.models||{};
  h += row('Databases', (db.count||0)+' live') + row('Models', (m.total!=null)?m.total:'—');
  $('resBody').innerHTML = statusDot(r.status)+h;
}
function renderSecurity(s){
  const fails = s.failed_access_attempts||0;
  let h = statusDot(s.status) + row('Tokens', s.tokens!=null?s.tokens:'—') +
          row('Failed access', fails);
  (s.recent||[]).slice(0,4).forEach(e=>{ h += `<div class="ev"><b>${esc(e.action)}</b> ${esc(e.result)} <span style="color:#6f86a8">${esc(e.actor)}</span></div>`; });
  $('secBody').innerHTML = h;
}
function renderEvents(e){
  const evs = e.events||[]; let h='';
  evs.slice(0,8).forEach(x=>{ h += `<div class="ev ${esc(x.level)}"><b>${esc(x.kind)}</b> <span style="color:#6f86a8">${esc(x.source||'')}</span></div>`; });
  $('evBody').innerHTML = h || '<div class="empty">no events</div>';
  const alerts = e.alerts||[];
  $('pAlerts').style.display = alerts.length ? 'block':'none';
  if(alerts.length) $('alertBody').innerHTML = alerts.slice(0,5).map(a=>`<div class="ev ${esc(a.level)}"><b>${esc(a.kind)}</b></div>`).join('');
}
function row(k,v){ return `<div class="kv"><span>${esc(k)}</span><b>${esc(v)}</b></div>`; }
function meter(k,v){ v=Math.max(0,Math.min(100,v||0)); return `<div class="kv"><span>${esc(k)}</span><b>${v|0}%</b></div><div class="bar"><i style="width:${v}%"></i></div>`; }

// ── 3D scene (Three.js) ─────────────────────────────────────────────────────────
function init3D(){
  const cv=$('scene'); const r=new THREE.WebGLRenderer({canvas:cv,antialias:true,alpha:true});
  r.setSize(innerWidth,innerHeight); r.setPixelRatio(devicePixelRatio);
  const sc=new THREE.Scene(); const cam=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,4000);
  cam.position.set(0,0,520);
  const kPts=new THREE.Group(), gPts=new THREE.Group(); sc.add(kPts); sc.add(gPts);
  three={r,sc,cam,kPts,gPts,rot:{x:0,y:0},drag:false,lx:0,ly:0,zoom:520};
  addEventListener('resize',()=>{r.setSize(innerWidth,innerHeight);cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();});
  cv.addEventListener('mousedown',e=>{three.drag=true;three.lx=e.clientX;three.ly=e.clientY;});
  addEventListener('mouseup',()=>three.drag=false);
  addEventListener('mousemove',e=>{ if(!three.drag)return; three.rot.y+=(e.clientX-three.lx)*0.005; three.rot.x+=(e.clientY-three.ly)*0.005; three.lx=e.clientX; three.ly=e.clientY; });
  cv.addEventListener('wheel',e=>{e.preventDefault(); three.zoom=Math.max(120,Math.min(1400,three.zoom+(e.deltaY>0?40:-40)));},{passive:false});
  (function render(){ requestAnimationFrame(render);
    three.cam.position.z=three.zoom;
    three.kPts.rotation.y=three.gPts.rotation.y=three.rot.y;
    three.kPts.rotation.x=three.gPts.rotation.x=three.rot.x;
    r.render(sc,cam); })();
}
function nodesToCloud(group,nodes,color,spread){
  while(group.children.length) group.remove(group.children[0]);
  if(!nodes||!nodes.length) return;
  const geo=new THREE.BufferGeometry(); const pos=new Float32Array(nodes.length*3);
  nodes.forEach((n,i)=>{ const a=i*2.399963; const rad=spread*Math.sqrt((i+1)/nodes.length);
    pos[i*3]=Math.cos(a)*rad; pos[i*3+1]=Math.sin(a)*rad; pos[i*3+2]=(Math.random()-0.5)*spread*0.5; });
  geo.setAttribute('position',new THREE.BufferAttribute(pos,3));
  const mat=new THREE.PointsMaterial({color,size:4,transparent:true,opacity:0.9});
  group.add(new THREE.Points(geo,mat));
}
function updateScene(know,goal){
  if(three){ nodesToCloud(three.kPts,know.nodes,0x4da3ff,260); nodesToCloud(three.gPts,goal.nodes,0xffcc55,150); }
  else update2D(know,goal);
}

// ── 2D fallback ─────────────────────────────────────────────────────────────────
let ctx2d=null;
function init2D(){ const cv=$('scene'); cv.width=innerWidth;cv.height=innerHeight; ctx2d=cv.getContext('2d');
  addEventListener('resize',()=>{cv.width=innerWidth;cv.height=innerHeight;}); }
function update2D(know,goal){ if(!ctx2d)return; const W=innerWidth,H=innerHeight;
  ctx2d.clearRect(0,0,W,H);
  const draw=(nodes,color,cx,cy,spread)=>{ (nodes||[]).forEach((n,i)=>{ const a=i*2.39963,rad=spread*Math.sqrt((i+1)/Math.max(1,nodes.length));
    ctx2d.fillStyle=color; ctx2d.beginPath(); ctx2d.arc(cx+Math.cos(a)*rad,cy+Math.sin(a)*rad,2.5,0,7); ctx2d.fill(); }); };
  draw(know.nodes,'#4da3ff',W*0.5,H*0.5,Math.min(W,H)*0.32);
  draw(goal.nodes,'#ffcc55',W*0.5,H*0.5,Math.min(W,H)*0.18);
}

boot();
</script>
</body>
</html>
"""


def render_hud() -> str:
    return HUD_HTML
