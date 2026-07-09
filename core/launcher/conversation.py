"""
core/launcher/conversation.py — FRIDAY 5.x (Phase A)
The conversation bridge: the single seam between the listening pipeline and the
cognitive stack on the production boot path. It implements the pipeline's
intelligence protocol (`think(command, context)`), delegates to the Intelligence
OS, records one DecisionLog row per voice turn, and speaks the answer aloud —
without ever blocking the real-time audio thread.

Uncertainty rules (docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md §6):
  · heard badly  → ask for clarification instead of guessing
  · thought badly → think harder locally (a second, collaborative reasoning
    pass over the local model team), visible in the DecisionLog route
  · still unsure → the temporary teacher (M30): an owner-enabled, config-gated
    cloud consult whose answer is learned back into memory so the next similar
    question is answered locally — the teacher tier is scaffolding that is
    meant to fall out of use, and every consult shows in the route

Speech is interruptible: sentences are spoken one at a time and barge-in
(the user starting to speak) stops FRIDAY mid-answer.

No 3.0 brain modules are imported here; this is the launcher-path replacement
for `friday_brain.respond()`.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("friday.launcher.conversation")

_CLARIFY_ANSWER = "Sorry, I didn't catch that clearly. Could you say it again?"


class _SpeechOutput:
    """Serialized, non-blocking, interruptible TTS playback on a daemon worker
    thread. Text is spoken sentence by sentence so `interrupt()` (barge-in) can
    stop FRIDAY mid-answer. The synthesizer is constructed lazily so missing
    audio backends (edge-tts / pygame) degrade to silence instead of failing
    the boot."""

    def __init__(self, synthesizer: Optional[Callable[[str], None]] = None,
                 stopper: Optional[Callable[[], None]] = None) -> None:
        self._synth = synthesizer
        self._stopper = stopper
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=8)
        self._worker: Optional[threading.Thread] = None
        self._interrupt = threading.Event()
        self._lock = threading.Lock()
        self.spoken = 0
        self.dropped = 0
        self.interrupted = 0

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run, name="friday-speech", daemon=True)
                self._worker.start()

    def _synthesize(self, text: str) -> None:
        if self._synth is None:
            from core.voice.friday_voice import FridayVoice
            voice = FridayVoice()
            self._synth = voice.say
        self._synth(text)

    @staticmethod
    def _sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [p for p in parts if p] or [text]

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                return
            self._interrupt.clear()
            for sentence in self._sentences(text):
                if self._interrupt.is_set():
                    break
                try:
                    self._synthesize(sentence)
                except Exception:  # noqa: BLE001 — audio output is best-effort
                    log.debug("speech synthesis failed", exc_info=True)
                    break
            else:
                self.spoken += 1

    def say(self, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False
        self._ensure_worker()
        try:
            self._queue.put_nowait(text)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def interrupt(self) -> None:
        """Barge-in: stop the current utterance and drop anything queued."""
        self._interrupt.set()
        self.interrupted += 1
        while True:                       # drop pending utterances
            try:
                if self._queue.get_nowait() is None:
                    self._queue.put_nowait(None)   # preserve shutdown sentinel
                    break
            except queue.Empty:
                break
        stopper = self._stopper
        if stopper is None:
            stopper = self._stop_playback
        try:
            stopper()
        except Exception:  # noqa: BLE001
            log.debug("playback stop failed", exc_info=True)

    @staticmethod
    def _stop_playback() -> None:
        import sys
        pygame = sys.modules.get("pygame")
        if pygame is not None and pygame.mixer.get_init():
            pygame.mixer.music.stop()

    def stop(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass


class ConversationBridge:
    """Adapts the Intelligence OS to the listening pipeline's `think()` protocol
    and makes every voice turn observable: one DecisionLog row per turn, answer
    spoken asynchronously, uncertainty handled instead of ignored."""

    def __init__(self, ios, *, decision_log=None, speech: Optional[_SpeechOutput] = None,
                 memory=None, self_model=None, goals=None, teacher=None,
                 speak_answers: bool = True,
                 clarify_threshold: float = 0.35,
                 escalate_threshold: float = 0.55) -> None:
        self.ios = ios
        self.memory = memory                # M2 MemoryService (One Memory, Phase C)
        self.self_model = self_model        # Self Model (Internal Mind, M23)
        self.goals = goals                  # GoalService (proposal gate, M28)
        self.teacher = teacher              # temporary cloud teacher (M30)
        from core.memory.learning_gate import LearningGate
        self.gate = LearningGate()          # selective learning (M27)
        self.speech = speech if speech is not None else _SpeechOutput()
        self.speak_answers = speak_answers
        self.clarify_threshold = clarify_threshold
        self.escalate_threshold = escalate_threshold
        self._decision_log = decision_log
        self._turn = 0
        self._escalations = 0
        self._clarifications = 0
        self._teacher_turns = 0
        self._pending_approval: Optional[tuple] = None   # (goal_id, title, expires_at)
        self._lock = threading.Lock()

    def _log(self):
        if self._decision_log is None:
            from core.observability.decision_log import get_decision_log
            self._decision_log = get_decision_log()
        return self._decision_log

    def _next_turn(self) -> int:
        with self._lock:
            self._turn += 1
            return self._turn

    def _record(self, *, turn: int, route: list, response, latency_ms: int,
                memory_used: Optional[list] = None) -> None:
        try:
            self._log().log(
                trace_id=getattr(response, "trace_id", None) or None,
                turn_id=turn,
                intent=getattr(response, "task", None),
                route=route,
                models_used=list(getattr(response, "models_used", []) or []),
                memory_used=memory_used or [],
                confidence=float(getattr(response, "confidence", 0.0) or 0.0),
                latency_ms=latency_ms,
                outcome=(getattr(response, "answer", "") or "")[:400],
                rationale="voice turn routed through the Intelligence OS",
                was_autonomous=False,
                source="voice",
            )
        except Exception:  # noqa: BLE001 — observability must not break a turn
            log.debug("decision log write failed", exc_info=True)

    def _introspect(self, command: str) -> Optional[str]:
        """Truthful first-person answers straight from the Self Model."""
        if self.self_model is None:
            return None
        q = (command or "").lower()
        try:
            if re.search(r"\bwhat (are you|r u) doing\b", q):
                return self.self_model.what_am_i_doing()
            if re.search(r"\bwhat can you (do|help)\b", q):
                return self.self_model.what_can_i_do()
            if re.search(r"\bwhat (can'?t|cannot) you do\b", q):
                return self.self_model.what_cant_i_do()
        except Exception:  # noqa: BLE001
            log.debug("self model introspection failed", exc_info=True)
        return None

    _APPROVAL_TTL_S = 60.0

    def _proposals(self, command: str) -> Optional[str]:
        """Voice gate for FRIDAY's self-proposed goals (M28): list, approve,
        reject — always the oldest open proposal first.

        Adversarial hardening (M29): approval is two-step — FRIDAY names the
        proposal and waits for an explicit 'confirm' within 60 s, so a stray
        phrase from a guest, a video, or her own speaker output can't wave a
        goal through. Any other command cancels the pending confirmation;
        rejection stays one-step (fail-safe direction)."""
        if self.goals is None:
            return None
        q = (command or "").lower()

        # a pending approval waits for exactly one thing: an explicit confirm
        pending = self._pending_approval
        if pending is not None:
            self._pending_approval = None            # single-shot, always cleared
            goal_id, title, expires_at = pending
            if time.time() <= expires_at:
                if re.search(r"\b(confirm|confirmed|go ahead|do it)\b", q):
                    try:
                        if self.goals.approve_proposal(goal_id) is not None:
                            return f"Confirmed — I'll start working on: {title}."
                    except Exception:  # noqa: BLE001
                        log.debug("proposal approval failed", exc_info=True)
                    return "I couldn't approve that proposal — it's no longer open."
                if re.search(r"\b(cancel|no|don'?t|never ?mind|stop)\b", q):
                    return f"Okay, I'll leave the proposal '{title}' waiting."
            # anything else falls through to normal handling, confirmation dropped

        wants_list = re.search(r"\b(any|your|what|list|pending)\b.*\bpropos", q) or \
            re.search(r"\bpropos\w*\b.*\b(goals?|anything)\b", q)
        wants_approve = re.search(r"\b(approve|accept|go ahead with)\b.*\bpropos", q)
        wants_reject = re.search(r"\b(reject|decline|dismiss)\b.*\bpropos", q)
        if not (wants_list or wants_approve or wants_reject):
            return None
        try:
            open_props = self.goals.list_proposals()
            if wants_approve or wants_reject:
                if not open_props:
                    return "I have no open proposals right now."
                goal = open_props[0]
                if wants_approve:
                    self._pending_approval = (goal.goal_id, goal.title,
                                              time.time() + self._APPROVAL_TTL_S)
                    return (f"Just to be sure — approve '{goal.title}'? "
                            f"Say 'confirm' and I'll start on it.")
                self.goals.reject_proposal(goal.goal_id, reason="rejected by voice")
                return f"Understood, I've dropped the proposal: {goal.title}."
            if not open_props:
                return "I have no goal proposals at the moment."
            titles = "; ".join(g.title for g in open_props[:3])
            return (f"I have {len(open_props)} proposal"
                    f"{'s' if len(open_props) != 1 else ''} waiting for your "
                    f"approval: {titles}.")
        except Exception:  # noqa: BLE001
            log.debug("proposal handling failed", exc_info=True)
            return None

    def _respond_directly(self, turn: int, source: str, answer: str, t0: float):
        from core.intelligence.router import RouterResponse
        response = RouterResponse(task=source, complexity="trivial",
                                  strategy=source, ok=True, answer=answer,
                                  confidence=0.95)
        self._record(turn=turn, route=[source], response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000))
        if self.speak_answers:
            self.speech.say(answer)
        return response

    def _clarify(self, turn: int, heard: float, t0: float):
        from core.intelligence.router import RouterResponse
        response = RouterResponse(task="clarify", complexity="trivial",
                                  strategy="clarify", ok=True,
                                  answer=_CLARIFY_ANSWER, confidence=heard)
        self._clarifications += 1
        self._record(turn=turn, route=["clarify"], response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000))
        if self.speak_answers:
            self.speech.say(response.answer)
        return response

    # ── the pipeline's intelligence protocol ─────────────────────────────────────
    def think(self, command: str, context: Optional[dict] = None):
        t0 = time.perf_counter()
        turn = self._next_turn()
        ctx = dict(context or {})

        # heard badly → ask again instead of guessing
        heard = ctx.get("audio_confidence")
        if heard is not None and float(heard) < self.clarify_threshold:
            return self._clarify(turn, float(heard), t0)

        # self-questions are answered from the Self Model, not a language model
        introspective = self._introspect(command)
        if introspective is not None:
            return self._respond_directly(turn, "self_model", introspective, t0)

        # goal proposals (M28): list / approve / reject straight from the store
        proposal_answer = self._proposals(command)
        if proposal_answer is not None:
            return self._respond_directly(turn, "goal_proposals", proposal_answer, t0)

        # memory retrieval happens before reasoning (provenance for the DecisionLog)
        memory_used: list = []
        if self.memory is not None:
            try:
                memory_used = [m.get("id") for m in self.memory.recall(command, k=5)
                               if isinstance(m, dict) and m.get("id") is not None]
            except Exception:  # noqa: BLE001
                log.debug("memory recall failed", exc_info=True)

        response = self.ios.think(command, context=ctx)
        route = [getattr(response, "strategy", "") or "intelligence_os"]

        # thought badly → think harder, still locally: a second, collaborative
        # pass over the local model team (visible in the route)
        weak = (not getattr(response, "ok", False)
                or float(getattr(response, "confidence", 0.0) or 0.0) < self.escalate_threshold)
        if weak:
            try:
                deeper = self.ios.think(command, context=ctx, collaborate=True,
                                        build_context=False)
            except Exception:  # noqa: BLE001 — the first answer still stands
                deeper = None
            if deeper is not None and getattr(deeper, "ok", False) and \
                    float(getattr(deeper, "confidence", 0.0) or 0.0) > \
                    float(getattr(response, "confidence", 0.0) or 0.0):
                response = deeper
                route.append("deep_reasoning")
                self._escalations += 1

        # still unsure after both local passes → consult the temporary teacher
        # (M30); its answer replaces hers AND is learned back into memory below,
        # so this branch is designed to fire less and less over time
        still_weak = (not getattr(response, "ok", False)
                      or float(getattr(response, "confidence", 0.0) or 0.0)
                      < self.escalate_threshold)
        if still_weak and self.teacher is not None and self.teacher.available():
            taught = self.teacher.ask(command)
            if taught.ok:
                from core.intelligence.router import RouterResponse
                response = RouterResponse(
                    task=getattr(response, "task", "general") or "general",
                    complexity="taught", strategy="groq_teacher", ok=True,
                    answer=taught.answer, confidence=0.85,
                    models_used=[f"groq:{taught.model}"],
                    latency_ms=taught.latency_ms)
                route.append("groq_teacher")
                self._teacher_turns += 1

        self._record(turn=turn, route=route, response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000),
                     memory_used=memory_used)

        # selective learning: the gate decides what (if anything) becomes memory —
        # explicit requests + personal info stored (private, local), noise dropped
        answer = getattr(response, "answer", "") or ""
        decision = self.gate.decide(
            command, answer,
            confidence=float(getattr(response, "confidence", 0.0) or 0.0),
            route=tuple(route))
        self.gate.apply(self.memory, decision, command, answer)

        if self.speak_answers and getattr(response, "ok", False):
            self.speech.say(getattr(response, "answer", ""))
        return response

    # ── announcements (runtime SPEAK_START handler) ──────────────────────────────
    def announce(self, text: str) -> bool:
        return self.speech.say(text)

    def interrupt(self) -> None:
        """Barge-in: the user started speaking — stop talking and listen."""
        self.speech.interrupt()

    def status(self) -> dict:
        return {"turns": self._turn, "spoken": self.speech.spoken,
                "dropped": self.speech.dropped,
                "interrupted": self.speech.interrupted,
                "clarifications": self._clarifications,
                "escalations": self._escalations,
                "teacher_turns": self._teacher_turns,
                "teacher": self.teacher.status() if self.teacher else {"enabled": False},
                "learning": self.gate.status()}

    def close(self) -> None:
        self.speech.stop()
