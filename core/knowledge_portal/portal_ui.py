"""
core/knowledge_portal/portal_ui.py — FRIDAY 4.0 (M8)
The single-page dashboard. Everything is visible from one interface (no tabs):
stats, recent knowledge, most-used concepts, search, an interactive knowledge
graph (canvas-based force layout with zoom/pan/selection), and the detail of a
selected concept.

Fully offline: the HTML/CSS/JS is self-contained — no CDN, no external fonts. The
page talks to the portal REST API on the same origin.
"""

from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>FRIDAY — Knowledge Portal</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --line:#21262d; --fg:#c9d1d9;
          --accent:#58a6ff; --muted:#8b949e; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:Segoe UI,system-ui,sans-serif; background:var(--bg);
         color:var(--fg); }
  header { padding:14px 20px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:16px; }
  header h1 { font-size:18px; margin:0; color:var(--accent); letter-spacing:.5px; }
  header .pill { background:var(--panel); border:1px solid var(--line);
                 border-radius:20px; padding:4px 12px; font-size:12px; color:var(--muted); }
  #search { margin-left:auto; }
  #search input { background:var(--panel); border:1px solid var(--line); color:var(--fg);
                  padding:8px 12px; border-radius:6px; width:280px; outline:none; }
  main { display:grid; grid-template-columns:320px 1fr 320px; gap:14px; padding:14px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px;
          padding:14px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.6px;
             color:var(--muted); margin:0 0 10px; }
  .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .stat { background:var(--bg); border:1px solid var(--line); border-radius:8px;
          padding:10px; text-align:center; }
  .stat b { display:block; font-size:22px; color:var(--accent); }
  .stat span { font-size:11px; color:var(--muted); }
  ul.list { list-style:none; margin:0; padding:0; max-height:240px; overflow:auto; }
  ul.list li { padding:7px 8px; border-radius:6px; cursor:pointer; font-size:13px;
               display:flex; justify-content:space-between; gap:8px; }
  ul.list li:hover { background:var(--bg); }
  ul.list li small { color:var(--muted); }
  #graphWrap { position:relative; height:560px; padding:0; overflow:hidden; }
  #graph { width:100%; height:100%; display:block; cursor:grab; }
  #graphHint { position:absolute; bottom:8px; left:12px; font-size:11px; color:var(--muted); }
  #detail .meta { font-size:12px; color:var(--muted); margin-bottom:8px; }
  #detail pre { white-space:pre-wrap; word-wrap:break-word; font-size:13px;
                background:var(--bg); border:1px solid var(--line); border-radius:8px;
                padding:10px; max-height:300px; overflow:auto; }
  .tag { display:inline-block; font-size:11px; padding:2px 8px; border-radius:12px;
         background:var(--bg); border:1px solid var(--line); color:var(--muted); }
  .empty { color:var(--muted); font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>◆ FRIDAY KNOWLEDGE</h1>
  <span class="pill" id="healthPill">health: …</span>
  <span class="pill" id="backendPill">index: …</span>
  <div id="search"><input id="q" placeholder="Search knowledge…" autocomplete="off"/></div>
</header>
<main>
  <div class="col">
    <div class="card">
      <h2>Overview</h2>
      <div class="stat-grid">
        <div class="stat"><b id="sTotal">0</b><span>Knowledge</span></div>
        <div class="stat"><b id="sLinks">0</b><span>Links</span></div>
        <div class="stat"><b id="sActive">0</b><span>Active</span></div>
        <div class="stat"><b id="sArchived">0</b><span>Archived</span></div>
      </div>
    </div>
    <div class="card" style="margin-top:14px;">
      <h2>Most Used Concepts</h2>
      <ul class="list" id="mostUsed"><li class="empty">none yet</li></ul>
    </div>
    <div class="card" style="margin-top:14px;">
      <h2>Recent Knowledge</h2>
      <ul class="list" id="recent"><li class="empty">none yet</li></ul>
    </div>
  </div>

  <div class="col">
    <div class="card" id="graphWrap">
      <canvas id="graph"></canvas>
      <div id="graphHint">scroll = zoom · drag = pan · click a node to inspect</div>
    </div>
  </div>

  <div class="col">
    <div class="card" id="detail">
      <h2>Concept</h2>
      <div id="detailBody"><p class="empty">Select a node or search to inspect a concept.</p></div>
    </div>
    <div class="card" style="margin-top:14px;">
      <h2>Search Results</h2>
      <ul class="list" id="results"><li class="empty">type above…</li></ul>
    </div>
  </div>
</main>

<script>
const api = (p) => fetch(p).then(r => r.json());

async function loadStats() {
  const s = await api('/stats');
  document.getElementById('sTotal').textContent = s.totals.total ?? 0;
  document.getElementById('sLinks').textContent = s.totals.links ?? 0;
  document.getElementById('sActive').textContent = s.totals.active ?? 0;
  document.getElementById('sArchived').textContent = s.totals.archived ?? 0;
  document.getElementById('healthPill').textContent = 'health: ' + (s.health.status||'?');
  document.getElementById('backendPill').textContent = 'index: ' + ((s.index&&s.index.backend)||'?');
  const mu = document.getElementById('mostUsed');
  mu.innerHTML = (s.most_used && s.most_used.length)
    ? s.most_used.map(x => `<li data-id="${x.id}">${esc(x.title)}<small>${x.usage}×</small></li>`).join('')
    : '<li class="empty">none yet</li>';
  const rc = document.getElementById('recent');
  rc.innerHTML = (s.recent && s.recent.length)
    ? s.recent.map(x => `<li data-id="${x.id}">${esc(x.title)}<small>${esc(x.category)}</small></li>`).join('')
    : '<li class="empty">none yet</li>';
  bindList(mu); bindList(rc);
}

function esc(t){ return String(t==null?'':t).replace(/[&<>"]/g, c=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function bindList(ul){
  ul.querySelectorAll('li[data-id]').forEach(li =>
    li.onclick = () => inspect(li.getAttribute('data-id')));
}

async function inspect(id){
  const r = await api('/knowledge/' + id);
  if (r.error){ return; }
  const e = r.item;
  const rel = (r.related||[]).map(x => `<span class="tag" data-id="${x.id}">${esc(x.title)}</span>`).join(' ');
  document.getElementById('detailBody').innerHTML =
    `<div class="meta">${esc(e.category)} · confidence ${(e.confidence*100|0)}% · used ${e.usage_count}×</div>`
    + `<h3 style="margin:.2em 0">${esc(e.title)}</h3>`
    + `<pre>${esc(e.content)}</pre>`
    + (rel ? `<div style="margin-top:8px">${rel}</div>` : '');
  document.querySelectorAll('#detailBody .tag[data-id]').forEach(t =>
    t.style.cursor='pointer', t.onclick=()=>inspect(t.getAttribute('data-id')));
  selected = id; draw();
}

let qTimer;
document.getElementById('q').addEventListener('input', e => {
  clearTimeout(qTimer);
  const q = e.target.value.trim();
  qTimer = setTimeout(async () => {
    const ul = document.getElementById('results');
    if (!q){ ul.innerHTML = '<li class="empty">type above…</li>'; return; }
    const r = await api('/search?q=' + encodeURIComponent(q));
    const items = r.items || [];
    ul.innerHTML = items.length
      ? items.map(x => `<li data-id="${x.id}">${esc(x.title)}<small>${esc(x.tier||x.category||'')}</small></li>`).join('')
      : `<li class="empty">no local hits (tier: ${esc(r.tier)})</li>`;
    bindList(ul);
  }, 220);
});

// ── canvas force graph ───────────────────────────────────────────────────────
let G = {nodes:[], edges:[]}, selected=null;
let cam = {x:0, y:0, z:1}, drag=null;
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');

function resize(){ canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight; }
window.addEventListener('resize', () => { resize(); draw(); });

async function loadGraph(){
  G = await api('/graph');
  const W = canvas.clientWidth || 600, H = canvas.clientHeight || 560;
  G.nodes.forEach((n,i) => {
    const a = (i / Math.max(1,G.nodes.length)) * Math.PI * 2;
    n.x = W/2 + Math.cos(a)*Math.min(W,H)*0.32 + (Math.random()-0.5)*40;
    n.y = H/2 + Math.sin(a)*Math.min(W,H)*0.32 + (Math.random()-0.5)*40;
    n.vx = 0; n.vy = 0;
  });
  for (let s=0; s<140; s++) step();
  draw();
}

function step(){
  const idx = {}; G.nodes.forEach(n => idx[n.id]=n);
  for (let i=0;i<G.nodes.length;i++) for (let j=i+1;j<G.nodes.length;j++){
    const a=G.nodes[i], b=G.nodes[j];
    let dx=a.x-b.x, dy=a.y-b.y, d=Math.hypot(dx,dy)||1;
    const f = 1200/(d*d);
    dx/=d; dy/=d; a.vx+=dx*f; a.vy+=dy*f; b.vx-=dx*f; b.vy-=dy*f;
  }
  G.edges.forEach(e => {
    const a=idx[e.source], b=idx[e.target]; if(!a||!b) return;
    let dx=b.x-a.x, dy=b.y-a.y, d=Math.hypot(dx,dy)||1;
    const f=(d-90)*0.01; dx/=d; dy/=d;
    a.vx+=dx*f; a.vy+=dy*f; b.vx-=dx*f; b.vy-=dy*f;
  });
  const W=canvas.clientWidth||600, H=canvas.clientHeight||560;
  G.nodes.forEach(n => { n.x+=n.vx*0.5; n.y+=n.vy*0.5; n.vx*=0.85; n.vy*=0.85;
    n.x=Math.max(20,Math.min(W-20,n.x)); n.y=Math.max(20,Math.min(H-20,n.y)); });
}

function draw(){
  const W=canvas.width, H=canvas.height;
  ctx.clearRect(0,0,W,H);
  ctx.save(); ctx.translate(cam.x,cam.y); ctx.scale(cam.z,cam.z);
  const idx={}; G.nodes.forEach(n=>idx[n.id]=n);
  ctx.strokeStyle='#30363d'; ctx.lineWidth=1;
  G.edges.forEach(e=>{ const a=idx[e.source], b=idx[e.target]; if(!a||!b)return;
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); });
  G.nodes.forEach(n=>{
    ctx.beginPath(); ctx.arc(n.x,n.y,(n.size||8),0,Math.PI*2);
    ctx.fillStyle = n.color||'#9E9E9E'; ctx.fill();
    if(n.id===selected){ ctx.lineWidth=2; ctx.strokeStyle='#58a6ff'; ctx.stroke(); }
    ctx.fillStyle='#c9d1d9'; ctx.font='11px Segoe UI';
    ctx.fillText(n.label||'', n.x+(n.size||8)+3, n.y+4);
  });
  ctx.restore();
}

canvas.addEventListener('wheel', e=>{ e.preventDefault();
  const f = e.deltaY<0 ? 1.1 : 0.9; cam.z=Math.max(0.2,Math.min(4,cam.z*f)); draw(); },
  {passive:false});
canvas.addEventListener('mousedown', e=>{ drag={x:e.clientX-cam.x, y:e.clientY-cam.y, moved:false}; canvas.style.cursor='grabbing'; });
window.addEventListener('mouseup', e=>{
  if(drag && !drag.moved){ pick(e); }
  drag=null; canvas.style.cursor='grab'; });
window.addEventListener('mousemove', e=>{ if(!drag) return; drag.moved=true;
  cam.x=e.clientX-drag.x; cam.y=e.clientY-drag.y; draw(); });

function pick(e){
  const r=canvas.getBoundingClientRect();
  const mx=(e.clientX-r.left-cam.x)/cam.z, my=(e.clientY-r.top-cam.y)/cam.z;
  let best=null, bd=1e9;
  G.nodes.forEach(n=>{ const d=Math.hypot(n.x-mx,n.y-my); if(d<(n.size||8)+4 && d<bd){bd=d;best=n;} });
  if(best) inspect(best.id);
}

resize(); loadStats(); loadGraph();
setInterval(loadStats, 15000);
</script>
</body>
</html>
"""


def render_dashboard() -> str:
    """Return the complete, self-contained dashboard HTML."""
    return DASHBOARD_HTML
