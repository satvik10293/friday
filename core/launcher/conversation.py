"""
core/launcher/conversation.py — FRIDAY 5.x (Phase A)
The conversation bridge: the single seam between the listening pipeline and the
cognitive stack on the production boot path. It implements the pipeline's
intelligence protocol (`think(command, context)`), delegates to the Intelligence
OS, records one DecisionLog row per voice turn, and speaks the answer aloud —
without ever blocking the real-time audio thread.

Routing (M42, owner-directed): the BASIC REASONER IS THE CLOUD. Substantive,
non-personal questions go to a frontier model first (`cloud_reasoner`),
grounded in the conversation window plus privacy-filtered local memories.
Personal-shaped questions never leave the box, and the full local chain
remains the fallback whenever the cloud is off, keyless, or unreachable:

Uncertainty rules for the local chain (docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md §6):
  · heard badly  → ask for clarification instead of guessing
  · thought badly → think harder locally (a second, collaborative reasoning
    pass over the local model team), visible in the DecisionLog route
  · still unsure → the librarian (M40), then the teacher (M30): a config-gated
    cloud consult whose answer is learned back into memory — skipped when the
    cloud reasoner already failed this turn (same infrastructure)

Speech is interruptible: sentences are spoken one at a time and barge-in
(the user starting to speak) stops FRIDAY mid-answer.

No 3.0 brain modules are imported here; this is the launcher-path replacement
for `friday_brain.respond()`.
"""

from __future__ import annotations

