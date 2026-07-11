"""
core/voice/friday_voice_loop.py — Friday 3.0
The minimal mic-in / voice-out loop: FridaySenses (VAD capture + whisper) →
Intelligence OS → FridayVoice. This is the quick end-to-end harness for
testing her hearing and voice; the PRODUCTION path is the launcher's M31
listening pipeline + conversation bridge, not this loop.

(History: this file's original loop was accidentally overwritten with a copy
of setup.py — which ran pip installs and a blocking input() at import. This
restores its documented role, guarded and side-effect-free to import.)

    python -m core.voice.friday_voice_loop
"""

from __future__ import annotations

_EXIT_WORDS = {"exit", "quit", "goodbye", "shut down", "shutdown"}


def main() -> int:
    from core.intelligence.service import think_text
    from core.voice.friday_senses import FridaySenses
    from core.voice.friday_voice import FridayVoice

    senses = FridaySenses()
    voice = FridayVoice()
    print("[voice-loop] Speak when ready — say 'goodbye' or Ctrl+C to exit.")
    try:
        while True:
            heard = senses.listen_for_command()
            if not heard:
                continue
            print(f"[You] {heard}")
            if heard.lower().strip(" .!?") in _EXIT_WORDS:
                voice.say("Goodbye.")
                return 0
            answer = think_text(heard)
            voice.say(answer or "I don't have an answer for that yet.")
    except KeyboardInterrupt:
        return 0
    finally:
        senses.stop()


if __name__ == "__main__":
    raise SystemExit(main())
