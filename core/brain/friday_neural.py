"""
friday_neural.py — Friday 3.0
The Master Reasoner. The Core of the Core.
Multi-API routing: Groq → Gemini → OpenAI → emergency fallback.
Complexity-aware routing. Consensus on high-stakes queries.
Integrates: Chronicle (memory) + Psyche (identity) + Empath (tone) + World (knowledge).
No single point of failure. Ever.
"""

import os
import sys
import json
import time
import logging
import threading
import requests
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("friday.neural")

# ── Config (Smart Search) ─────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent

# Load secrets from the gitignored .env into the environment (best-effort).
try:
    from core.infra.friday_secrets import load_env
    load_env()
except Exception:
    pass

# API keys are read from these environment variables first; the config file is a
# fallback for non-secret settings (models, owner_name, voice, ...).
_ENV_KEY_MAP = {
    "groq_api_key":       "GROQ_API_KEY",
    "gemini_api_key":     "GEMINI_API_KEY",
    "openai_api_key":     "OPENAI_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
}

_POSSIBLE_PATHS = [
    _HERE / "friday_config.json",
    _ROOT / "friday_config.json",
    Path.cwd() / "friday_config.json"
]

def _pick_config_path() -> Optional[Path]:
    """Pick the first config that actually has an API key filled in; otherwise
    the first that exists. Stops an empty template (e.g. core/friday_config.json)
    from shadowing the real config with the keys."""
    existing = [p for p in _POSSIBLE_PATHS if p.exists()]
    for p in existing:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if any(str(data.get(k, "")).strip()
                   for k in ("groq_api_key", "openai_api_key", "gemini_api_key")):
                return p
        except Exception:
            continue
    return existing[0] if existing else None

_CONFIG_PATH = _pick_config_path()
_config_cache: Optional[dict] = None
_config_mtime: float          = 0.0
_config_lock                  = threading.Lock()

def _cfg() -> dict:
    """Config = file settings with API keys overlaid from the environment
    (env wins). Keys never need to live in the config file."""
    global _config_cache, _config_mtime
    file_cfg: dict = {}
    if _CONFIG_PATH:
        with _config_lock:
            try:
                mtime = os.path.getmtime(_CONFIG_PATH)
                if _config_cache is None or mtime != _config_mtime:
                    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                        _config_cache = json.load(f)
                    _config_mtime = mtime
                file_cfg = _config_cache or {}
            except Exception:
                file_cfg = _config_cache or {}

    merged = dict(file_cfg)
    for field, env_var in _ENV_KEY_MAP.items():
        val = os.environ.get(env_var, "").strip()
        if val:
            merged[field] = val
    return merged


# ── API definitions ────────────────────────────────────────────────────────────

@dataclass
class APIEndpoint:
    name:          str
    url:           str
    key_field:     str
    model_field:   str
    default_model: str
    priority:      int
    max_tokens:    int  = 1024
    timeout:       int  = 25
    enabled:       bool = True


_ENDPOINTS = [
    APIEndpoint(
        name          = "groq_primary",
        url           = "https://api.groq.com/openai/v1/chat/completions",
        key_field     = "groq_api_key",
        model_field   = "groq_model",
        default_model = "llama-3.3-70b-versatile",
        priority      = 1,
        timeout       = 20,
    ),
    APIEndpoint(
        name          = "gemini",
        url           = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        key_field     = "gemini_api_key",
        model_field   = "gemini_model",
        default_model = "gemini-2.0-flash",
        priority      = 2,
        timeout       = 25,
    ),
    APIEndpoint(
        name          = "openai",
        url           = "https://api.openai.com/v1/chat/completions",
        key_field     = "openai_api_key",
        model_field   = "openai_model",
        default_model = "gpt-4o-mini",
        priority      = 3,
        timeout       = 25,
    ),
    APIEndpoint(
        name          = "groq_fallback",
        url           = "https://api.groq.com/openai/v1/chat/completions",
        key_field     = "groq_api_key",
        model_field   = "groq_fallback_model",
        default_model = "llama-3.1-8b-instant",
        priority      = 4,
        timeout       = 15,
    ),
]

