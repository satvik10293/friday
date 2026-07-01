const canvas = document.getElementById("friday-core");
const gl = canvas ? canvas.getContext("webgl", { antialias: true, alpha: true }) : null;
const modeValue = document.getElementById("mode-value");
const modeBadge = document.getElementById("mode-badge");
const goalValue = document.getElementById("goal-value");
const autonomyLine = document.getElementById("autonomy-line");
const confidenceValue = document.getElementById("confidence-value");
const sourceValue = document.getElementById("source-value");
const focusValue = document.getElementById("focus-value");
const classValue = document.getElementById("class-value");
const visionValue = document.getElementById("vision-value");
const batteryValue = document.getElementById("battery-value");
const networkValue = document.getElementById("network-value");
const memoryValue = document.getElementById("memory-value");
const agentsValue = document.getElementById("agents-value");
const schedulerValue = document.getElementById("scheduler-value");
const voiceValue = document.getElementById("voice-value");
const screenValue = document.getElementById("screen-value");
const connectionLabel = document.getElementById("connection-label");
const timelineList = document.getElementById("timeline-list");
const commandState = document.getElementById("command-state");
const commandLog = document.getElementById("command-log");
const commandForm = document.getElementById("command-form");
const commandInput = document.getElementById("command-input");
const systemSummary = document.getElementById("system-summary");
const timeValue = document.getElementById("time-value");
const toast = document.getElementById("toast");
const voiceStatus = document.getElementById("voice-status");
const voiceStatusLabel = document.getElementById("voice-status-label");
const agentsRoster = document.getElementById("agents-roster");
const agentsPanelStatus = document.getElementById("agents-panel-status");
const agentsTaskInput = document.getElementById("agents-task-input");
const agentsForm = document.getElementById("agents-form");
const agentsDeployBtn = document.getElementById("agents-deploy");
const agentsLastRun = document.getElementById("agents-last-run");
const agentsFusionTitle = document.getElementById("agents-fusion-title");
const agentsFusionPreview = document.getElementById("agents-fusion-preview");
const schedulerJobList = document.getElementById("scheduler-job-list");
const schedulerPanelTitle = document.getElementById("scheduler-panel-title");
const agentsQuickButtons = [...document.querySelectorAll(".agents-quick__btn")];

const selectedAgentIds = new Set();
let agentsDeploying = false;

const VOICE_LABELS = {
  idle: "Standby",
  hearing: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

let accentColor = [0.9, 1.1, 1.15];
let webglRunning = true;
let toastTimer = null;
let statusConnected = true;

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const commandButtons = [...document.querySelectorAll("[data-command]")];

const vertexSource = `
attribute vec3 position;
attribute vec4 color;
uniform mat4 matrix;
uniform float time;
uniform float pointScale;
varying vec4 vColor;
void main() {
  float pulse = 0.82 + 0.18 * sin(time * 2.4 + position.x * 4.0 + position.y * 3.0);
  vColor = vec4(color.rgb * pulse, color.a);
  vec4 mv = matrix * vec4(position, 1.0);
  gl_Position = mv;
  gl_PointSize = pointScale * (1.0 + color.a * 0.6) * (220.0 / max(-mv.z, 0.5));
}
`;

const fragmentSource = `
precision highp float;
varying vec4 vColor;
uniform vec3 accent;
uniform float time;
void main() {
  vec3 col = vColor.rgb * accent;
  float flicker = 0.92 + 0.08 * sin(time * 5.0 + col.b * 12.0);
  gl_FragColor = vec4(col * flicker, vColor.a);
}
`;

function titleCase(text) {
  return String(text || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function modeAccent(mode) {
  const value = String(mode || "").toLowerCase();
  if (["class", "study", "focused"].includes(value)) return [0.8, 1.15, 0.85];
  if (["privacy", "presentation", "curious"].includes(value)) return [1.25, 0.85, 0.5];
  if (["break", "entertainment", "playful"].includes(value)) return [1.25, 0.55, 0.6];
  return [0.9, 1.1, 1.15];
}

function modePalette(mode) {
  const value = String(mode || "").toLowerCase();
  const jarvis = modeAccent(mode);
  const ultron = ["privacy", "presentation", "curious"].includes(value)
    ? [1.35, 0.55, 0.18]
    : ["break", "entertainment", "playful"].includes(value)
      ? [1.45, 0.28, 0.22]
      : [1.2, 0.38, 0.28];
  return { jarvis, ultron };
}

function setCommandState(state) {
  commandState.textContent = state;
  commandState.className = "";
  if (state === "Running") commandState.classList.add("is-running");
  else if (state === "Error" || state === "Issue") commandState.classList.add("is-error");
  else if (state === "Complete") commandState.classList.add("is-complete");
}

function showToast(message, type = "info") {
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  toast.className = "toast is-visible";
  if (type === "success") toast.classList.add("is-success");
  else if (type === "error") toast.classList.add("is-error");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("is-visible");
    setTimeout(() => { toast.hidden = true; }, 220);
  }, 4200);
}

function setReadout(el, value, isLive = true) {
  if (!el) return;
  el.textContent = value;
  el.classList.toggle("is-stale", !isLive);
}

function setVoiceHud(state) {
  const s = String(state || "idle").toLowerCase();
  document.body.dataset.voiceState = s;
  if (voiceStatus) voiceStatus.dataset.state = s;
  if (voiceStatusLabel) voiceStatusLabel.textContent = VOICE_LABELS[s] || "Standby";
  if (voiceValue) {
    voiceValue.textContent = VOICE_LABELS[s] || "Standby";
    voiceValue.classList.remove("is-hearing", "is-thinking", "is-speaking", "is-stale");
    if (s === "hearing") voiceValue.classList.add("is-hearing");
    else if (s === "thinking") voiceValue.classList.add("is-thinking");
    else if (s === "speaking") voiceValue.classList.add("is-speaking");
    else voiceValue.classList.add("is-stale");
  }
}

function renderTimeline(events) {
  const source = Array.isArray(events) && events.length ? events : [];
  if (!source.length) {
    timelineList.innerHTML = `<li class="timeline-empty"><time class="tl-time">--:--</time><span class="tl-kind">Status</span><span class="tl-detail">No recent events recorded.</span></li>`;
    return;
  }
  const rows = [];
  for (const event of source.slice(-6).reverse()) {
    const ts = event.at
      ? new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : "--:--";
    rows.push(
      `<li><time class="tl-time">${escapeHtml(ts)}</time><span class="tl-kind">${escapeHtml(event.kind || "Event")}</span><span class="tl-detail">${escapeHtml(event.detail || "")}</span></li>`
    );
  }
  timelineList.innerHTML = rows.join("");
}

async function pollJob(jobId, { interval = 250, timeout = 90000 } = {}) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const response = await fetch(`/api/job/${jobId}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Job poll failed: HTTP ${response.status}`);
    const job = await response.json();
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error("Command timed out waiting for completion.");
}

