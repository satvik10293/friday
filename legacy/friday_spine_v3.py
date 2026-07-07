"""
legacy/friday_spine_v3.py — Friday 3.0 (QUARANTINED, Phase A cutover)
The retired 3.0 master orchestrator, kept for reference and emergency fallback.
The production boot path is `friday_launch.py` (also reachable via the
`friday_spine.py` shim). Do not import this from new code — the 3.0 respond
pipeline (`friday_brain` → `friday_neural`) is superseded by the launcher's
cognitive stack. See docs/FRIDAY_5X_ROADMAP.md, Phase A.
"""

import sys
import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent          # legacy/ lives one level below the repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.spine")


class FridaySpine:

    def __init__(self):
        self._running  = False
        self._bus      = None
        self._brain    = None
        self._world    = None
        self._senses   = None
        self._voice    = None
        self._action   = None
        self._notify   = None
        # Interruptible speech (v2 port)
        self._speaking        = False
        self._speak_thread    = None
        self._interrupt_event = threading.Event()

    # ── Boot sequence ─────────────────────────────────────────────────────────

    def boot(self) -> bool:
        print("[Spine] Booting Friday 3.0...")
        ok = True

        # 1. Signal bus (must be first)
        try:
            from core.infra.friday_signal import get_bus
            self._bus = get_bus()
            print("[Spine] ✓ Signal bus")
        except Exception as e:
            print(f"[Spine] ✗ Signal bus: {e}")
            ok = False

        # 2. Brain
        try:
            from core.brain.friday_brain import FridayBrain
            self._brain = FridayBrain()
            print("[Spine] ✓ Brain")
        except Exception as e:
            print(f"[Spine] ✗ Brain: {e}")
            ok = False

        # 3. World (background — non-fatal)
        try:
            from  core.knowledge.friday_world import start as world_start
            world_start(env_interval=15, knowledge_interval=300)
            print("[Spine] ✓ World")
        except Exception as e:
            print(f"[Spine] ○ World: {e}")

        # 4. Voice
        try:
            from core.voice.friday_voice import FridayVoice
            self._voice = FridayVoice()
            print("[Spine] ✓ Voice")
        except Exception as e:
            print(f"[Spine] ○ Voice: {e}")

        # 5. Action
        try:
            from core.io.friday_action import FridayAction
            self._action = FridayAction()
            print("[Spine] ✓ Action")
        except Exception as e:
            print(f"[Spine] ○ Action: {e}")

        # 6. Notify
        try:
            from core.io.friday_notify import FridayNotify
            self._notify = FridayNotify()
            print("[Spine] ✓ Notify")
        except Exception as e:
            print(f"[Spine] ○ Notify: {e}")

        # 7. Wire signal handlers
        self._wire_signals()

        # 8. Scheduler
        try:
            from core.infra.friday_scheduler import start as sched_start, every_minutes, task_heartbeat
            every_minutes(5, task_heartbeat, "heartbeat")
            sched_start()
            print("[Spine] ✓ Scheduler")
        except Exception as e:
            print(f"[Spine] ○ Scheduler: {e}")

        # 9. Codex self-improvement agent (24/7 self-check → proposals for review)
        try:
            from core.agents.friday_codex_agent import start as codex_start
            codex_start()
            print("[Spine] ✓ Codex agent")
        except Exception as e:
            print(f"[Spine] ○ Codex agent: {e}")

        # 10. Proactive screen watcher (offers help when you look stuck)
        try:
            from core.io.friday_proactive import start as proactive_start
            proactive_start()
            print("[Spine] ✓ Proactive watcher")
        except Exception as e:
            print(f"[Spine] ○ Proactive watcher: {e}")

        print(f"[Spine] Boot complete — {'OK' if ok else 'DEGRADED'}")
        return ok

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _wire_signals(self) -> None:
        if not self._bus:
            return
        try:
            from core.infra.friday_signal import Signal

            async def on_thinking_done(event):
                text = event.data
                if text and self._voice:
                    threading.Thread(
                        target=self._voice.say,
                        args=(text,),
                        daemon=True
                    ).start()

            async def on_action_execute(event):
                if self._action and event.data:
                    cmd  = event.data.get("command", "")
                    args = event.data.get("args", {})
                    if cmd:
                        threading.Thread(
                            target=self._action.execute,
                            args=(cmd, args),
                            daemon=True
                        ).start()

            async def on_module_error(event):
                log.error("Module error: %s", event.data)
                if self._notify:
                    self._notify.send(
                        title   = "Friday Error",
                        message = str(event.data)[:100],
                    )

            self._bus.on(Signal.THINKING_DONE,  on_thinking_done)
            self._bus.on(Signal.ACTION_EXECUTE,  on_action_execute)
            self._bus.on(Signal.MODULE_ERROR,    on_module_error)
            log.info("Signals wired")
        except Exception as e:
            log.warning("Signal wiring failed: %s", e)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def respond(self, text: str) -> str:
        """Direct text-in / text-out. Used by voice loop and UI."""
        if self._brain:
            return self._brain.respond(text)
        return "Brain offline."

    # ── Interruptible speech (ported from v2) ─────────────────────────────────

    def say(self, text: str, interruptible: bool = True) -> None:
        """Speak text. If interruptible=True, can be cut off mid-sentence."""
        if not self._voice:
            print(f"[Friday] {text}")
            return
        if interruptible:
            self._speak_interruptible(text)
        else:
            self._voice.say(text)

    def _speak_interruptible(self, text: str) -> None:
        """Speak sentence-by-sentence. Stops immediately on interrupt."""
        import re
        self._interrupt_event.clear()
        self._speaking = True

        def _do():
            try:
                sentences = re.split(r'(?<=[.!?])\s+', text.strip()) or [text]
                for sentence in sentences:
                    if self._interrupt_event.is_set():
                        log.debug("Speech interrupted")
                        break
                    if self._voice:
                        self._voice.say(sentence)
            finally:
                self._speaking = False

        self._speak_thread = threading.Thread(target=_do, daemon=True, name="spine-speak")
        self._speak_thread.start()

    def interrupt_speech(self) -> None:
        """Stop Friday mid-sentence."""
        if self._speaking:
            self._interrupt_event.set()
            if self._speak_thread:
                self._speak_thread.join(timeout=1.0)
            self._speaking = False

    def run_voice_loop(self) -> None:
        """Blocking voice interaction loop."""
        try:
            from core.voice.friday_senses import FridaySenses
            senses = FridaySenses()
        except Exception as e:
            print(f"[Spine] Voice loop failed to start: {e}")
            return

        self.say(self._brain.greeting() if self._brain else "Friday online.")
        self._running = True

        while self._running:
            try:
                text = senses.listen_for_command(
                    should_run=lambda: self._running
                )
                if not text:
                    continue
                print(f"\n[User] {text}")
                response = self.respond(text)
                if response == "__EXIT__":
                    self.say("Shutting down. Goodbye.")
                    break
                self.say(response)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error("Voice loop error: %s", e)

        self.shutdown()

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._running = False
        self.interrupt_speech()
        try:
            from core.knowledge.friday_world import stop as world_stop
            world_stop()
        except Exception:
            pass
        try:
            from core.infra.friday_scheduler import stop as sched_stop
            sched_stop()
        except Exception:
            pass
        try:
            from core.agents.friday_codex_agent import stop as codex_stop
            codex_stop()
        except Exception:
            pass
        try:
            from core.io.friday_proactive import stop as proactive_stop
            proactive_stop()
        except Exception:
            pass
        if self._brain:
            self._brain.end_session("spine shutdown")
        print("[Spine] Shutdown complete")

    def status(self) -> dict:
        return {
            "running":   self._running,
            "brain":     self._brain is not None,
            "voice":     self._voice is not None,
            "action":    self._action is not None,
            "notify":    self._notify is not None,
            "world":     self._world is not None,
        }
# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    spine = FridaySpine()
    if spine.boot():
        spine.run_voice_loop()
    else:
        print("[Spine] Boot failed — check config and API keys")
        sys.exit(1)