# Rate limit tracker
_rate_limits: dict[str, float] = {}
_rate_lock = threading.Lock()


def _is_rate_limited(name: str) -> bool:
    with _rate_lock:
        return time.time() < _rate_limits.get(name, 0)


def _set_rate_limit(name: str, retry_after: float = 10.0) -> None:
    with _rate_lock:
        _rate_limits[name] = time.time() + retry_after
    log.warning("Rate limit set on %s for %.1fs", name, retry_after)


# ── Per-API call implementations ───────────────────────────────────────────────

def _call_openai_compat(
    endpoint:    APIEndpoint,
    messages:    list[dict],
    temperature: float,
    max_tokens:  int,
) -> str:
    cfg     = _cfg()
    api_key = cfg.get(endpoint.key_field, "").strip()
    if not api_key:
        raise ValueError(f"No API key for {endpoint.name} ({endpoint.key_field})")

    model   = cfg.get(endpoint.model_field, endpoint.default_model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }

    resp = requests.post(endpoint.url, headers=headers, json=payload,
                         timeout=endpoint.timeout)

    if resp.status_code == 429:
        retry = float(resp.headers.get("Retry-After", 10))
        _set_rate_limit(endpoint.name, retry)
        raise RuntimeError(f"429 rate limit on {endpoint.name}")

    if resp.status_code >= 500:
        raise RuntimeError(f"Server error {resp.status_code} on {endpoint.name}")

    if resp.status_code != 200:
        body = resp.text.lower()
        if "decommissioned" in body or "no longer supported" in body:
            raise RuntimeError(f"Model decommissioned on {endpoint.name}: {resp.text[:100]}")
        raise RuntimeError(f"API error {resp.status_code} on {endpoint.name}: {resp.text[:200]}")

    text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    if not text:
        # Reasoning models (gpt-oss) can burn the whole token budget thinking;
        # an empty answer must fall through to the next endpoint, not be spoken.
        raise RuntimeError(f"Empty completion from {endpoint.name}")
    return text


def _call_gemini(
    endpoint:    APIEndpoint,
    messages:    list[dict],
    temperature: float,
    max_tokens:  int,
) -> str:
    cfg     = _cfg()
    api_key = cfg.get(endpoint.key_field, "").strip()
    if not api_key:
        raise ValueError(f"No API key for {endpoint.name} ({endpoint.key_field})")

    model   = cfg.get(endpoint.model_field, endpoint.default_model)
    url     = endpoint.url.format(model=model) + f"?key={api_key}"

    system_text      = ""
    gemini_contents  = []

    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        elif m["role"] == "user":
            text = m["content"]
            if system_text:
                text = f"{system_text}\n\n{text}"
                system_text = ""
            gemini_contents.append({"role": "user",  "parts": [{"text": text}]})
        elif m["role"] == "assistant":
            gemini_contents.append({"role": "model", "parts": [{"text": m["content"]}]})

    if not gemini_contents:
        raise ValueError("No content to send to Gemini")

    payload = {
        "contents": gemini_contents,
        "generationConfig": {
            "temperature":     temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    resp = requests.post(url, json=payload, timeout=endpoint.timeout)

    if resp.status_code == 429:
        _set_rate_limit(endpoint.name, 15)
        raise RuntimeError(f"429 rate limit on {endpoint.name}")

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")

    candidates = resp.json().get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")

    return candidates[0]["content"]["parts"][0]["text"].strip()


def _call_endpoint(
    endpoint:    APIEndpoint,
    messages:    list[dict],
    temperature: float,
    max_tokens:  int,
) -> str:
    if _is_rate_limited(endpoint.name):
        raise RuntimeError(f"{endpoint.name} is rate limited")
    if endpoint.name == "gemini":
        return _call_gemini(endpoint, messages, temperature, max_tokens)
    return _call_openai_compat(endpoint, messages, temperature, max_tokens)


# ── Message assembly ───────────────────────────────────────────────────────────

def _build_messages(
    prompt:  str,
    system:  str,
    history: list[dict],
    context: str,
) -> list[dict]:
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-20:])

    user_content = f"{context}\n\nQuestion: {prompt}" if context else prompt
    messages.append({"role": "user", "content": user_content})
    return messages