function formatJobResult(job) {
  const parts = [];
  if (job.message) parts.push(job.message);
  if (job.workflow) parts.push(`Workflow: ${job.workflow}`);
  if (Array.isArray(job.steps) && job.steps.length) {
    parts.push(`${job.steps.length} step(s) completed`);
  }
  if (Array.isArray(job.errors) && job.errors.length) {
    parts.push(`Errors: ${job.errors.join("; ")}`);
  }
  return parts.join(" · ") || "Command finished.";
}

function renderAgentRoster(agentsData) {
  if (!agentsRoster) return;
  const roster = agentsData?.roster || [];
  const active = new Set(agentsData?.active_agents || []);
  const running = (agentsData?.running || 0) > 0;

  if (!roster.length) {
    agentsRoster.innerHTML = '<span class="agents-last-run">Agents offline</span>';
    return;
  }

  agentsRoster.innerHTML = roster
    .map((a) => {
      const id = a.id || "";
      const tier = a.tier === "elite" ? "elite" : "standard";
      const isActive = active.has(id);
      const isSelected = selectedAgentIds.has(id);
      const cls = [
        "agent-chip",
        `agent-chip--${tier}`,
        isActive ? "is-active" : "",
        isSelected ? "is-selected" : "",
      ]
        .filter(Boolean)
        .join(" ");
      return `<button type="button" class="${cls}" data-agent-id="${escapeHtml(id)}" role="listitem" title="${escapeHtml(a.role || "")}">
        <span class="agent-chip__dot" aria-hidden="true"></span>
        <span>${escapeHtml(a.name || id)}</span>
      </button>`;
    })
    .join("");

  agentsRoster.querySelectorAll("[data-agent-id]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const id = chip.dataset.agentId;
      if (selectedAgentIds.has(id)) selectedAgentIds.delete(id);
      else selectedAgentIds.add(id);
      renderAgentRoster(agentsData);
    });
  });

  if (agentsPanelStatus) {
    const n = roster.length;
    agentsPanelStatus.textContent = running
      ? `Deploying (${active.size || agentsData.running})`
      : agentsData?.always_active
        ? `${active.size || n} mini-brains active`
      : `${n} mini-brains ready`;
    agentsPanelStatus.classList.toggle("is-live", running || !!agentsData?.always_active);
  }
}

function renderSchedulerPanel(sched) {
  if (!schedulerJobList) return;
  const jobs = sched?.jobs || [];
  if (schedulerPanelTitle) {
    schedulerPanelTitle.textContent = sched?.running
      ? `${sched.job_count || 0} active`
      : "Offline";
  }
  if (!jobs.length) {
    schedulerJobList.innerHTML =
      '<li class="scheduler-empty">No jobs scheduled</li>';
    return;
  }
  schedulerJobList.innerHTML = jobs
    .slice(0, 8)
    .map((j) => {
      const err = j.last_error ? " is-error" : "";
      return `<li class="${err}">
        <span class="job-name">${escapeHtml(j.name)}</span>
        <span class="job-next">${escapeHtml(j.next_run || j.description || "—")}</span>
      </li>`;
    })
    .join("");
}

