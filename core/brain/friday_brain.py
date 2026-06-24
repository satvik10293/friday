"""
friday_brain.py — Friday 3.0
The unified brain interface.
Single entry point: friday.respond(user_text) → response string

Pipeline:
  Signal → Context → Neural → Critic → Response → Sovereign (background)

Drop this in core/ and call it from friday_voice_loop.py.
"""

import sys
import time
import logging
from pathlib import Path
from typing import Optional

# Ensure project root is on path regardless of where this is run from
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.brain")


class FridayBrain:
    """
    Unified interface to the full Friday reasoning pipeline.
    Instantiate once. Call respond() on every user turn.
    """

    def __init__(self):
        self._ready        = False
        self._session_len  = 0
        self._last_intent  = "chat"
        self._last_topic   = ""
        self._last_response = ""
        self._boot()

    # ── Boot ──────────────────────────────────────────────────────────────────

    def _boot(self) -> None:
        print("[FridayBrain] Booting...")

        # 1. Psyche — identity + mood
        try:
            from core.persona.friday_psyche import boot
            self._psyche_state = boot()
            print(f"[FridayBrain] Psyche online — mood: {self._psyche_state.emotional.mood}")
        except Exception as e:
            print(f"[FridayBrain] Psyche failed: {e}")
            self._psyche_state = None

        # 2. Chronicle — start session
        try:
            from core.knowledge.friday_chronicle import start_session
            self._session_id = start_session()
            print(f"[FridayBrain] Chronicle online — session: {self._session_id}")
        except Exception as e:
            print(f"[FridayBrain] Chronicle failed: {e}")
            self._session_id = "default"

        # 3. Signal bus
        try:
            from core.infra.friday_signal import get_bus
            self._bus = get_bus()
            print("[FridayBrain] Signal bus online")
        except Exception as e:
            print(f"[FridayBrain] Signal bus failed: {e}")
            self._bus = None

        # 4. Sovereign — load stats
        try:
            from core.knowledge.friday_sovereign import load_stats
            load_stats()
            print("[FridayBrain] Sovereign online")
        except Exception as e:
            print(f"[FridayBrain] Sovereign failed: {e}")

        # 5. Learning — load preferences
        try:
            from core.knowledge.friday_learning import get_preferences
            self._prefs = get_preferences()
            print(f"[FridayBrain] Learning online — {len(self._prefs)} preferences loaded")
        except Exception as e:
            print(f"[FridayBrain] Learning failed: {e}")
            self._prefs = {}

        self._ready = True
        print("[FridayBrain] Ready ✓")

    # ── Core respond pipeline ─────────────────────────────────────────────────

    def respond(self, user_text: str) -> str:
        """
        Full pipeline: user_text → response string.
        Always returns a string. Never raises.
        """
        if not user_text or not user_text.strip():
            return ""

        t0 = time.time()
        user_text = user_text.strip()

        try:
            # ── Stage 1: Emit USER_TEXT signal ────────────────────────────────
            self._emit_signal("USER_TEXT", user_text, priority=2)

            # ── Stage 2: Context Builder ──────────────────────────────────────
            packet = self._build_context(user_text)

            # ── Stage 3: Emit THINKING_START ──────────────────────────────────
            self._emit_signal("THINKING_START",
                              {"intent": packet.intent, "priority": packet.priority},
                              priority=3)

            # ── Stage 4: Neural reasoning ─────────────────────────────────────
            response = self._neural_think(user_text, packet)

            # ── Stage 5: Critic review ────────────────────────────────────────
            response = self._critic_check(response, user_text, packet)

            # ── Stage 6: Emit THINKING_DONE ───────────────────────────────────
            self._emit_signal("THINKING_DONE", response, priority=2)

            # ── Stage 7: Record feedback / learning ───────────────────────────
            self._record_learning(user_text, packet)

            # ── Stage 8: Sovereign extraction (background) ────────────────────
            self._sovereign_extract(user_text, response, packet)

            # ── Update session state ──────────────────────────────────────────
            self._session_len  += 1
            self._last_intent   = packet.intent
            self._last_topic    = packet.topic
            self._last_response = response

            elapsed = round((time.time() - t0) * 1000)
            log.info("respond() done in %dms | intent=%s", elapsed, packet.intent)

            return response

        except Exception as e:
            log.error("respond() pipeline failed: %s", e, exc_info=True)
            return self._safe_fallback(user_text)

    # ── Stage implementations ─────────────────────────────────────────────────

    def _build_context(self, user_text: str):
        """Stage 2: Build context packet."""
        try:
            from core.brain.friday_context import build
            return build(
                user_text,
                prev_topic  = self._last_topic,
                session_len = self._session_len,
            )
        except Exception as e:
            log.warning("Context build failed: %s — using minimal packet", e)
            # Minimal fallback packet
            from types import SimpleNamespace
            pkt = SimpleNamespace(
                intent          = "chat",
                priority        = 3,
                topic           = "",
                temperature     = 0.45,
                max_tokens      = 400,
                route_to        = ["neural"],
                system_addendum = "",
                refined_prompt  = user_text,
                needs_search    = False,
                needs_memory    = True,
                complexity      = "medium",
                tone            = "neutral",
            )
            return pkt

    def _neural_think(self, user_text: str, packet) -> str:
        """Stage 4: Route through Neural with full context."""
        try:
            from core.brain.friday_neural import think_with_context

            # Check if Codex should handle this
            if "codex" in getattr(packet, "route_to", []):
                codex_response = self._codex_think(user_text, packet)
                if codex_response:
                    return codex_response

            # Check if Planner should handle this
            if "planner" in getattr(packet, "route_to", []):
                planner_response = self._planner_think(user_text, packet)
                if planner_response:
                    return planner_response

            return think_with_context(
                user_text,
                tone        = getattr(packet, "tone", "neutral"),
                task_type   = getattr(packet, "intent", "chat"),
                max_tokens  = getattr(packet, "max_tokens", 400),
                temperature = getattr(packet, "temperature", 0.45),
            )

        except Exception as e:
            log.warning("Neural think failed: %s", e)
            return self._safe_fallback(user_text)

    def _codex_think(self, user_text: str, packet) -> Optional[str]:
        """Route code tasks through Codex specialist."""
        try:
            from core.brain.friday_codex import build_packet as codex_build
            from core.brain.friday_neural import think

            cp = codex_build(
                user_text,
                intent   = getattr(packet, "intent", "code_write"),
                language = getattr(packet, "language", None),
            )

            response = think(
                cp.prompt,
                system      = cp.system,
                temperature = cp.temperature,
                max_tokens  = cp.max_tokens,
            )
            return response
        except Exception as e:
            log.warning("Codex think failed: %s — falling back to neural", e)
            return None

    def _planner_think(self, user_text: str, packet) -> Optional[str]:
        """Route planning tasks through Planner."""
        try:
            from core.brain.friday_planner import build_plan_prompt, parse_plan_from_response, format_plan_for_display, register_plan
            from core.brain.friday_neural import think

            prompt, system = build_plan_prompt(user_text)
            raw_plan = think(
                prompt,
                system      = system,
                temperature = 0.4,
                max_tokens  = 800,
            )

            plan = parse_plan_from_response(user_text, raw_plan)
            register_plan(plan)
            return format_plan_for_display(plan)
        except Exception as e:
            log.warning("Planner think failed: %s — falling back to neural", e)
            return None

    def _critic_check(self, response: str, original: str, packet) -> str:
        """Stage 5: Critic reviews the response."""
        try:
            from core.brain.friday_critic import critique_with_retry
            from core.brain.friday_neural import think

            return critique_with_retry(
                prompt      = original,
                response    = response,
                intent      = getattr(packet, "intent", "chat"),
                think_fn    = think,
                max_retries = 1,
                max_tokens  = getattr(packet, "max_tokens", 400),
            )
        except Exception as e:
            log.warning("Critic check failed: %s — returning original", e)
            return response

    def _record_learning(self, user_text: str, packet) -> None:
        """Stage 7: Check if this turn contains feedback/corrections."""
        if self._session_len == 0:
            return
        try:
            from core.knowledge.friday_learning import record_feedback
            record_feedback(
                user_message    = user_text,
                friday_response = self._last_response,
                intent          = self._last_intent,
            )
        except Exception as e:
            log.debug("Learning record failed: %s", e)

    def _sovereign_extract(self, user_text: str, response: str, packet) -> None:
        """Stage 8: Background knowledge extraction."""
        try:
            from core.knowledge.friday_sovereign import run_background
            run_background(
                user_input      = user_text,
                friday_response = response,
                intent          = getattr(packet, "intent", "chat"),
                used_api        = True,
            )
        except Exception as e:
            log.debug("Sovereign extract failed: %s", e)

    def _emit_signal(self, signal_name: str, data=None, priority: int = 5) -> None:
        if not self._bus:
            return
        try:
            from core.infra.friday_signal import Signal
            sig = getattr(Signal, signal_name, None)
            if sig:
                self._bus.emit_sync(sig, data=data, source="brain", priority=priority)
        except Exception:
            pass

    # ── Fallback ───────────────────────────────────────────────────────────────

    def _safe_fallback(self, user_text: str) -> str:
        """Last-resort response when everything fails."""
        log.warning("Using safe fallback for: %s", user_text[:50])
        q = user_text.lower()
        if any(w in q for w in ("hello", "hi", "hey")):
            return "Hey — I'm here. What do you need?"
        if "time" in q:
            from datetime import datetime
            return f"It's {datetime.now().strftime('%I:%M %p')}."
        if "your name" in q or "who are you" in q:
            return "I'm Friday. Your AI partner."
        if any(w in q for w in ("exit", "quit", "shutdown", "bye")):
            return "__EXIT__"
        return "I'm processing that — give me a moment."

    # ── Utilities ──────────────────────────────────────────────────────────────

    def greeting(self) -> str:
        """Boot greeting based on psyche state."""
        try:
            from core.persona.friday_psyche import get_greeting
            return get_greeting()
        except Exception:
            return "Friday online. What do you need?"

    def status(self) -> dict:
        """Full brain status — for debugging."""
        try:
            from core.persona.friday_psyche import full_status
            from core.knowledge.friday_chronicle import stats as chron_stats
            from core.knowledge.friday_sovereign import get_status as sov_status
            return {
                "ready":        self._ready,
                "session_len":  self._session_len,
                "session_id":   self._session_id,
                "psyche":       full_status(),
                "chronicle":    chron_stats(),
                "sovereign":    sov_status(),
            }
        except Exception as e:
            return {"ready": self._ready, "error": str(e)}

    def end_session(self, summary: Optional[str] = None) -> None:
        """Call on shutdown."""
        try:
            from core.knowledge.friday_chronicle import end_session
            end_session(summary)
        except Exception:
            pass
        log.info("Brain session ended")