# ── History ────────────────────────────────────────────────────────────────────

_history:      list[dict] = []
_history_lock  = threading.Lock()
_HISTORY_CAP   = 30


# ── Answer-source signal ───────────────────────────────────────────────────────
# Thread-local because think() runs on spine, Flask-job and daemon threads
# concurrently. This is the truthful signal behind the independence metric:
# consumers (sovereign, DecisionLog) must know whether the cloud was used.

_last_source = threading.local()


def _set_answer_source(source: str) -> None:
    _last_source.value = source


def last_answer_source() -> str:
    """
    Where the last think() answer on THIS thread came from:
    'local' | 'cloud:<endpoint>' | 'unknown'.
    """
    return getattr(_last_source, "value", "unknown")


def last_answer_was_local() -> bool:
    return last_answer_source() == "local"


# ── Core think function ────────────────────────────────────────────────────────

def think(
    user_input:      str,
    *,
    system:          Optional[str] = None,
    context:         str           = "",
    temperature:     float         = 0.45,
    max_tokens:      int           = 500,
    force_endpoint:  Optional[str] = None,
    allow_local:     bool          = False,
) -> str:
    """
    Friday's master reasoning function.
    Routes through the API chain. Never fails silently.

    The basic reasoner is the CLOUD (M42, owner-directed): Groq → Gemini →
    OpenAI answer first. If allow_local is set, the on-device retrieval QA
    (friday_local) is the terminal fallback when every endpoint is down, and
    substantive cloud answers are learned back into the vault.
    """
    global _history

    _set_answer_source("unknown")

    full_system = _build_full_system(system)

    with _history_lock:
        history_snapshot = list(_history)

    messages   = _build_messages(user_input, full_system, history_snapshot, context)
    endpoints  = sorted(_ENDPOINTS, key=lambda e: e.priority)

    if force_endpoint:
        endpoints = [e for e in endpoints if e.name == force_endpoint] + \
                    [e for e in endpoints if e.name != force_endpoint]

    last_error: Optional[Exception] = None
    response:   Optional[str]       = None

    for ep in endpoints:
        if _is_rate_limited(ep.name):
            log.info("Skipping %s (rate limited)", ep.name)
            continue

        try:
            t0       = time.time()
            response = _call_endpoint(ep, messages, temperature, max_tokens)
            elapsed  = round((time.time() - t0) * 1000)
            _set_answer_source(f"cloud:{ep.name}")
            log.info("✓ %s responded in %dms", ep.name, elapsed)

            # Notify UI if not using primary
            if ep.name != "groq_primary":
                _emit_notice(f"Using {ep.name}")

            break

        except Exception as e:
            last_error = e
            log.warning("✗ %s failed: %s — trying next", ep.name, e)

    # ── Offline fallback: every endpoint failed — answer from her own
    # knowledge (retrieval + local reader) rather than failing the turn.
    if response is None and allow_local and not force_endpoint:
        local_resp = _try_local(user_input)
        if local_resp:
            log.info("✓ local_qa answered (all cloud endpoints down)")
            _set_answer_source("local")
            _emit_notice("Answered locally (offline)")
            _record_turn(user_input, local_resp)
            return local_resp

    if response is None:
        raise RuntimeError(f"All API endpoints exhausted. Last error: {last_error}")

    _record_turn(user_input, response)

    # This was a cloud answer to a real question on the main answer path —
    # remember it so the local module can learn it on its next retrain.
    if allow_local:
        _maybe_learn(user_input, response)

    return response


