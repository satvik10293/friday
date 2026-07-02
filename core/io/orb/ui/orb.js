/* =====================================================================
 * FRIDAY Orb UI — orb.js
 *
 * A self-contained, purely-reactive front-end for FRIDAY's floating orb.
 * Runs inside a frameless pywebview window (Edge WebView2). No build step,
 * no framework, no network. The orb NEVER contains AI logic — it only
 * visualises what FRIDAY sends and reports interactions back to Python.
 *
 * The "4D" orb is ported from the reference OrbApp.tsx:
 *   - SVG feTurbulence displacement (organic surface projection)
 *   - stacked CSS 3D perspective rings (parallax depth)
 *   - radial-gradient sphere with specular highlight + Fresnel rim
 *   - per-frame requestAnimationFrame animation for all state motion
 *
 * FROZEN CONTRACT — window.FRIDAY (called by Python via evaluate_js):
 *   FRIDAY.setState(state)      one of the 9 states
 *   FRIDAY.setEmotion(emotion)  neutral|happy|curious|concerned|focused
 *   FRIDAY.showSpeech(text)     show glass speech panel (typewriter reveal)
 *   FRIDAY.hideSpeech()         fade the speech panel out and clear it
 *   FRIDAY.setAmplitude(v)      v in [0,1] real audio amplitude
 *   FRIDAY.setMode(mode)        voice|text
 *   FRIDAY.notify(kind, glow)   brief coloured glow, then return to prior state
 *   FRIDAY.openDashboard()      show dashboard overlay
 *   FRIDAY.closeDashboard()     hide dashboard overlay
 *   FRIDAY.bootstrap(obj)       apply initial {state,mode,emotion,dashboard_open,
 *                               always_on_top,config}
 *
 * Interactions -> window.pywebview.api (guarded; no-op if unavailable):
 *   single click  -> api.wake()
 *   double click  -> api.toggle_dashboard()
 *   right click   -> quick menu -> api.command('settings'|'diagnostics'|
 *                    'plugins'|'restart'|'exit')
 *   drag body     -> api.move(x, y)  (frameless window move via screen deltas)
 *   on load       -> api.ready() (Promise) -> FRIDAY.bootstrap(obj)
 * ===================================================================== */