function updateAgentsFusion(agentsData) {
  const last = agentsData?.last_run;
  if (!last) return;
  if (agentsFusionTitle) {
    const names = (last.agent_names || []).join(", ");
    agentsFusionTitle.textContent = names ? `Team: ${names}` : "Fusion ready";
    agentsFusionTitle.classList.add("is-live");
  }
  if (agentsFusionPreview && last.answer_preview) {
    agentsFusionPreview.textContent = last.answer_preview;
  }
  if (agentsLastRun) {
    const ms = last.elapsed_ms ? `${Math.round(last.elapsed_ms)}ms` : "";
    agentsLastRun.textContent = `Last deploy: ${(last.agent_names || []).join(", ")} ${ms}`.trim();
  }
}

async function runAgents(task, button) {
  const trimmed = String(task || "").trim();
  if (!trimmed || agentsDeploying) return;

  agentsDeploying = true;
  setCommandState("Agents");
  if (agentsDeployBtn) {
    agentsDeployBtn.disabled = true;
    agentsDeployBtn.classList.add("is-running");
  }
  if (agentsLastRun) agentsLastRun.textContent = "Deploying mini-brains…";
  if (agentsFusionPreview) agentsFusionPreview.textContent = "Team working in parallel…";

  const payload = { task: trimmed };
  if (selectedAgentIds.size) payload.agents = [...selectedAgentIds];

  try {
    const response = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.message || `HTTP ${response.status}`);
    }
    let outcome = result;
    if (result.job_id) outcome = await pollJob(result.job_id, { interval: 400, timeout: 180000 });

    const success = outcome.ok !== false && outcome.status !== "error";
    setCommandState(success ? "Complete" : "Issue");
    const summary = outcome.message || formatJobResult(outcome);
    if (agentsLastRun) agentsLastRun.textContent = summary.slice(0, 280);
    if (agentsFusionPreview) agentsFusionPreview.textContent = summary;
    if (commandLog) {
      commandLog.textContent = outcome.agents
        ? `Agents (${outcome.agents.join(", ")}): ${summary.slice(0, 160)}…`
        : summary.slice(0, 240);
    }
    showToast(success ? "Mini-brains fused an answer" : summary, success ? "success" : "error");
    await refreshStatus();
  } catch (error) {
    setCommandState("Error");
    if (agentsLastRun) agentsLastRun.textContent = error.message;
    showToast(error.message, "error");
  } finally {
    agentsDeploying = false;
    if (agentsDeployBtn) {
      agentsDeployBtn.disabled = false;
      agentsDeployBtn.classList.remove("is-running");
    }
  }
}

