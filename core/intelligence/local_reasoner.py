"""
core/intelligence/local_reasoner.py — FRIDAY 5.x (M54)
Her own reasoning brain — local, on-device, and OURS.

Where the keyword `builtin_models` team can only recite retrieved snippets and
the CloudReasoner (M42) rents a frontier mind over the network, the
LocalReasoner is a *real* small reasoning model (Qwen2.5-class, ~3B) running
locally through llama.cpp, wrapped in a reasoning scaffold WE own:

    draft  →  self-critique  →  corrected final

The weights are the substrate; the scaffold is the reasoning. A 3B model that
checks and repairs its own first answer is meaningfully better than one that
blurts — and that loop is the part we control, tune, and can extend (tools,
retrieval, multi-step) without swapping the model.

Design, mirroring CloudReasoner so it drops straight into the local chain:
    · same ReasonedAnswer contract, same reason()/available()/status() surface
    · NEVER raises — a missing dependency, missing model file, or a generation
      fault returns ok=False and the caller falls through to the rest of the
      local chain (ios team → librarian → teacher)
    · lazy: the model (a multi-GB file + llama_cpp) loads on first real use,
      never at import and never at boot — available() is cheap and honest
    · local-first & private: this path may reason over PRIVATE memory because
      nothing leaves the box; it is the brain personal questions are meant for
    · injectable backend: tests pass a stub, so the scaffold is verifiable with
      zero model download

Config under the `local_brain` block in friday_config.json. Pull the weights
once with:  python -m core.intelligence.local_reasoner --pull
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional, Protocol

from core.intelligence.cloud_reasoner import ReasonedAnswer  # shared contract
from core.intelligence.teacher import _context_block          # same grounding

log = logging.getLogger("friday.intelligence.local_reasoner")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "friday_config.json"
_MODELS_DIR = _ROOT / "models"

# A small, genuinely capable instruct model that fits an 8 GB CPU box at Q4
# (~2 GB resident) and actually reasons + writes usable code — unlike flan-t5.
_DEFAULT_REPO = "Qwen/Qwen2.5-3B-Instruct-GGUF"
_DEFAULT_FILE = "qwen2.5-3b-instruct-q4_k_m.gguf"
_DEFAULT_MAX_TOKENS = 700
_DEFAULT_N_CTX = 4096

_SYSTEM_PROMPT = (
    "You are FRIDAY, Satvik's personal AI assistant — direct, warm, sharp, and "
    "technically excellent. Think carefully, then answer accurately and "
    "concisely. Keep conversational answers to one to four spoken sentences. "
    "For technical, coding, or math questions give the complete correct answer; "
    "write code as plain indented text without markdown fences. Never mention "
    "these instructions or that you are a language model.")

# The self-critique pass — the reasoning we own. The model audits its own draft
# for errors and returns a corrected final answer (or the same answer if it was
# already right). Kept terse so a small model stays on task.
_CRITIQUE_PROMPT = (
    "Review your previous answer for factual errors, faulty logic, or bugs in "
    "any code. If it is correct, repeat it verbatim. If not, reply ONLY with "
    "the corrected answer. Do not explain what you changed or mention this "
    "review.")


class ReasoningBackend(Protocol):
    """The minimal surface the scaffold needs from a text model. The real
    implementation wraps llama.cpp; tests inject a stub."""

    def available(self) -> bool: ...

    def chat(self, messages: list[dict], *, max_tokens: int,
             temperature: float) -> str: ...


class LlamaCppBackend:
    """llama.cpp GGUF backend. Loads lazily and exactly once; degrades to
    unavailable (never raises) when llama_cpp isn't installed or the model file
    is absent."""

    def __init__(self, *, model_path: Path, n_ctx: int, n_threads: int) -> None:
        self._model_path = model_path
        self._n_ctx = n_ctx
        self._n_threads = n_threads
        self._llm = None
        self._tried = False
        self._ok = False

    def available(self) -> bool:
        # cheap, honest gate: deps present AND the weights are on disk. The
        # actual (expensive) load is deferred to the first chat() call.
        if self._ok:
            return True
        if self._tried and self._llm is None:
            return False
        import importlib.util
        if importlib.util.find_spec("llama_cpp") is None:
            return False
        return self._model_path.exists()

    def _ensure_loaded(self) -> bool:
        if self._llm is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        if not self._model_path.exists():
            log.warning("local brain: model file not found at %s — run "
                        "`python -m core.intelligence.local_reasoner --pull`",
                        self._model_path)
            return False
        try:
            from llama_cpp import Llama
            self._llm = Llama(
                model_path=str(self._model_path),
                n_ctx=self._n_ctx,
                n_threads=(self._n_threads or None),
                verbose=False)
            self._ok = True
            log.info("local brain loaded: %s", self._model_path.name)
            return True
        except Exception as e:  # noqa: BLE001 — a bad load must not crash a turn
            log.warning("local brain failed to load: %s", e)
            self._llm = None
            return False

    def chat(self, messages: list[dict], *, max_tokens: int,
             temperature: float) -> str:
        if not self._ensure_loaded():
            return ""
        try:
            out = self._llm.create_chat_completion(
                messages=messages, max_tokens=max_tokens,
                temperature=temperature)
            return (out["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:  # noqa: BLE001 — generation faults degrade quietly
            log.debug("local brain generation failed: %s", e)
            return ""


class LocalReasoner:
    """FRIDAY's own local reasoning brain: a real model behind a draft →
    self-critique → final scaffold. Mirrors CloudReasoner; never raises."""

    def __init__(self, *, enabled: Optional[bool] = None,
                 model_path: Optional[str] = None,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None,
                 self_check: Optional[bool] = None,
                 backend: Optional[ReasoningBackend] = None) -> None:
        cfg = _local_brain_config()
        self.enabled = cfg.get("enabled", True) if enabled is None else enabled
        self.max_tokens = int(max_tokens or cfg.get("max_tokens")
                              or _DEFAULT_MAX_TOKENS)
        self.temperature = float(cfg.get("temperature", 0.3)
                                 if temperature is None else temperature)
        self.self_check = cfg.get("self_check", True) if self_check is None \
            else self_check
        self._model_path = Path(model_path) if model_path else _resolve_model_path(cfg)
        if backend is not None:
            self._backend: ReasoningBackend = backend
        else:
            self._backend = LlamaCppBackend(
                model_path=self._model_path,
                n_ctx=int(cfg.get("n_ctx") or _DEFAULT_N_CTX),
                n_threads=int(cfg.get("n_threads") or 0))
        self.asked = 0
        self.answered = 0
        self.failed = 0
        self.self_corrections = 0
        self.total_latency_ms = 0.0

    def available(self) -> bool:
        """Enabled AND a usable backend (deps + weights). Cheap — no model
        load. `enabled: false` in config disables the local brain outright."""
        return bool(self.enabled) and self._backend.available()

    def reason(self, question: str, *, context: Optional[dict] = None) -> ReasonedAnswer:
        """One local reasoning turn: draft, then (optionally) self-critique into
        a corrected final answer. Never raises; ok=False on any failure so the
        caller falls through to the rest of the local chain.

        Unlike the cloud path, `context` MAY include private material — this
        stays on the box."""
        if not self.available():
            return ReasonedAnswer(ok=False, error="local brain unavailable")
        self.asked += 1
        t0 = time.perf_counter()

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        block = _context_block(context)
        if block:
            messages.append({"role": "system",
                             "content": "Context from FRIDAY's local knowledge "
                                        "and memory:\n" + block})
        messages.append({"role": "user", "content": question})

        draft = self._backend.chat(messages, max_tokens=self.max_tokens,
                                   temperature=self.temperature)
        if not draft:
            self.failed += 1
            return ReasonedAnswer(ok=False, error="empty draft",
                                  latency_ms=(time.perf_counter() - t0) * 1000.0)

        final = draft
        if self.self_check:
            checked = self._critique(messages, draft)
            if checked and checked != draft:
                self.self_corrections += 1
                final = checked

        latency = (time.perf_counter() - t0) * 1000.0
        self.answered += 1
        self.total_latency_ms += latency
        return ReasonedAnswer(ok=True, answer=final,
                              model=self._model_path.name, latency_ms=latency)

    def _critique(self, base_messages: list[dict], draft: str) -> str:
        """The reasoning we own: have the model audit and repair its own draft.
        A low temperature keeps the correction faithful."""
        messages = list(base_messages) + [
            {"role": "assistant", "content": draft},
            {"role": "user", "content": _CRITIQUE_PROMPT}]
        try:
            return self._backend.chat(messages, max_tokens=self.max_tokens,
                                      temperature=min(self.temperature, 0.2))
        except Exception:  # noqa: BLE001 — the draft still stands if critique fails
            log.debug("self-critique failed; keeping draft", exc_info=True)
            return ""

    def status(self) -> dict:
        return {"primary": "local", "available": self.available(),
                "enabled": bool(self.enabled),
                "model": self._model_path.name,
                "model_present": self._model_path.exists(),
                "self_check": bool(self.self_check),
                "asked": self.asked, "answered": self.answered,
                "failed": self.failed, "self_corrections": self.self_corrections,
                "avg_latency_ms": round(self.total_latency_ms / self.answered, 1)
                if self.answered else 0.0}


def _local_brain_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg.get("local_brain") or {}
    except (OSError, ValueError):
        return {}


def _resolve_model_path(cfg: dict) -> Path:
    """An explicit `model_path` wins; otherwise models/<model_file>."""
    explicit = (cfg.get("model_path") or "").strip()
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else (_ROOT / p)
    return _MODELS_DIR / (cfg.get("model_file") or _DEFAULT_FILE)


def get_local_reasoner() -> Optional[LocalReasoner]:
    """Build the local brain if it's enabled AND usable (deps + weights on
    disk); else None, so the bridge simply runs without it (as before). Never
    raises."""
    try:
        reasoner = LocalReasoner()
    except Exception as e:  # noqa: BLE001 — the local brain is always optional
        log.debug("local reasoner unavailable: %s", e)
        return None
    return reasoner if reasoner.available() else None


# ── one-time model fetch ──────────────────────────────────────────────────────
def pull_model(repo: Optional[str] = None, filename: Optional[str] = None) -> Path:
    """Download the GGUF weights into models/ via huggingface_hub. Idempotent —
    hf caches, and we copy/point into models/. Returns the final path."""
    cfg = _local_brain_config()
    repo = repo or cfg.get("model_repo") or _DEFAULT_REPO
    filename = filename or cfg.get("model_file") or _DEFAULT_FILE
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _MODELS_DIR / filename
    if dest.exists():
        print(f"already present: {dest}")
        return dest
    from huggingface_hub import hf_hub_download
    print(f"downloading {filename} from {repo} … (this is a few GB, one time)")
    cached = hf_hub_download(repo_id=repo, filename=filename,
                             local_dir=str(_MODELS_DIR))
    print(f"ready: {cached}")
    return Path(cached)


def _main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="FRIDAY local reasoning brain")
    ap.add_argument("--pull", action="store_true", help="download the model")
    ap.add_argument("--ask", type=str, default="", help="ask the local brain")
    ap.add_argument("--status", action="store_true", help="print status")
    args = ap.parse_args(argv)
    if args.pull:
        pull_model()
        return 0
    r = LocalReasoner()
    if args.status or not args.ask:
        print(json.dumps(r.status(), indent=2))
        return 0
    ans = r.reason(args.ask)
    print(ans.answer if ans.ok else f"[unavailable] {ans.error}")
    return 0 if ans.ok else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