def think_with_context(
    user_input:  str,
    *,
    tone:        str   = "neutral",
    task_type:   str   = "conversation",
    max_tokens:  int   = 500,
    temperature: float = 0.45,
    extract_knowledge: bool = True,
) -> str:
    """
    Full pipeline think:
    World context → Chronicle memory → Psyche identity → Empath tone → Neural routing.
    This is what friday_spine and friday_brain call.
    """
    # 1. Pull world context (Layer 2 — pre-knowledge from background ingest)
    world_context = ""
    try:
        from core.knowledge.friday_world import query_world
        world_results = query_world(user_input, k=4)
        if world_results:
            snippets = []
            for r in world_results:
                title   = r.get("title", "")
                content = r.get("content", "")[:300]
                snippets.append(f"• {title}: {content}")
            world_context = "Knowledge from your vault:\n" + "\n".join(snippets)
            log.debug("World context: %d entries", len(world_results))
    except Exception as e:
        log.debug("World context unavailable: %s", e)

    # 2. Pull Chronicle memory context (Layer 3)
    memory_context = ""
    try:
        from core.knowledge.friday_chronicle import build_context_block
        memory_context = build_context_block(user_input)
    except Exception as e:
        log.debug("Chronicle context failed: %s", e)

    # 3. Merge contexts: world first (background knowledge), then memory (personal history)
    context_parts = [p for p in (world_context, memory_context) if p]
    merged_context = "\n\n".join(context_parts)
    if merged_context:
        # Tell her HOW to use the retrieved knowledge — without this the model
        # treats the snippets as noise instead of grounding its answer in them.
        merged_context = (
            "[The following is knowledge you already have (recalled from your vault) "
            "plus relevant memory. Use whatever is relevant to answer accurately and "
            "specifically, and prefer it over guessing. Silently ignore anything that "
            "isn't relevant, and don't refer to this section explicitly.]\n\n"
            + merged_context
        )

    # 4. Pull identity + mood system prompt (Layer 4)
    system = _build_full_system()

    # 5. Empath signal — tone, temperature, token budget (Layer 5)
    empath_tone = tone   # falls back to the caller's packet tone
    try:
        from core.persona.friday_empath import analyze, build_tone_prompt
        signal      = analyze(user_input)
        tone_hint   = build_tone_prompt(signal)
        temperature = signal.response_temperature
        max_tokens  = signal.response_max_tokens
        empath_tone = signal.tone
        if tone_hint:
            system += f"\n\n{tone_hint}"
    except Exception as e:
        log.debug("Empath analysis failed: %s", e)

    # 6. Think
    response = think(
        user_input,
        system      = system,
        context     = merged_context,
        temperature = temperature,
        max_tokens  = max_tokens,
        allow_local = True,      # offline fallback + learn cloud answers into the vault
    )

    # 6b. Visual answer — open a map / news / images / weather view when the
    #     question asks for something to see (best-effort, alongside the text).
    try:
        from core.io.friday_visual import maybe_show
        maybe_show(user_input)
    except Exception as e:
        log.debug("Visual answer failed: %s", e)

    # 7. Persist to Chronicle
    try:
        from core.knowledge.friday_chronicle import save_turn
        save_turn("user",   user_input, importance=0.6)
        save_turn("friday", response,   importance=0.7)
    except Exception as e:
        log.debug("Chronicle save failed: %s", e)

    # 8. Update psyche — Empath's computed tone drives mood (a default
    #    "neutral" used to be passed instead), and the turn feedback is honest:
    #    a frustrated/stressed Satvik is a negative signal, so trust can fall.
    try:
        from core.persona.friday_psyche import record_turn, infer_mood_from_context, update_mood
        record_turn(positive=empath_tone not in ("frustrated", "stressed"))
        new_mood = infer_mood_from_context(
            satvik_tone = empath_tone,
            task_type   = task_type,
            session_len = len(_history) // 2,
        )
        update_mood(new_mood)
    except Exception as e:
        log.debug("Psyche update failed: %s", e)

    # 9. Sovereign — extract knowledge from this exchange (Layer 8).
    #    friday_brain owns extraction on its path (it has intent + the
    #    critic-reviewed response) and passes extract_knowledge=False; this
    #    call covers standalone use of think_with_context. The old call here
    #    had a missing `intent` argument and threw on every turn since 3.0.
    if extract_knowledge:
        try:
            from core.knowledge.friday_sovereign import run_background
            run_background(
                user_input      = user_input,
                friday_response = response,
                intent          = task_type,
                used_api        = not last_answer_was_local(),
            )
        except Exception as e:
            log.debug("Sovereign extraction failed: %s", e)

    # 10. Emit signal
    _emit_signal("THINKING_DONE", response)

    return response


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_full_system(extra: Optional[str] = None) -> str:
    parts = []
    try:
        from core.persona.friday_psyche import get_identity_block, get_mood_prompt
        parts.append(get_identity_block())
        parts.append(get_mood_prompt())
    except Exception:
        parts.append(
            "You are Friday, Satvik's AI partner. "
            "Be direct, warm, sharp, and independent. "
            "Max 5 sentences unless it's a complex technical task."
        )
    if extra:
        parts.append(extra)
    return "\n\n".join(p for p in parts if p)