async function runCommand(command, button) {
  const trimmed = String(command || "").trim();
  if (!trimmed) return;

  const low = trimmed.toLowerCase();
  if (low.startsWith("use agents ") || low.startsWith("delegate ")) {
    const task = low.startsWith("use agents ")
      ? trimmed.slice(11).trim()
      : trimmed.slice(9).trim();
    return runAgents(task, button);
  }

  setCommandState("Running");
  commandLog.textContent = `You: ${trimmed}`;
  commandLog.classList.remove("is-error");

  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }

  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: trimmed }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.message || `HTTP ${response.status}`);
    }

    let outcome = result;
    if (result.job_id) {
      outcome = await pollJob(result.job_id);
    }

    const success = outcome.ok !== false && outcome.status !== "error";
    setCommandState(success ? "Complete" : "Issue");
    const summary = formatJobResult(outcome);
    commandLog.textContent = `Friday: ${summary}`;
    if (autonomyLine) autonomyLine.textContent = summary.slice(0, 200);
    if (!success) commandLog.classList.add("is-error");
    showToast(success ? "Friday answered" : summary, success ? "success" : "error");
    await refreshStatus();
  } catch (error) {
    setCommandState("Error");
    commandLog.textContent = `Command failed: ${error.message}`;
    commandLog.classList.add("is-error");
    showToast(error.message, "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

async function refreshStatus() {
  connectionLabel.classList.add("is-updating");
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    const autonomy = data.autonomy || {};
    const system = data.system || {};
    const battery = system.battery || {};
    const wifi = system.wifi || {};
    const mode = autonomy.mode || "idle";

    document.body.dataset.mode = mode;
    accentColor = modeAccent(mode);
    if (jarvisScene) jarvisScene.setPalette(modePalette(mode));

    const modeLabel = titleCase(mode);
    modeValue.textContent = modeLabel;
    modeBadge.textContent = modeLabel;
    goalValue.textContent = `Goal: ${autonomy.goal || "Stand by and assist Satvik."}`;
    if (!commandLog || !commandLog.textContent.startsWith("Friday:")) {
      autonomyLine.textContent = `${autonomy.source || "local"} · ${autonomy.updated_at || "unknown"}`;
    }

    setReadout(confidenceValue, `${Math.round((autonomy.confidence || 0) * 100)}%`, true);
    setReadout(sourceValue, autonomy.source || "local", true);
    setReadout(focusValue, system.focus_active ? "Active" : "Idle", true);
    setReadout(classValue, autonomy.class || "Ready", true);
    setReadout(visionValue, data.gesture && data.gesture.running ? (data.gesture.label || "Watching") : "—", !!(data.gesture && data.gesture.running));

    setReadout(
      batteryValue,
      battery.percent >= 0
        ? `${battery.percent}%${battery.plugged ? " ↑" : ""}`
        : "N/A",
      battery.percent >= 0
    );

    setReadout(
      networkValue,
      wifi.connected
        ? `${wifi.ssid || "Connected"}${wifi.signal ? ` (${wifi.signal})` : ""}`
        : system.internet
          ? "Online"
          : "Offline",
      true
    );

    const agents = data.agents || {};
    const agentRunning = (agents.running || 0) > 0;
    const activeN = (agents.active_agents || []).length;
    const agentLabel = agentRunning
      ? `Team (${activeN || agents.running})`
      : agents.always_active
        ? `${activeN || (agents.roster || []).length} active`
      : agents.last_run
        ? `${(agents.roster || []).length} · ${(agents.last_run.agent_names || []).slice(0, 2).join("+")}`
        : agents.enabled
          ? `${(agents.roster || []).length} brains`
          : "Off";
    setReadout(agentsValue, agentLabel, agents.enabled !== false);
    renderAgentRoster(agents);
    updateAgentsFusion(agents);

    setReadout(memoryValue, data.memory_count != null ? String(data.memory_count) : "Active", data.memory_count != null);
    const sched = data.scheduler || {};
    const schedJobs = sched.jobs || [];
    const nextJob = schedJobs.find((j) => j.next_run);
    let schedLabel = sched.running
      ? `${sched.job_count || 0} jobs`
      : "Off";
    if (nextJob) {
      schedLabel = `${sched.job_count} · ${nextJob.name}`;
    } else if (sched.job_count) {
      schedLabel = `${sched.job_count} jobs`;
    }
    setReadout(schedulerValue, schedLabel, sched.running !== false);
    renderSchedulerPanel(sched);
    const vs = (data.voice_state || "idle").toLowerCase();
    setVoiceHud(vs);
    setReadout(screenValue, system.focus_active ? "Focused" : "Idle", true);

    statusConnected = true;
    connectionLabel.textContent = "Local systems online";
    connectionLabel.classList.remove("is-offline");
    connectionLabel.classList.add("is-live");
    systemSummary.textContent = data.system_summary || "System summary unavailable.";
    renderTimeline(data.recent_events || []);
  } catch (error) {
    statusConnected = false;
    connectionLabel.textContent = "Offline or waiting for Friday";
    connectionLabel.classList.add("is-offline");
    autonomyLine.textContent = `Status unavailable: ${error.message}`;
  } finally {
    connectionLabel.classList.remove("is-updating");
  }
}

function refreshClock() {
  const now = new Date();
  timeValue.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function connectEvents() {
  try {
    const es = new EventSource("/api/events");
    es.addEventListener("job_done", () => refreshStatus());
    es.addEventListener("agents.completed", () => refreshStatus());
    es.addEventListener("agent.started", () => refreshStatus());
    es.addEventListener("scheduler.job_done", () => refreshStatus());
    es.addEventListener("scheduler.reminder", () => refreshStatus());
    es.onerror = () => {
      es.close();
      setTimeout(connectEvents, 5000);
    };
  } catch {
    /* SSE unavailable — polling fallback handles updates */
  }
}

function shouldAnimateWebGL() {
  return webglRunning && !document.hidden && !reducedMotion.matches;
}

function compile(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader));
  }
  return shader;
}

function createProgram() {
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl.VERTEX_SHADER, vertexSource));
  gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragmentSource));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program));
  }
  return program;
}

function pushVertex(vertices, x, y, z, r, g, b, a = 1) {
  vertices.push(x, y, z, r, g, b, a);
}

function fibonacciNodes(count, radius, color, spread = 0) {
  const vertices = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / Math.max(count - 1, 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    const jitter = spread * (Math.random() - 0.5);
    const rad = radius + jitter;
    const x = Math.cos(theta) * r * rad;
    const z = Math.sin(theta) * r * rad;
    const yy = y * rad;
    const glow = 0.55 + 0.45 * (1 - Math.abs(yy) / (radius + 0.01));
    pushVertex(vertices, x, yy, z, color[0] * glow, color[1] * glow, color[2] * glow, 0.55 + glow * 0.35);
  }
  return vertices;
}