import difflib
import logging
import queue
import re
import threading
import time
from collections import deque
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
                 knowledge=None, reasoner=None,
                 speak_answers: bool = True,
                 clarify_threshold: float = 0.35,
                 escalate_threshold: float = 0.55) -> None:
        self.ios = ios
        self.memory = memory                # M2 MemoryService (One Memory, Phase C)
        self.self_model = self_model        # Self Model (Internal Mind, M23)
        self.goals = goals                  # GoalService (proposal gate, M28)
        self.teacher = teacher              # temporary cloud teacher (M30)
        self.knowledge = knowledge          # M7 KnowledgeService → librarian (M40)
        self.reasoner = reasoner            # cloud-primary basic reasoner (M42)
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
        self._librarian_turns = 0
        self._cloud_turns = 0
        self._echoes_dropped = 0
        self._noise_dropped = 0
        self._last_clarify_ts = 0.0
        self._recent_speech: deque = deque(maxlen=8)   # (normalized text, ts)
        # conversation window: the last few (role, text) turns, so follow-up
        # questions have an anchor — passed into reasoning context and (privacy
        # aside) to the teacher for pronoun resolution
        self._window: deque = deque(maxlen=6)
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

    # ── keeping her own voice and room noise out of the conversation ─────────────
    _ECHO_WINDOW_S = 45.0
    _ECHO_RATIO = 0.72
    _CLARIFY_COOLDOWN_S = 20.0

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()

    def _say(self, text: str) -> None:
        """All speech goes through here so the bridge remembers what SHE said —
        the mic will hear it again, and she must not answer herself."""
        text = (text or "").strip()
        if not text:
            return
        self._recent_speech.append((self._norm(text), time.time()))
        self.speech.say(text)

    def _is_self_echo(self, command: str) -> bool:
        cmd = self._norm(command)
        if len(cmd) < 8:
            return False
        now = time.time()
        for spoken, ts in self._recent_speech:
            if now - ts > self._ECHO_WINDOW_S:
                continue
            if cmd in spoken:                          # STT caught a fragment
                return True
            if difflib.SequenceMatcher(None, cmd, spoken).ratio() > self._ECHO_RATIO:
                return True
        return False

    def _drop(self, turn: int, kind: str, heard: float, t0: float):
        """Silently ignore a turn (self-echo / repeated noise): logged for
        observability, nothing spoken."""
        from core.intelligence.router import RouterResponse
        response = RouterResponse(task=kind, complexity="trivial", strategy=kind,
                                  ok=True, answer="", confidence=heard)
        self._record(turn=turn, route=[kind], response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000))
        return response

    def _respond_directly(self, turn: int, source: str, answer: str, t0: float,
                          command: str = ""):
        from core.intelligence.router import RouterResponse
        response = RouterResponse(task=source, complexity="trivial",
                                  strategy=source, ok=True, answer=answer,
                                  confidence=0.95)
        self._record(turn=turn, route=[source], response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000))
        if command:
            self._remember_turn(command, answer)
        if self.speak_answers:
            self._say(answer)
        return response

    def _remember_turn(self, command: str, answer: str) -> None:
        self._window.append({"role": "user", "text": (command or "")[:200]})
        if (answer or "").strip():
            self._window.append({"role": "friday", "text": answer.strip()[:200]})

    @staticmethod
    def _is_personal(command: str) -> bool:
        """Personal-shaped questions are answered locally — their answers live
        in local (often private) memory and must not leave the box. Shares the
        librarian's pattern so 'personal' means one thing everywhere."""
        try:
            from core.memory.learning_gate import _PERSONAL_RE
        except ImportError:
            return False
        return bool(_PERSONAL_RE.search(command or ""))

    def _cloud_pass(self, command: str):
        """(M42) The basic reasoner: one cloud turn grounded in the
        conversation window plus privacy-filtered local memories. Returns
        (RouterResponse, memory_used_ids) on success, (None, []) otherwise —
        the local chain then runs exactly as before."""
        facts: list[str] = []
        memory_used: list = []
        if self.memory is not None:
            try:
                for m in self.memory.recall(command, k=6):
                    if isinstance(m, dict) and m.get("private") is False \
                            and (m.get("content") or "").strip():
                        facts.append(m["content"])
                        if m.get("id") is not None:
                            memory_used.append(m["id"])
            except Exception:  # noqa: BLE001 — grounding is best-effort
                log.debug("memory recall for cloud pass failed", exc_info=True)
        reasoned = self.reasoner.reason(command, context={
            "recent_turns": list(self._window), "facts": facts[:5]})
        if not getattr(reasoned, "ok", False):
            return None, []
        from core.intelligence.router import RouterResponse
        response = RouterResponse(
            task="general", complexity="cloud", strategy="cloud_reasoner",
            ok=True, answer=reasoned.answer, confidence=0.9,
            models_used=[f"groq:{reasoned.model}"],
            latency_ms=reasoned.latency_ms)
        return response, memory_used

    def _consult_librarian(self, command: str, reasoned_ctx: dict):
        """Look the question up in the world's reference library (M7 bridge →
        wikipedia) and ground HER OWN reader on the fetched extract. Returns a
        confident grounded response, or None (→ the teacher gets its turn).

        Personal-shaped questions never trigger a fetch — the library holds
        world knowledge, and personal context must not leave the box."""
        try:
            from core.memory.learning_gate import _PERSONAL_RE
            if _PERSONAL_RE.search(command or ""):
                return None
        except ImportError:
            pass
        try:
            result = self.knowledge.resolve(command, allow_external=True)
        except Exception:  # noqa: BLE001 — the librarian must never break a turn
            log.debug("librarian lookup failed", exc_info=True)
            return None
        candidate = (result or {}).get("candidate")
        if candidate is None or not (candidate.content or "").strip():
            return None

        ctx = {"query": command,
               "memories": list(reasoned_ctx.get("memories", []) or []),
               "knowledge": [{"title": candidate.title,
                              "content": candidate.content,
                              "confidence": 0.7}]}
        try:
            grounded = self.ios.think(command, context=ctx, build_context=False,
                                      use_mini_brains=False)
        except Exception:  # noqa: BLE001
            log.debug("librarian grounding failed", exc_info=True)
            return None
        if not getattr(grounded, "ok", False) or \
                float(getattr(grounded, "confidence", 0.0) or 0.0) < self.escalate_threshold:
            return None

        # the distilled extract becomes validated knowledge — the next similar
        # question is answered locally, no network (the flywheel, with sources)
        try:
            self.knowledge.learn(candidate.content, title=candidate.title,
                                 confidence=0.7, source="wikipedia")
        except Exception:  # noqa: BLE001
            log.debug("librarian learn-back failed", exc_info=True)
        return grounded

    def _teacher_context(self, reasoned_ctx: dict) -> dict:
        """Only what may leave the box: the conversation window plus memories
        NOT marked private. Anything without an explicit private=False stays
        local (unknown provenance is treated as private)."""
        facts = [m.get("content") for m in reasoned_ctx.get("memories", [])
                 if isinstance(m, dict) and m.get("private") is False
                 and (m.get("content") or "").strip()]
        return {"recent_turns": list(self._window), "facts": facts[:5]}

    def _clarify(self, turn: int, heard: float, t0: float):
        # ask once, then stay quiet: a noisy room must not become a nag loop
        now = time.time()
        if now - self._last_clarify_ts < self._CLARIFY_COOLDOWN_S:
            self._noise_dropped += 1
            return self._drop(turn, "noise", heard, t0)
        self._last_clarify_ts = now
        from core.intelligence.router import RouterResponse
        response = RouterResponse(task="clarify", complexity="trivial",
                                  strategy="clarify", ok=True,
                                  answer=_CLARIFY_ANSWER, confidence=heard)
        self._clarifications += 1
        self._record(turn=turn, route=["clarify"], response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000))
        if self.speak_answers:
            self._say(response.answer)
        return response

    # ── the pipeline's intelligence protocol ─────────────────────────────────────
    def think(self, command: str, context: Optional[dict] = None):
        t0 = time.perf_counter()
        turn = self._next_turn()
        ctx = dict(context or {})

        # the mic hears her too — never answer her own recent speech
        if self._is_self_echo(command):
            self._echoes_dropped += 1
            return self._drop(turn, "self_echo", 1.0, t0)

        # heard badly → ask again instead of guessing (once, then stay quiet)
        heard = ctx.get("audio_confidence")
        if heard is not None and float(heard) < self.clarify_threshold:
            return self._clarify(turn, float(heard), t0)

        # self-questions are answered from the Self Model, not a language model
        introspective = self._introspect(command)
        if introspective is not None:
            return self._respond_directly(turn, "self_model", introspective, t0,
                                          command=command)

        # goal proposals (M28): list / approve / reject straight from the store
        proposal_answer = self._proposals(command)
        if proposal_answer is not None:
            return self._respond_directly(turn, "goal_proposals", proposal_answer,
                                          t0, command=command)

        # the conversation window rides along so follow-ups have an anchor
        ctx["recent_turns"] = list(self._window)

        # (M42) the BASIC REASONER IS THE CLOUD: substantive, non-personal
        # questions ask a frontier model first, grounded in the window plus
        # privacy-filtered memories. Personal questions stay local, and a
        # cloud failure falls through to the full local chain below.
        response = None
        route: list = []
        memory_used: list = []
        cloud_tried = False
        if self.reasoner is not None and self.reasoner.available() \
                and not self._is_personal(command):
            cloud_tried = True
            response, memory_used = self._cloud_pass(command)
            if response is not None:
                route.append("cloud_reasoner")
                self._cloud_turns += 1

        if response is None:
            response = self.ios.think(command, context=ctx)
            route.append(getattr(response, "strategy", "") or "intelligence_os")

            # provenance comes from the context the models actually reasoned
            # over — a single retrieval per turn serves reasoning, the
            # DecisionLog, and any escalation pass below
            reasoned_ctx = dict(getattr(response, "context_used", None) or ctx)
            memory_used = [m.get("id") for m in reasoned_ctx.get("memories", [])
                           if isinstance(m, dict) and m.get("id") is not None]

            # thought badly → think harder, still locally: a second,
            # collaborative pass over the local model team (visible in the
            # route), reasoning over the SAME retrieved memories/knowledge
            weak = (not getattr(response, "ok", False)
                    or float(getattr(response, "confidence", 0.0) or 0.0)
                    < self.escalate_threshold)
            if weak:
                try:
                    deeper = self.ios.think(command, context=reasoned_ctx,
                                            collaborate=True, build_context=False)
                except Exception:  # noqa: BLE001 — the first answer still stands
                    deeper = None
                if deeper is not None and getattr(deeper, "ok", False) and \
                        float(getattr(deeper, "confidence", 0.0) or 0.0) > \
                        float(getattr(response, "confidence", 0.0) or 0.0):
                    response = deeper
                    route.append("deep_reasoning")
                    self._escalations += 1

            # still unsure after both local passes → the LIBRARIAN first (M40):
            # fetch a real reference source (wikipedia, via the M7 documentation
            # bridge) and let HER OWN reader answer from it — provenance over
            # generation. Only if the library has nothing does the teacher speak.
            still_weak = (not getattr(response, "ok", False)
                          or float(getattr(response, "confidence", 0.0) or 0.0)
                          < self.escalate_threshold)
            if still_weak and self.knowledge is not None:
                looked_up = self._consult_librarian(command, reasoned_ctx)
                if looked_up is not None:
                    response = looked_up
                    route.append("librarian")
                    self._librarian_turns += 1
                    still_weak = False

            # (M30) temporary teacher; its answer replaces hers AND is learned
            # back into memory below. Skipped when the cloud reasoner already
            # failed this turn — it is the same infrastructure, and a second
            # timeout would only add dead air.
            if still_weak and not cloud_tried and self.teacher is not None \
                    and self.teacher.available():
                taught = self.teacher.ask(
                    command, context=self._teacher_context(reasoned_ctx))
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

        if getattr(response, "ok", False):
            self._remember_turn(command, answer)
        if self.speak_answers and getattr(response, "ok", False):
            self._say(getattr(response, "answer", ""))
        return response

    # ── announcements (runtime SPEAK_START handler) ──────────────────────────────
    def announce(self, text: str) -> bool:
        self._recent_speech.append((self._norm(text), time.time()))
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
                "librarian_turns": self._librarian_turns,
                "cloud_turns": self._cloud_turns,
                "echoes_dropped": self._echoes_dropped,
                "noise_dropped": self._noise_dropped,
                "reasoner": self.reasoner.status() if self.reasoner
                else {"primary": "local"},
                "teacher": self.teacher.status() if self.teacher else {"enabled": False},
                "learning": self.gate.status()}

    def close(self) -> None:
        self.speech.stop()