def _try_local(user_input: str) -> Optional[str]:
    """Try the on-device retrieval QA (friday_local). Returns an answer or None."""
    try:
        from core.brain.friday_local import answer as _local_answer
        return _local_answer(user_input)
    except Exception as e:
        log.debug("Local QA unavailable: %s", e)
        return None


_QUESTION_STARTS = (
    "what", "why", "how", "is", "are", "can", "could", "does", "do", "who",
    "when", "where", "which", "will", "would", "explain", "define", "tell",
)


def _maybe_learn(question: str, answer: str) -> None:
    """If a cloud answer looks like real knowledge (a substantive answer to a
    question), save it to the vault so Friday can recall it locally next time."""
    q = question.strip().lower()
    if len(answer.strip()) < 100:
        return
    first = q.split(" ", 1)[0] if q else ""
    if not (q.endswith("?") or first in _QUESTION_STARTS):
        return
    try:
        from core.knowledge.friday_world import learn as _world_learn
        if _world_learn(question, answer):
            log.info("Learned new knowledge → vault: %s", question[:60])
    except Exception as e:
        log.debug("Learn step failed: %s", e)


def _record_turn(user_input: str, response: str) -> None:
    global _history
    with _history_lock:
        _history.append({"role": "user",      "content": user_input})
        _history.append({"role": "assistant", "content": response})
        if len(_history) > _HISTORY_CAP:
            _history = _history[-20:]


def _emit_notice(msg: str):
    try:
        from core.infra.friday_signal import get_bus, Signal
        get_bus().emit_sync(Signal.UI_UPDATE, data={"notice": msg}, source="neural")
    except Exception:
        pass


def _emit_signal(event: str, data):
    try:
        from core.infra.friday_signal import get_bus, Signal
        get_bus().emit_sync(getattr(Signal, event, event), data=data, source="neural")
    except Exception:
        pass


def clear_history() -> None:
    global _history
    with _history_lock:
        _history = []
    log.info("Neural history cleared")


def history_len() -> int:
    with _history_lock:
        return len(_history) // 2


def get_api_status() -> dict:
    cfg    = _cfg()
    status = {}
    for ep in _ENDPOINTS:
        has_key = bool(cfg.get(ep.key_field, "").strip())
        limited = _is_rate_limited(ep.name)
        status[ep.name] = {
            "has_key":      has_key,
            "rate_limited": limited,
            "model":        cfg.get(ep.model_field, ep.default_model),
            "priority":     ep.priority,
            "available":    has_key and not limited,
        }
    return status


# ── Self-test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_neural] Running self-test...\n")
    status = get_api_status()
    print("  API Status:")
    for name, s in status.items():
        key_str  = "✓ key"  if s["has_key"]   else "✗ no key"
        avail    = "AVAILABLE" if s["available"] else "unavailable"
        print(f"    [{s['priority']}] {name:20} {key_str:10} → {avail} ({s['model']})")

    available = [n for n, s in status.items() if s["available"]]
    if not available:
        print("\n  No API keys configured. Add keys to friday_config.json.")
        print("  Required: groq_api_key  Optional: gemini_api_key, openai_api_key")
        sys.exit(0)

    print(f"\n  Available APIs: {available}")
    print("  Testing live call...\n")

    try:
        response = think(
            "Say 'Friday online' and nothing else.",
            temperature = 0.1,
            max_tokens  = 20,
        )
        print(f"  ✓ Response: {response}")
        print(f"  ✓ History:  {history_len()} turns")
        clear_history()
        print(f"  ✓ Cleared:  {history_len()} turns")
        print("\n[friday_neural] All tests passed ✓\n")
    except Exception as e:
        print(f"\n  ✗ Live call failed: {e}")
        sys.exit(1)