function buildSynapses(nodeVerts, maxDist, color, maxLinks = 3) {
  const nodes = [];
  for (let i = 0; i < nodeVerts.length; i += 7) {
    nodes.push({ x: nodeVerts[i], y: nodeVerts[i + 1], z: nodeVerts[i + 2] });
  }
  const lines = [];
  const linked = nodes.map(() => 0);
  for (let i = 0; i < nodes.length; i++) {
    const dists = [];
    for (let j = 0; j < nodes.length; j++) {
      if (i === j) continue;
      const dx = nodes[i].x - nodes[j].x;
      const dy = nodes[i].y - nodes[j].y;
      const dz = nodes[i].z - nodes[j].z;
      dists.push({ j, d: Math.sqrt(dx * dx + dy * dy + dz * dz) });
    }
    dists.sort((a, b) => a.d - b.d);
    for (const { j, d } of dists) {
      if (linked[i] >= maxLinks || linked[j] >= maxLinks) continue;
      if (d > maxDist) break;
      const fade = 1 - d / maxDist;
      pushVertex(lines, nodes[i].x, nodes[i].y, nodes[i].z, color[0], color[1], color[2], 0.12 + fade * 0.35);
      pushVertex(lines, nodes[j].x, nodes[j].y, nodes[j].z, color[0], color[1], color[2], 0.08 + fade * 0.28);
      linked[i]++;
      linked[j]++;
    }
  }
  return lines;
}

function sphereMesh(latitude, longitude, radius, color, alpha = 0.35) {
  const vertices = [];
  const indices = [];
  for (let lat = 0; lat <= latitude; lat++) {
    const theta = (lat * Math.PI) / latitude;
    const sinTheta = Math.sin(theta);
    const cosTheta = Math.cos(theta);
    for (let lon = 0; lon <= longitude; lon++) {
      const phi = (lon * 2 * Math.PI) / longitude;
      const x = Math.cos(phi) * sinTheta * radius;
      const y = cosTheta * radius;
      const z = Math.sin(phi) * sinTheta * radius;
      const glow = 0.35 + 0.65 * (1 - Math.abs(y) / (radius + 0.001));
      pushVertex(vertices, x, y, z, color[0] * glow, color[1] * glow, color[2] * glow, alpha * glow);
    }
  }
  for (let lat = 0; lat < latitude; lat++) {
    for (let lon = 0; lon < longitude; lon++) {
      const first = lat * (longitude + 1) + lon;
      const second = first + longitude + 1;
      indices.push(first, second, first + 1, second, second + 1, first + 1);
    }
  }
  return { vertices: new Float32Array(vertices), indices: new Uint16Array(indices) };
}

function offsetVertices(vertices, ox, oy, oz) {
  const out = [];
  for (let i = 0; i < vertices.length; i += 7) {
    pushVertex(out, vertices[i] + ox, vertices[i + 1] + oy, vertices[i + 2] + oz, vertices[i + 3], vertices[i + 4], vertices[i + 5], vertices[i + 6]);
  }
  return out;
}

function ringMesh(radius, segments, color, alpha = 0.55, y = 0) {
  const vertices = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    const pulse = 0.7 + 0.3 * Math.sin(i * 0.35);
    pushVertex(vertices, Math.cos(a) * radius, y, Math.sin(a) * radius, color[0] * pulse, color[1] * pulse, color[2] * pulse, alpha);
  }
  return { vertices: new Float32Array(vertices), count: segments };
}

function helixMesh(turns, points, radius, height, color, alpha = 0.45, phase = 0) {
  const vertices = [];
  for (let i = 0; i < points; i++) {
    const t = i / Math.max(points - 1, 1);
    const angle = t * turns * Math.PI * 2 + phase;
    const y = (t - 0.5) * height;
    const r = radius * (0.85 + 0.15 * Math.sin(t * Math.PI * 4));
    const pulse = 0.65 + 0.35 * Math.sin(t * Math.PI * 8);
    pushVertex(vertices, Math.cos(angle) * r, y, Math.sin(angle) * r, color[0] * pulse, color[1] * pulse, color[2] * pulse, alpha);
  }
  return { vertices: new Float32Array(vertices), count: points };
}

function particleField(count, spread, color) {
  const vertices = [];
  for (let i = 0; i < count; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = spread * (0.35 + Math.random() * 0.65);
    const x = r * Math.sin(phi) * Math.cos(theta);
    const y = r * Math.sin(phi) * Math.sin(theta);
    const z = r * Math.cos(phi);
    const a = 0.15 + Math.random() * 0.35;
    pushVertex(vertices, x, y, z, color[0], color[1], color[2], a);
  }
  return { vertices: new Float32Array(vertices), count };
}

function multiply(a, b) {
  const out = new Float32Array(16);
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 4; c++) {
      out[c * 4 + r] =
        a[0 * 4 + r] * b[c * 4 + 0] +
        a[1 * 4 + r] * b[c * 4 + 1] +
        a[2 * 4 + r] * b[c * 4 + 2] +
        a[3 * 4 + r] * b[c * 4 + 3];
    }
  }
  return out;
}

function identity() {
  return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
}