(function () {
  "use strict";

  // ── Full 9-state config (ported from stateConfig.ts, exact colours) ──────────
  //   color = cssColor (accent / rim / rings)   dim = cssDim (outermost)
  //   core  = colorCore (sphere body)           glow = colorEmit (deep emission)
  var STATE_CONFIG = {
    idle:      { label: "Idle",      emoji: "😴", color: "#4f80ff", core: "#1f388c", glow: "#0d1f61", dim: "#04091f", vib: 0, pulse: 0, spin: 5,   breathAmp: 0.035, breathFreq: 0.8, sleep: 0 },
    listening: { label: "Listening", emoji: "🎙️", color: "#22d3ee", core: "#05b8e6", glow: "#03598c", dim: "#00131a", vib: 0, pulse: 0, spin: 12,  breathAmp: 0.030, breathFreq: 1.2, sleep: 0 },
    thinking:  { label: "Thinking",  emoji: "🤔", color: "#a78bfa", core: "#6b2ef2", glow: "#330f80", dim: "#110620", vib: 0, pulse: 0, spin: 35,  breathAmp: 0.015, breathFreq: 1.8, sleep: 0 },
    speaking:  { label: "Speaking",  emoji: "🗣️", color: "#34d399", core: "#0dd98c", glow: "#036640", dim: "#001610", vib: 1, pulse: 0, spin: 28,  breathAmp: 0.008, breathFreq: 2.5, sleep: 0 },
    happy:     { label: "Happy",     emoji: "😊", color: "#60a5fa", core: "#1a6bff", glow: "#0a2e94", dim: "#040f2e", vib: 0, pulse: 0, spin: 18,  breathAmp: 0.028, breathFreq: 1.5, sleep: 0 },
    warning:   { label: "Warning",   emoji: "⚠️", color: "#fbbf24", core: "#f29905", glow: "#8c4703", dim: "#1e1000", vib: 0, pulse: 1, spin: 10,  breathAmp: 0.045, breathFreq: 2.0, sleep: 0 },
    error:     { label: "Error",     emoji: "❌", color: "#f87171", core: "#eb2424", glow: "#800a0a", dim: "#1e0202", vib: 0, pulse: 1, spin: 8,   breathAmp: 0.040, breathFreq: 2.2, sleep: 0 },
    offline:   { label: "Offline",   emoji: "⚫", color: "#4b5563", core: "#1a1a1f", glow: "#0d0d0f", dim: "#080808", vib: 0, pulse: 0, spin: 2,   breathAmp: 0.008, breathFreq: 0.4, sleep: 0.6 },
    sleeping:  { label: "Sleeping",  emoji: "💤", color: "#334155", core: "#0f1a38", glow: "#050a1a", dim: "#03050f", vib: 0, pulse: 0, spin: 1.5, breathAmp: 0.012, breathFreq: 0.3, sleep: 0.8 },
  };

  var VALID_STATES = Object.keys(STATE_CONFIG);

  // Emotion overlays — subtle screen-blended tints on top of the sphere.
  var EMOTION_OVERLAY = {
    neutral:   { color: "transparent", opacity: 0.0 },
    happy:     { color: "#ffd27f",     opacity: 0.16 },
    curious:   { color: "#7fe9ff",     opacity: 0.15 },
    concerned: { color: "#ff9b7f",     opacity: 0.16 },
    focused:   { color: "#9d8bff",     opacity: 0.15 },
  };
  var VALID_EMOTIONS = Object.keys(EMOTION_OVERLAY);

  var CONTEXT_ITEMS = [
    { cmd: "settings",    icon: "⚙️", label: "Settings",       opensDashboard: true },
    { cmd: "diagnostics", icon: "🔬", label: "Diagnostics",    opensDashboard: true },
    { cmd: "plugins",     icon: "🧩", label: "Plugins",        opensDashboard: true, divider: true },
    { cmd: "restart",     icon: "🔄", label: "Restart FRIDAY" },
    { cmd: "exit",        icon: "✕",       label: "Exit",           danger: true },
  ];

  var DASH_TABS = [
    { id: "conversation", icon: "💬", label: "Conversation",    title: "Conversation History", desc: "Full conversation thread with FRIDAY will appear here.", status: "Connected" },
    { id: "memory",       icon: "🧠", label: "Memory",          title: "Memory Store",         desc: "FRIDAY's long-term episodic and semantic memories.",    status: "Ready" },
    { id: "brains",       icon: "⚡",       label: "Brains",          title: "Active Brains",        desc: "Loaded reasoning modules and their current states.",    status: "Idle" },
    { id: "knowledge",    icon: "🌐", label: "Knowledge Graph", title: "Knowledge Graph",      desc: "Entity and relationship graph powered by FRIDAY.",      status: "Synced" },
    { id: "plugins",      icon: "🧩", label: "Plugins",         title: "Plugin Registry",      desc: "Installed FRIDAY plugins and their permissions.",       status: "Loaded" },
    { id: "diagnostics",  icon: "🔬", label: "Diagnostics",     title: "Diagnostics",          desc: "Runtime health, model latency, memory usage.",          status: "All green" },
    { id: "settings",     icon: "⚙️", label: "Settings",        title: "Configuration",        desc: "FRIDAY runtime and UI configuration.",                  status: "Default" },
    { id: "health",       icon: "💚", label: "System Health",   title: "System Health",        desc: "CPU, RAM, temperature, and inference metrics.",         status: "Healthy" },
    { id: "logs",         icon: "📋", label: "Logs",            title: "Log Stream",           desc: "Live structured logs from FRIDAY runtime.",             status: "Streaming" },
  ];

  // ── Runtime state ────────────────────────────────────────────────────────────
  var currentState = "idle";
  var currentEmotion = "neutral";
  var currentMode = "voice";
  var dashboardOpen = false;
  var activeTab = "conversation";

  var targetAudio = 0;   // last value from FRIDAY.setAmplitude()
  var audioNow = 0;      // smoothed
  var speechEnabled = true;
  var animationQuality = "high";

  // notification flash
  var flashColor = null;
  var flashStart = 0;
  var flashDur = 1200;

  // typewriter
  var typeTimer = null;
  var fullSpeechText = "";

  // DOM refs (filled on DOMContentLoaded)
  var el = {};

  // ── Tiny internal event bus (optional, for internal wiring) ──────────────────
  var listeners = {};
  function on(evt, cb) {
    (listeners[evt] || (listeners[evt] = [])).push(cb);
    return function () { off(evt, cb); };
  }
  function off(evt, cb) {
    if (listeners[evt]) listeners[evt] = listeners[evt].filter(function (l) { return l !== cb; });
  }
  function emit(evt, payload) {
    (listeners[evt] || []).forEach(function (l) { try { l(payload); } catch (e) {} });
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────
  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  function withAlpha(hex, a) {
    var n = Math.round(clamp(a, 0, 1) * 255).toString(16);
    if (n.length < 2) n = "0" + n;
    return hex + n;
  }

  // pywebview api call — always guarded; no-ops in dev / before injection.
  function api(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[method] === "function") {
        return window.pywebview.api[method].apply(window.pywebview.api, args);
      }
    } catch (e) { /* no-op */ }
    return undefined;
  }
  function apiAvailable() {
    return !!(window.pywebview && window.pywebview.api);
  }

  // ── Per-state colour application (not per-frame) ─────────────────────────────
  function applyStateColors(cfg) {
    var root = document.documentElement.style;
    root.setProperty("--accent", cfg.color);
    root.setProperty("--core", cfg.core);
    root.setProperty("--glow", cfg.glow);
    root.setProperty("--dim", cfg.dim);

    if (el.sphere) {
      el.sphere.style.background =
        "radial-gradient(circle at 34% 30%," +
        "rgba(255,255,255,0.62) 0%," +
        "rgba(255,255,255,0.15) 8%," +
        cfg.core + " 28%," +
        cfg.glow + " 62%," +
        cfg.dim + " 100%)";
    }
    if (el.glow) el.glow.style.background = cfg.glow;
    if (el.halo) el.halo.style.background = cfg.dim;

    if (el.ring1) {
      el.ring1.style.borderColor = withAlpha(cfg.color, 0.33);
      el.ring1.style.boxShadow = "0 0 10px 1px " + withAlpha(cfg.color, 0.20);
    }
    if (el.ring2) el.ring2.style.borderColor = withAlpha(cfg.color, 0.23);
    if (el.ring3) el.ring3.style.borderColor = withAlpha(cfg.color, 0.16);

    // badge
    if (el.badgeEmoji) el.badgeEmoji.textContent = cfg.emoji;
    if (el.badgeLabel) el.badgeLabel.textContent = cfg.label;
    if (el.badge) el.badge.style.borderColor = withAlpha(cfg.color, 0.20);
  }

  // ── The animation loop (ported from OrbApp.tsx tick) ─────────────────────────
  var t = 0;
  var scaleNow = 1.0;
  var glowNow = 70;
  var dispNow = 20;

  function tick() {
    t += 0.007;
    var cfg = STATE_CONFIG[currentState] || STATE_CONFIG.idle;

    // smooth the amplitude for a fluid "speaking" response
    audioNow += (targetAudio - audioNow) * 0.18;
    var a = audioNow;

    var sleepFactor = 1 - cfg.sleep * 0.55; // dimmer / calmer when asleep

    // ── 4D SVG turbulence (skipped on low animation quality) ─────────────
    if (animationQuality !== "low") {
      var bf1x = 0.30 + Math.sin(t * 0.65) * 0.10;
      var bf1y = 0.30 + Math.cos(t * 0.48) * 0.10;
      if (el.tb1) {
        el.tb1.setAttribute("baseFrequency", bf1x.toFixed(4) + " " + bf1y.toFixed(4));
        el.tb1.setAttribute("seed", (Math.sin(t * 0.28) * 60 + 70).toFixed(2));
      }
      var bf2x = 0.50 + Math.cos(t * 1.05) * 0.14;
      var bf2y = 0.50 + Math.sin(t * 0.80) * 0.14;
      if (el.tb2) {
        el.tb2.setAttribute("baseFrequency", bf2x.toFixed(4) + " " + bf2y.toFixed(4));
        el.tb2.setAttribute("seed", (Math.cos(t * 0.50) * 90 + 120).toFixed(2));
      }
      var targetDisp =
        cfg.vib > 0 ? 28 + a * 32 + Math.sin(t * 20) * a * 12
      : cfg.pulse > 0 ? 24 + Math.sin(t * 4.5) * 9
      : currentState === "thinking" ? 16 + Math.sin(t * 0.6) * 5
      : 18 + Math.sin(t * 0.8) * 4;
      dispNow += (targetDisp - dispNow) * 0.08;
      if (el.disp) el.disp.setAttribute("scale", dispNow.toFixed(2));
    }

    // ── Orb breathing / speaking scale ───────────────────────────────────
    var targetScale =
      cfg.vib > 0
        ? 1 + a * 0.14 + Math.sin(t * 20) * a * 0.05
      : cfg.pulse > 0
        ? 1 + cfg.breathAmp + Math.sin(t * 4.2) * cfg.breathAmp * 0.8
        : 1 + cfg.breathAmp * Math.sin(t * cfg.breathFreq);
    scaleNow += (targetScale - scaleNow) * 0.07;
    if (el.wrap) el.wrap.style.transform = "scale(" + scaleNow.toFixed(4) + ")";

    // ── Glow ─────────────────────────────────────────────────────────────
    var targetGlow =
      cfg.vib > 0 ? 80 + a * 80 + Math.sin(t * 20) * a * 18
    : cfg.pulse > 0 ? 70 + Math.sin(t * 4.5) * 24
    : 55 + Math.sin(t * 1.1) * 8;
    targetGlow *= sleepFactor;
    glowNow += (targetGlow - glowNow) * 0.06;
    if (el.glow) {
      el.glow.style.boxShadow =
        "0 0 " + glowNow.toFixed(0) + "px " + (glowNow * 0.55).toFixed(0) + "px " + cfg.glow;
    }

    // ── Fresnel rim ──────────────────────────────────────────────────────
    var rimAlpha =
      cfg.vib > 0 ? 0.5 + a * 0.4
    : cfg.pulse > 0 ? 0.3 + Math.sin(t * 4.5) * 0.2
    : 0.18;
    rimAlpha *= sleepFactor;
    if (el.rim) {
      el.rim.style.boxShadow =
        "0 0 0 2px " + withAlpha(cfg.color, rimAlpha) + ", " +
        "0 0 28px 4px " + withAlpha(cfg.color, rimAlpha * 0.45);
    }

    // ── CSS 3D rings ─────────────────────────────────────────────────────
    var deg = t * cfg.spin;
    if (el.ring1) el.ring1.style.transform = "rotateX(70deg) rotateZ(" + deg + "deg)";
    if (el.ring2) el.ring2.style.transform = "rotateX(22deg) rotateY(" + (deg * 0.68) + "deg) rotateZ(" + (deg * 0.42) + "deg)";
    if (el.ring3) el.ring3.style.transform = "rotateX(48deg) rotateY(" + (-deg * 0.52) + "deg) rotateZ(" + (deg * 1.08) + "deg)";

    // ── Wide ambient halo ────────────────────────────────────────────────
    if (el.halo) {
      var haloSize = (cfg.vib > 0 ? 120 + a * 80 : cfg.pulse > 0 ? 100 + Math.sin(t * 4) * 20 : 90) * sleepFactor;
      el.halo.style.boxShadow = "0 0 " + haloSize.toFixed(0) + "px " + (haloSize * 0.7).toFixed(0) + "px " + cfg.dim;
    }

    // ── Notification flash (transient; does not change state) ────────────
    if (flashColor && el.flash) {
      var elapsed = performance.now() - flashStart;
      if (elapsed >= flashDur) {
        flashColor = null;
        el.flash.style.opacity = "0";
        el.flash.style.boxShadow = "none";
      } else {
        var p = elapsed / flashDur;                 // 0..1
        var env = Math.sin(p * Math.PI);            // rise then fall
        var pulseWave = 0.6 + 0.4 * Math.sin(elapsed * 0.02);
        var intensity = env * pulseWave;
        el.flash.style.opacity = (0.85 * env).toFixed(3);
        el.flash.style.boxShadow =
          "0 0 " + (60 + 90 * intensity).toFixed(0) + "px " +
          (30 + 50 * intensity).toFixed(0) + "px " + flashColor;
        el.flash.style.background =
          "radial-gradient(circle, " + withAlpha(flashColor, 0.18 * env) + " 0%, transparent 72%)";
      }
    }

    requestAnimationFrame(tick);
  }

  // ── Contract: window.FRIDAY ──────────────────────────────────────────────────
  function setState(state) {
    if (VALID_STATES.indexOf(state) === -1) return;
    currentState = state;
    applyStateColors(STATE_CONFIG[state]);
    // Speech panel shows ONLY while speaking.
    if (state !== "speaking") hideSpeech();
    emit("stateChange", state);
  }

  function setEmotion(emotion) {
    if (VALID_EMOTIONS.indexOf(emotion) === -1) emotion = "neutral";
    currentEmotion = emotion;
    var ov = EMOTION_OVERLAY[emotion];
    if (el.emotion) {
      el.emotion.style.background =
        emotion === "neutral"
          ? "none"
          : "radial-gradient(circle at 40% 35%, " + ov.color + " 0%, transparent 70%)";
      el.emotion.style.opacity = String(ov.opacity);
    }
    emit("emotionChange", emotion);
  }

  function showSpeech(text) {
    if (!speechEnabled) return;
    text = text == null ? "" : String(text);
    fullSpeechText = text;
    if (el.speech) el.speech.classList.add("visible");
    // progressive typewriter reveal
    if (typeTimer) { clearInterval(typeTimer); typeTimer = null; }
    var i = 0;
    renderSpeech("", true);
    typeTimer = setInterval(function () {
      i++;
      renderSpeech(fullSpeechText.slice(0, i), i < fullSpeechText.length);
      if (i >= fullSpeechText.length) { clearInterval(typeTimer); typeTimer = null; }
    }, 22);
    emit("speechShow", text);
  }

  function renderSpeech(shown, showCaret) {
    if (!el.speechText) return;
    el.speechText.textContent = shown;
    if (showCaret) {
      var caret = document.createElement("span");
      caret.className = "caret";
      el.speechText.appendChild(caret);
    }
  }

  function hideSpeech() {
    if (typeTimer) { clearInterval(typeTimer); typeTimer = null; }
    if (el.speech) el.speech.classList.remove("visible");
    fullSpeechText = "";
    if (el.speechText) el.speechText.textContent = "";
    // auto-return the badge to the current state
    applyStateColors(STATE_CONFIG[currentState] || STATE_CONFIG.idle);
    emit("speechHide");
  }

  function setAmplitude(v) {
    var n = Number(v);
    if (isNaN(n)) n = 0;
    targetAudio = clamp(n, 0, 1);
    emit("amplitudeChange", targetAudio);
  }

  function setMode(mode) {
    if (mode !== "voice" && mode !== "text") return;
    currentMode = mode;
    if (el.mode) el.mode.classList.toggle("mode-text", mode === "text");
    if (el.modeIcon) el.modeIcon.innerHTML = mode === "voice" ? "🎙️" : "⌨️";
    if (el.modeLabel) el.modeLabel.textContent = mode === "voice" ? "VOICE" : "TEXT";
    emit("modeChange", mode);
  }

  function notify(kind, glow) {
    // A brief coloured glow/pulse of the orb, then return to the prior state.
    // The state itself is never changed here.
    flashColor = (typeof glow === "string" && glow) ? glow : "#4f80ff";
    flashStart = performance.now();
    flashDur = (kind === "error" || kind === "warning") ? 1700 : 1200;
    emit("notify", { kind: kind, glow: flashColor });
  }

  function openDashboard() {
    dashboardOpen = true;
    if (el.dashboard) el.dashboard.hidden = false;
    emit("dashboardOpen");
  }

  function closeDashboard() {
    dashboardOpen = false;
    if (el.dashboard) el.dashboard.hidden = true;
    emit("dashboardClose");
  }

  function bootstrap(obj) {
    obj = obj || {};
    var cfg = obj.config || {};
    if (typeof cfg.speech_panel_enabled === "boolean") speechEnabled = cfg.speech_panel_enabled;
    if (typeof cfg.animation_quality === "string") animationQuality = cfg.animation_quality;
    if (animationQuality === "low" && el.sphere) el.sphere.style.filter = "none";

    setMode(obj.mode === "text" ? "text" : "voice");
    setEmotion(obj.emotion || "neutral");
    setState(VALID_STATES.indexOf(obj.state) !== -1 ? obj.state : "idle");

    if (obj.dashboard_open) openDashboard(); else closeDashboard();
    emit("bootstrap", obj);
  }

  var FRIDAY = {
    setState: setState,
    setEmotion: setEmotion,
    showSpeech: showSpeech,
    hideSpeech: hideSpeech,
    setAmplitude: setAmplitude,
    setMode: setMode,
    notify: notify,
    openDashboard: openDashboard,
    closeDashboard: closeDashboard,
    bootstrap: bootstrap,
    on: on,
    off: off,
  };
  window.FRIDAY = FRIDAY;

  // ── Dashboard building ───────────────────────────────────────────────────────
  function buildDashboard() {
    if (!el.dashboard) return;
    var navButtons = DASH_TABS.map(function (tb) {
      return '<button class="dash-tab" data-tab="' + tb.id + '">' +
        '<span class="dash-tab-icon">' + tb.icon + '</span>' + tb.label + "</button>";
    }).join("");

    var cards = "";
    for (var i = 0; i < 6; i++) cards += '<div class="dash-card"><div class="bar1"></div><div class="bar2"></div></div>';

    el.dashboard.innerHTML =
      '<div class="dash-panel">' +
        '<div class="dash-side">' +
          '<div class="dash-logo">' +
            '<div class="dash-logo-orb"></div>' +
            '<div><div class="dash-logo-title">FRIDAY</div>' +
            '<div class="dash-logo-sub">v3 &middot; Dashboard</div></div>' +
          "</div>" +
          '<nav class="dash-nav">' + navButtons + "</nav>" +
          '<div class="dash-close-wrap">' +
            '<button class="dash-close" id="dash-close-btn">✕ Close Dashboard</button>' +
          "</div>" +
        "</div>" +
        '<div class="dash-content">' +
          '<div class="dash-head">' +
            '<div class="dash-head-row">' +
              '<h2 class="dash-title" id="dash-title"></h2>' +
              '<span class="dash-status" id="dash-status"></span>' +
            "</div>" +
            '<p class="dash-desc" id="dash-desc"></p>' +
          "</div>" +
          '<div class="dash-grid">' + cards + "</div>" +
        "</div>" +
      "</div>";

    // wire tab clicks
    var tabs = el.dashboard.querySelectorAll(".dash-tab");
    Array.prototype.forEach.call(tabs, function (btn) {
      btn.addEventListener("click", function () { selectTab(btn.getAttribute("data-tab")); });
    });
    // backdrop click closes
    el.dashboard.addEventListener("mousedown", function (e) {
      if (e.target === el.dashboard) requestCloseDashboard();
    });
    var closeBtn = el.dashboard.querySelector("#dash-close-btn");
    if (closeBtn) closeBtn.addEventListener("click", requestCloseDashboard);

    selectTab(activeTab);
  }

  function selectTab(id) {
    var tb = null;
    for (var i = 0; i < DASH_TABS.length; i++) if (DASH_TABS[i].id === id) { tb = DASH_TABS[i]; break; }
    if (!tb) tb = DASH_TABS[0];
    activeTab = tb.id;
    var buttons = el.dashboard.querySelectorAll(".dash-tab");
    Array.prototype.forEach.call(buttons, function (b) {
      b.classList.toggle("active", b.getAttribute("data-tab") === tb.id);
    });
    var t1 = el.dashboard.querySelector("#dash-title");
    var s1 = el.dashboard.querySelector("#dash-status");
    var d1 = el.dashboard.querySelector("#dash-desc");
    if (t1) t1.textContent = tb.title;
    if (s1) s1.textContent = tb.status;
    if (d1) d1.textContent = tb.desc;
  }

  // Dashboard open/close intents (keep Python in sync; work standalone in dev).
  function requestCloseDashboard() {
    closeDashboard();
    if (apiAvailable()) api("toggle_dashboard");
  }
  function requestOpenDashboard() {
    if (!dashboardOpen) openDashboard();
  }
  function requestToggleDashboard() {
    if (apiAvailable()) {
      api("toggle_dashboard");   // Python is the source of truth; it calls back
    } else {
      if (dashboardOpen) closeDashboard(); else openDashboard();  // dev fallback
    }
  }

  // ── Context menu ─────────────────────────────────────────────────────────────
  function buildContextMenu() {
    if (!el.ctx) return;
    var html = "";
    CONTEXT_ITEMS.forEach(function (it) {
      if (it.divider) html += '<div class="ctx-divider"></div>';
      html += '<button class="ctx-item' + (it.danger ? " danger" : "") + '" data-cmd="' + it.cmd + '">' +
        '<span class="ctx-icon">' + it.icon + "</span>" + it.label + "</button>";
    });
    el.ctx.innerHTML = html;
    var items = el.ctx.querySelectorAll(".ctx-item");
    Array.prototype.forEach.call(items, function (btn) {
      btn.addEventListener("click", function () {
        var cmd = btn.getAttribute("data-cmd");
        var spec = null;
        for (var i = 0; i < CONTEXT_ITEMS.length; i++) if (CONTEXT_ITEMS[i].cmd === cmd) { spec = CONTEXT_ITEMS[i]; break; }
        if (spec && spec.opensDashboard) requestOpenDashboard();
        api("command", cmd);
        hideContextMenu();
      });
    });
  }

  function showContextMenu(x, y) {
    if (!el.ctx) return;
    el.ctx.hidden = false;
    var vw = window.innerWidth, vh = window.innerHeight;
    var rect = el.ctx.getBoundingClientRect();
    var cx = Math.min(x, vw - rect.width - 8);
    var cy = Math.min(y, vh - rect.height - 8);
    el.ctx.style.left = Math.max(8, cx) + "px";
    el.ctx.style.top = Math.max(8, cy) + "px";
  }
  function hideContextMenu() { if (el.ctx) el.ctx.hidden = true; }

  // ── Orb click handling (single vs double) ────────────────────────────────────
  var lastClickTime = 0;
  var singleTimer = null;
  var DOUBLE_MS = 280;

  function onOrbClick() {
    if (didDrag) return;                 // a drag isn't a click
    var now = performance.now();
    if (now - lastClickTime < DOUBLE_MS) {
      // double click
      if (singleTimer) { clearTimeout(singleTimer); singleTimer = null; }
      lastClickTime = 0;
      requestToggleDashboard();
    } else {
      lastClickTime = now;
      if (singleTimer) clearTimeout(singleTimer);
      singleTimer = setTimeout(function () {
        singleTimer = null;
        api("wake");                     // single click -> wake
      }, DOUBLE_MS);
    }
  }

  // ── Frameless window drag (whole background) ─────────────────────────────────
  var dragging = false;
  var didDrag = false;
  var pressing = false;
  var lastScreenX = 0, lastScreenY = 0;
  var winX = 0, winY = 0;
  var DRAG_THRESHOLD = 4;

  function onMouseDown(e) {
    if (e.button !== 0) return;
    // Ignore drags that start inside overlays / menus.
    if (el.dashboard && !el.dashboard.hidden && el.dashboard.contains(e.target)) return;
    if (el.ctx && !el.ctx.hidden && el.ctx.contains(e.target)) return;
    pressing = true;
    didDrag = false;
    dragging = false;
    lastScreenX = e.screenX;
    lastScreenY = e.screenY;
    // seed window top-left from the current window screen position
    winX = (typeof window.screenX === "number" ? window.screenX : 0);
    winY = (typeof window.screenY === "number" ? window.screenY : 0);
  }

  function onMouseMove(e) {
    if (!pressing) return;
    var dx = e.screenX - lastScreenX;
    var dy = e.screenY - lastScreenY;
    if (!dragging && (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)) {
      dragging = true;
      didDrag = true;
    }
    if (dragging) {
      winX += dx;
      winY += dy;
      lastScreenX = e.screenX;
      lastScreenY = e.screenY;
      api("move", Math.round(winX), Math.round(winY));
    }
  }

  function onMouseUp() {
    if (dragging) {
      // persist final position on drag end
      api("move", Math.round(winX), Math.round(winY));
    }
    pressing = false;
    dragging = false;
    // didDrag stays true until the orb click handler consumes it, then resets:
    setTimeout(function () { didDrag = false; }, 0);
  }

  // ── Wiring ───────────────────────────────────────────────────────────────────
  function cacheRefs() {
    el.orb = document.getElementById("orb");
    el.wrap = document.getElementById("orb-wrap");
    el.halo = document.getElementById("halo");
    el.glow = document.getElementById("glow");
    el.sphere = document.getElementById("sphere");
    el.rim = document.getElementById("rim");
    el.emotion = document.getElementById("emotion");
    el.ring1 = document.getElementById("ring1");
    el.ring2 = document.getElementById("ring2");
    el.ring3 = document.getElementById("ring3");
    el.flash = document.getElementById("flash");
    el.tb1 = document.getElementById("tb1");
    el.tb2 = document.getElementById("tb2");
    el.disp = document.getElementById("disp");
    el.badge = document.getElementById("badge");
    el.badgeEmoji = document.getElementById("badge-emoji");
    el.badgeLabel = document.getElementById("badge-label");
    el.speech = document.getElementById("speech");
    el.speechText = document.getElementById("speech-text");
    el.mode = document.getElementById("mode");
    el.modeIcon = document.getElementById("mode-icon");
    el.modeLabel = document.getElementById("mode-label");
    el.ctx = document.getElementById("context-menu");
    el.dashboard = document.getElementById("dashboard");
  }

  function wireEvents() {
    // Orb click (single/double).
    if (el.orb) el.orb.addEventListener("click", onOrbClick);

    // Right-click quick menu (anywhere).
    document.addEventListener("contextmenu", function (e) {
      e.preventDefault();
      showContextMenu(e.clientX, e.clientY);
    });

    // Dismiss context menu on outside click / Esc / scroll.
    document.addEventListener("mousedown", function (e) {
      if (el.ctx && !el.ctx.hidden && !el.ctx.contains(e.target)) hideContextMenu();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { hideContextMenu(); }
    });

    // Window drag (whole background, frameless).
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);

    // Native browsers: prevent image/text drag artefacts.
    document.addEventListener("dragstart", function (e) { e.preventDefault(); });
  }

  // ── Startup: ask Python for the bootstrap object ─────────────────────────────
  var bootstrapped = false;
  function requestBootstrap() {
    if (bootstrapped) return;
    if (!apiAvailable() || typeof window.pywebview.api.ready !== "function") return;
    bootstrapped = true;
    try {
      Promise.resolve(window.pywebview.api.ready()).then(function (obj) {
        if (obj) FRIDAY.bootstrap(obj);
      }).catch(function () { /* no-op */ });
    } catch (e) { /* no-op */ }
  }

  function init() {
    cacheRefs();
    buildContextMenu();
    buildDashboard();
    wireEvents();

    // Apply a sensible default look before Python bootstraps us.
    setMode("voice");
    setEmotion("neutral");
    setState("idle");

    requestAnimationFrame(tick);

    // pywebview injects its api asynchronously; try now and on its ready event.
    requestBootstrap();
    window.addEventListener("pywebviewready", requestBootstrap);
    // Fallback poll for a short window in case the event was missed.
    var tries = 0;
    var poll = setInterval(function () {
      tries++;
      if (bootstrapped || tries > 40) { clearInterval(poll); return; }
      requestBootstrap();
    }, 100);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