# ── Singleton ─────────────────────────────────────────────────────────────────

_brain: Optional[FridayBrain] = None


def get_brain() -> FridayBrain:
    global _brain
    if _brain is None:
        _brain = FridayBrain()
    return _brain


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_brain] Running self-test...\n")

    brain = FridayBrain()
    print(f"\n  Greeting: {brain.greeting()}")

    # Check if API keys are configured
    config_path = "friday_config.json"
    has_keys = False
    try:
        import json
        cfg = json.load(open(config_path))
        has_keys = bool(cfg.get("groq_api_key", "").strip())
    except Exception:
        pass

    if not has_keys:
        print("\n  No API keys found in friday_config.json")
        print("  Testing fallback responses only...\n")
        cases = [
            ("hello friday",   True),
            ("what time is it", True),
            ("who are you",     True),
        ]
        for text, should_respond in cases:
            resp = brain._safe_fallback(text)
            ok   = bool(resp) == should_respond
            print(f"  {'✓' if ok else '✗'} '{text}' → '{resp}'")
    else:
        print("\n  API keys found — testing live pipeline...\n")
        test_inputs = [
            "What is your name?",
            "Write a Python one-liner to reverse a string",
        ]
        for inp in test_inputs:
            print(f"  Testing: '{inp}'")
            resp = brain.respond(inp)
            print(f"  Response: {resp[:120]}{'...' if len(resp) > 120 else ''}\n")

    print(f"\n  Status: {brain.status()}")
    brain.end_session("brain self-test")
    print("\n[friday_brain] Self-test complete ✓\n")