function translate(x, y, z) {
  const m = identity();
  m[12] = x;
  m[13] = y;
  m[14] = z;
  return m;
}

function rotateX(a) {
  const c = Math.cos(a);
  const s = Math.sin(a);
  return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]);
}

function rotateY(a) {
  const c = Math.cos(a);
  const s = Math.sin(a);
  return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
}

function rotateZ(a) {
  const c = Math.cos(a);
  const s = Math.sin(a);
  return new Float32Array([c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
}

function scale(s) {
  return new Float32Array([s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1]);
}

function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) / (near - far), -1,
    0, 0, (2 * far * near) / (near - far), 0,
  ]);
}

function composeModel(time, { spin = 1, tiltX = 0, tiltY = 0, tiltZ = 0, s = 1, offset = [0, 0, 0] }) {
  let m = multiply(rotateY(time * spin + tiltY), rotateX(tiltX));
  m = multiply(m, rotateZ(tiltZ));
  m = multiply(m, scale(s));
  m = multiply(m, translate(offset[0], offset[1], offset[2]));
  return m;
}

function viewMatrix(time) {
  const breathe = 1 + Math.sin(time * 0.6) * 0.015;
  const cam = multiply(translate(0, 0, -5.4 * breathe), rotateX(0.12 + Math.sin(time * 0.25) * 0.04));
  return multiply(cam, rotateY(time * 0.08));
}

function mesh(data, mode, pointCount = 0) {
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, data.vertices, gl.STATIC_DRAW);
  const item = {
    buffer,
    mode,
    count: pointCount || data.count || (data.indices ? data.indices.length : data.vertices.length / 7),
    stride: 28,
    colorOffset: 12,
    indexBuffer: null,
  };
  if (data.indices) {
    item.indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, item.indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, data.indices, gl.STATIC_DRAW);
  }
  return item;
}

function meshFromArray(vertices, mode) {
  const arr = new Float32Array(vertices);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
  return {
    buffer,
    mode,
    count: vertices.length / 7,
    stride: 28,
    colorOffset: 12,
    indices: null,
    raw: arr,
  };
}

function updateMeshVertices(item, vertices) {
  item.raw = new Float32Array(vertices);
  gl.bindBuffer(gl.ARRAY_BUFFER, item.buffer);
  gl.bufferData(gl.ARRAY_BUFFER, item.raw, gl.DYNAMIC_DRAW);
  item.count = vertices.length / 7;
}

function buildBridgeVerts(time) {
  const bridgeVerts = [];
  const segments = 28;
  for (let i = 0; i < segments; i++) {
    const t = i / (segments - 1);
    const x = -0.95 + t * 1.9;
    const wave = Math.sin(t * Math.PI * 4 + time * 3) * 0.22;
    const z = Math.sin(time * 1.5 + t * 5) * 0.18;
    const jarvisMix = 1 - t;
    const ultronMix = t;
    const r = jarvisMix * 0.2 + ultronMix * 1.0;
    const g = jarvisMix * 0.9 + ultronMix * 0.4;
    const b = jarvisMix * 1.0 + ultronMix * 0.35;
    pushVertex(bridgeVerts, x, wave, z, r, g, b, 0.2 + Math.sin(t * Math.PI) * 0.4);
  }
  return bridgeVerts;
}

function setCanvasSize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.floor(innerWidth * dpr);
  const height = Math.floor(innerHeight * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  gl.viewport(0, 0, canvas.width, canvas.height);
}

function createJarvisScene(gl) {
  const program = createProgram();
  gl.useProgram(program);
  const position = gl.getAttribLocation(program, "position");
  const color = gl.getAttribLocation(program, "color");
  const matrix = gl.getUniformLocation(program, "matrix");
  const accent = gl.getUniformLocation(program, "accent");
  const timeUniform = gl.getUniformLocation(program, "time");
  const pointScale = gl.getUniformLocation(program, "pointScale");

  let palette = modePalette("idle");
  const jarvisBlue = [0.15, 0.85, 1.0];
  const jarvisCore = [0.25, 0.95, 1.0];
  const ultronRed = palette.ultron;

  const jarvisNodes = fibonacciNodes(72, 1.35, jarvisBlue, 0.08);
  const ultronNodes = offsetVertices(fibonacciNodes(48, 1.05, ultronRed, 0.12), -1.65, 0, 0.15);
  const synapses = buildSynapses(jarvisNodes, 0.95, jarvisBlue, 3);
  const ultronSynapses = buildSynapses(ultronNodes, 0.75, ultronRed, 2);

  const layers = {
    coreInner: mesh(sphereMesh(28, 36, 0.42, jarvisCore, 0.55), gl.TRIANGLES),
    coreOuter: mesh(sphereMesh(24, 32, 0.72, jarvisBlue, 0.22), gl.TRIANGLES),
    jarvisNodes: meshFromArray(jarvisNodes, gl.POINTS),
    ultronNodes: meshFromArray(ultronNodes, gl.POINTS),
    synapses: meshFromArray(synapses, gl.LINES),
    ultronSynapses: meshFromArray(ultronSynapses, gl.LINES),
    helixA: mesh(helixMesh(3.2, 220, 1.05, 2.8, jarvisBlue, 0.42, 0), gl.LINE_STRIP),
    helixB: mesh(helixMesh(3.2, 220, 1.05, 2.8, jarvisBlue, 0.38, Math.PI), gl.LINE_STRIP),
    helixC: mesh(helixMesh(2.4, 160, 0.78, 2.2, ultronRed, 0.32, Math.PI * 0.5), gl.LINE_STRIP),
    ringA: mesh(ringMesh(1.95, 200, jarvisBlue, 0.38), gl.LINE_LOOP),
    ringB: mesh(ringMesh(2.35, 180, jarvisBlue, 0.28), gl.LINE_LOOP),
    ringC: mesh(ringMesh(2.72, 160, ultronRed, 0.22), gl.LINE_LOOP),
    particles: mesh(particleField(280, 3.2, jarvisBlue), gl.POINTS),
    bridge: meshFromArray(buildBridgeVerts(0), gl.LINE_STRIP),
  };

  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
  gl.depthMask(false);

  function drawMesh(item, mat, accentColor, time, pointSize = 3.5) {
    gl.bindBuffer(gl.ARRAY_BUFFER, item.buffer);
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 3, gl.FLOAT, false, item.stride, 0);
    gl.enableVertexAttribArray(color);
    gl.vertexAttribPointer(color, 4, gl.FLOAT, false, item.stride, item.colorOffset);
    gl.uniformMatrix4fv(matrix, false, mat);
    gl.uniform3fv(accent, new Float32Array(accentColor));
    gl.uniform1f(timeUniform, time);
    gl.uniform1f(pointScale, pointSize);
    if (item.indexBuffer) {
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, item.indexBuffer);
      gl.drawElements(item.mode, item.count, gl.UNSIGNED_SHORT, 0);
    } else {
      gl.drawArrays(item.mode, 0, item.count);
    }
  }

  function mvp(model, time) {
    const view = viewMatrix(time);
    const proj = perspective(0.78, canvas.width / canvas.height, 0.1, 100);
    return multiply(proj, multiply(view, model));
  }

  return {
    setPalette(mode) {
      palette = modePalette(mode);
    },
    render(time) {
      const pulse = 1 + Math.sin(time * 1.8) * 0.06;
      const clash = 0.5 + 0.5 * Math.sin(time * 0.9);

      gl.clearColor(0.01, 0.025, 0.04, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

      drawMesh(layers.particles, mvp(composeModel(time, { spin: 0.04, s: 1 })), palette.jarvis, time, 2.2);

      drawMesh(
        layers.coreInner,
        mvp(composeModel(time, { spin: 0.22, tiltX: 0.18, s: pulse * 0.95 })),
        palette.jarvis,
        time
      );
      drawMesh(
        layers.coreOuter,
        mvp(composeModel(time, { spin: -0.15, tiltX: -0.12, s: pulse * 1.08 })),
        palette.jarvis,
        time
      );

      drawMesh(
        layers.synapses,
        mvp(composeModel(time, { spin: 0.12, tiltX: 0.22, tiltZ: 0.08 })),
        palette.jarvis,
        time
      );
      drawMesh(
        layers.jarvisNodes,
        mvp(composeModel(time, { spin: 0.12, tiltX: 0.22, tiltZ: 0.08 })),
        palette.jarvis,
        time,
        5.5
      );

      drawMesh(
        layers.helixA,
        mvp(composeModel(time, { spin: 0.18, tiltX: 0.55, s: 1.02 })),
        palette.jarvis,
        time
      );
      drawMesh(
        layers.helixB,
        mvp(composeModel(time, { spin: -0.16, tiltX: -0.48, s: 1.02 })),
        palette.jarvis,
        time
      );

      drawMesh(
        layers.ringA,
        mvp(composeModel(time, { spin: 0.35, tiltX: 1.05, tiltZ: 0.35 })),
        palette.jarvis,
        time
      );
      drawMesh(
        layers.ringB,
        mvp(composeModel(time, { spin: -0.28, tiltX: -0.85, tiltZ: -0.25 })),
        palette.jarvis,
        time
      );

      const ultronOffset = [-1.55 + clash * 0.12, Math.sin(time * 0.7) * 0.08, 0.15];
      const ultronSpin = -0.2 - clash * 0.08;
      drawMesh(
        layers.ultronSynapses,
        mvp(composeModel(time, { spin: ultronSpin, tiltX: 0.35, tiltY: 0.4, offset: ultronOffset, s: 0.92 })),
        palette.ultron,
        time
      );
      drawMesh(
        layers.ultronNodes,
        mvp(composeModel(time, { spin: ultronSpin, tiltX: 0.35, tiltY: 0.4, offset: ultronOffset, s: 0.92 })),
        palette.ultron,
        time,
        4.8
      );
      drawMesh(
        layers.helixC,
        mvp(composeModel(time, { spin: ultronSpin * 1.2, tiltX: 0.62, offset: ultronOffset, s: 0.88 })),
        palette.ultron,
        time
      );
      drawMesh(
        layers.ringC,
        mvp(composeModel(time, { spin: ultronSpin * 0.8, tiltX: 1.2, tiltZ: 0.5, offset: ultronOffset, s: 0.85 })),
        palette.ultron,
        time
      );

      updateMeshVertices(layers.bridge, buildBridgeVerts(time));
      drawMesh(layers.bridge, mvp(identity(), time), [1.0, 0.95, 1.0], time);
    },
  };
}

let jarvisScene = null;

// The neural-core WebGL is decorative: if the context or shaders fail to build
// (e.g. strict ANGLE validation in WebView2), degrade gracefully — never let it
// abort the rest of the UI (command box, status polling, timeline).
try {
  if (!gl) throw new Error("no webgl context");
  jarvisScene = createJarvisScene(gl);
} catch (err) {
  jarvisScene = null;
  document.body.classList.add("no-webgl");
  console.warn("[FRIDAY] neural-core WebGL disabled:", err && err.message);
}

if (jarvisScene) {
  const render = (ms) => {
    if (!shouldAnimateWebGL()) {
      requestAnimationFrame(render);
      return;
    }
    setCanvasSize();
    try {
      jarvisScene.render(ms * 0.001);
    } catch (err) {
      console.warn("[FRIDAY] neural-core render stopped:", err && err.message);
      return;                              // stop the loop; UI keeps working
    }
    requestAnimationFrame(render);
  };

  document.addEventListener("visibilitychange", () => {
    webglRunning = !document.hidden;
  });

  reducedMotion.addEventListener("change", () => {
    webglRunning = !reducedMotion.matches;
  });

  webglRunning = !reducedMotion.matches;
  requestAnimationFrame(render);
}

commandButtons.forEach((button) => {
  button.addEventListener("click", () => runCommand(button.dataset.command, button));
});

if (commandForm && commandInput) {
  commandForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const command = commandInput.value;
    commandInput.value = "";
    runCommand(command, document.getElementById("command-submit"));
  });
}

if (agentsForm && agentsTaskInput) {
  agentsForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const task = agentsTaskInput.value;
    agentsTaskInput.value = "";
    runAgents(task, agentsDeployBtn);
  });
}

agentsQuickButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const task = btn.dataset.agentsTask || "";
    if (agentsTaskInput) agentsTaskInput.value = task;
    runAgents(task, agentsDeployBtn);
  });
});

document.addEventListener("keydown", (event) => {
  if (event.target === commandInput) return;
  const idx = parseInt(event.key, 10);
  if (idx >= 1 && idx <= 6 && commandButtons[idx - 1]) {
    event.preventDefault();
    runCommand(commandButtons[idx - 1].dataset.command, commandButtons[idx - 1]);
  }
});

// ── Gesture control overlay (centre of the neural core) ───────────────────────
(function setupGesture() {
  const toggle = document.getElementById("gesture-toggle");
  const stage = document.getElementById("gesture-stage");
  const feed = document.getElementById("gesture-feed");
  const label = document.getElementById("gesture-label");
  if (!toggle || !stage || !feed) return;
  let live = false;
  let labelTimer = null;

  async function start() {
    try {
      const r = await fetch("/gesture/start", { method: "POST" });
      const d = await r.json();
      if (!d.ok) {
        showToast(d.message || "Gesture control unavailable", "error");
        return;
      }
      live = true;
      toggle.classList.add("is-live");
      toggle.textContent = "Gesture ⏹";
      stage.hidden = false;
      feed.src = "/gesture/stream?ts=" + Date.now();
      showToast("Gesture control online — fist · open hand · call-me", "success");
      pollLabel();
    } catch (e) {
      showToast("Gesture start failed: " + e.message, "error");
    }
  }

  async function stop() {
    live = false;
    toggle.classList.remove("is-live");
    toggle.textContent = "Gesture";
    stage.hidden = true;
    feed.src = "";
    if (labelTimer) { clearTimeout(labelTimer); labelTimer = null; }
    try { await fetch("/gesture/stop", { method: "POST" }); } catch {}
  }

  async function pollLabel() {
    if (!live) return;
    try {
      const r = await fetch("/gesture/status", { cache: "no-store" });
      const d = await r.json();
      if (label) label.textContent = d.label || "Watching";
      if (!d.running) { stop(); return; }
    } catch {}
    labelTimer = setTimeout(pollLabel, 600);
  }

  toggle.addEventListener("click", () => (live ? stop() : start()));
})();

connectEvents();
refreshStatus();
refreshClock();
setInterval(refreshStatus, statusConnected ? 2000 : 1200);
setInterval(refreshClock, 1000);
