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
                 stopper: Optional[Callable[[], None]] = None,
                 on_spoken: Optional[Callable[[], None]] = None) -> None:
        self._synth = synthesizer
        self._stopper = stopper
        # fired when an utterance finishes speaking — lets the bridge reopen the
        # follow-up window from when she STOPS talking, not when she starts
        self._on_spoken = on_spoken
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
                    break                        # deliberate barge-in: stop now
                try:
                    self._synthesize(sentence)
                except Exception:  # noqa: BLE001 — audio output is best-effort
                    # one sentence failing (a network blip) must not swallow the
                    # rest of her answer — skip it and keep speaking
                    log.debug("speech synthesis failed on a sentence", exc_info=True)
                    continue
            else:
                self.spoken += 1
                if self._on_spoken is not None:
                    try:
                        self._on_spoken()
                    except Exception:  # noqa: BLE001 — a hook never breaks speech
                        log.debug("on_spoken hook failed", exc_info=True)

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
                 knowledge=None, reasoner=None, local_reasoner=None,
                 distiller=None, neural=None, core_memory=None, brains=None,
                 conversation_state=None, skills=None, overlay=None, agentic=None,
                 harness=None,
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
        self.harness = harness              # council over the user's AI subscriptions
        self.local_reasoner = local_reasoner  # her OWN local reasoning brain (M54)
        self.distiller = distiller          # the notebook trick (M55)
        self.neural = neural                # her own trained weights (M58)
        self.brains = dict(brains or {})    # addressable brain society (M46)
        self.skills = skills                # governed action executor (M47)
        self.overlay = overlay              # private on-screen overlay (M51)
        self.agentic = agentic              # autonomous goal workflow (M59)
        self._owner_name = self._get_owner_name()   # for natural small talk
        from core.memory.learning_gate import LearningGate
        self.gate = LearningGate()          # selective learning (M27)
        from core.verify import Verifier
        self.verifier = Verifier()          # verify gate, extracted from friday-v0
        if core_memory is not None:
            self.core = core_memory         # standing memory (M43)
        else:
            from core.memory.core_memory import get_core_memory
            self.core = get_core_memory()
        self.speech = speech if speech is not None else _SpeechOutput()
        # keep the hands-free follow-up window open from when she STOPS
        # speaking: on a slow CPU her own (long) reply used to eat an 8 s
        # window timed from when she started, so the user had to re-say
        # "Friday" every turn. Reopening on speech-completion makes it a real
        # back-and-forth conversation.
        self._conversation_state = conversation_state
        if conversation_state is not None and self.speech._on_spoken is None:
            self.speech._on_spoken = self._reopen_window
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
        self._local_turns = 0
        self._notebook_turns = 0
        self._skill_turns = 0
        self._screen_reads = 0
        self._echoes_dropped = 0
        self._noise_dropped = 0
        self._last_clarify_ts = 0.0
        self._recent_speech: deque = deque(maxlen=8)   # (normalized text, ts)
        # conversation window: the last few (role, text) turns, so follow-up
        # questions have an anchor — passed into reasoning context and (privacy
        # aside) to the teacher for pronoun resolution
        self._window: deque = deque(maxlen=6)
        self._pending_approval: Optional[tuple] = None   # (goal_id, title, expires_at)
        self._pending_paused: Optional[tuple] = None     # (goal_id, title, skill, expires_at)
        self._pending_command: Optional[tuple] = None    # (skill, args, describe, expires_at)
        self._pending_send: Optional[dict] = None        # a composed message await confirm
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
                memory_used: Optional[list] = None, verify=None) -> None:
        try:
            rationale = "voice turn routed through the Intelligence OS"
            if verify is not None:                 # the verify gate's verdict
                rationale += (f" · verify tier {verify.tier} {verify.verdict}"
                              f" ({verify.detail})")
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
                rationale=rationale,
                was_autonomous=False,
                source="voice",
            )
        except Exception:  # noqa: BLE001 — observability must not break a turn
            log.debug("decision log write failed", exc_info=True)

    # ── the verify stage (friday-v0's gate) ──────────────────────────────────────
    def _verify_answer(self, answer: str, response):
        """Rule one verdict on the answer the chat box produced. A spoken answer
        carries no machine-checkable criteria, so this is friday-v0's self-report
        tier over her OWN confidence — the gate module also carries v0's objective
        and second-model differential tiers for callers that supply criteria or a
        checker, but the turn path stays on-device and makes no extra model call.
        An answer she already disowns (`ok` is false) fails without a second look.
        Never raises — a verify fault defaults to success so it can't silently
        swallow her learning."""
        from core.verify import VerifyResult
        try:
            ok = bool(getattr(response, "ok", False))
            conf = float(getattr(response, "confidence", 0.0) or 0.0)
            return self.verifier.verify(artifact=answer,
                                        self_confidence=conf if ok else 0.0)
        except Exception:  # noqa: BLE001 — verify must never break a turn
            log.debug("verify stage failed", exc_info=True)
            return VerifyResult(success=True, verdict="unknown", tier=0,
                                detail="verify skipped")

    # ── small talk: greetings answered as herself, never parroted ────────────────
    @staticmethod
    def _get_owner_name() -> str:
        try:
            import json
            from pathlib import Path
            root = Path(__file__).resolve().parents[2]
            cfg = json.loads((root / "friday_config.json").read_text(encoding="utf-8"))
            return (cfg.get("owner_name") or "").strip()
        except Exception:  # noqa: BLE001 — a nameless greeting still works
            return ""

    _GREETING_RE = re.compile(
        r"^(?:hey|hi|hello|yo|hiya|howdy|sup|wassup|what'?s up|greetings|"
        r"good (?:morning|afternoon|evening))(?:\s+friday)?[\s!.,]*$", re.I)
    _HOWAREYOU_RE = re.compile(
        r"^(?:hey |hi |hello )?(?:friday[,\s]+)?how (?:are|r|'?re) (?:you|u|ya)"
        r"(?:\s+doing|\s+going)?[\s?!.]*$|^how'?s it going[\s?!.]*$|"
        r"^how do you feel[\s?!.]*$|^you (?:ok|okay|good|alright)[\s?!.]*$", re.I)
    _THANKS_RE = re.compile(
        r"^(?:thanks|thank you|thx|ty|cheers|appreciate it|nice one|"
        r"good job|well done)(?:\s+friday)?[\s!.,]*$", re.I)
    _BYE_RE = re.compile(
        r"^(?:bye|goodbye|good night|goodnight|see you|see ya|later|cya|"
        r"talk later|i'?m off)(?:\s+friday)?[\s!.,]*$", re.I)

    def _smalltalk(self, command: str) -> Optional[str]:
        """Greetings, thanks, farewells, and 'how are you' answered directly as
        herself — run FIRST so they never fall through to retrieval, which
        would parrot a stored conversation turn back at the owner. Returns the
        reply or None. Never raises."""
        q = (command or "").strip()
        if not q or len(q) > 40:                 # small talk is short
            return None
        name = self._owner_name
        who = f" {name}" if name else ""
        try:
            if self._GREETING_RE.match(q):
                hour = time.localtime().tm_hour
                part = ("Good morning" if 5 <= hour < 12 else
                        "Good afternoon" if 12 <= hour < 18 else "Good evening")
                low = q.lower()
                if low.startswith("good "):       # mirror their time-of-day
                    return f"{part}{who}. How can I help?"
                return f"Hey{who} — how can I help?"
            if self._THANKS_RE.match(q):
                return "Anytime."
            if self._BYE_RE.match(q):
                return f"Talk soon{who}."
            if self._HOWAREYOU_RE.match(q):
                return "I'm running well, thanks. What can I do for you?"
        except Exception:  # noqa: BLE001 — small talk must never break a turn
            log.debug("smalltalk failed", exc_info=True)
        return None

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

    # ── truthful self-assessment: how independent is she, really ─────────────────
    _INDEP_RE = re.compile(
        r"\bhow (?:independent|self.?sufficient) are you\b|"
        r"\bhow (?:often|much) do you (?:answer|think) (?:for )?yourself\b|"
        r"\bare you getting smarter\b|\bhow smart (?:are you getting|have you "
        r"(?:gotten|become))\b|\bhow much have you learn(?:ed|t)\b", re.I)

    def _independence(self, command: str) -> Optional[str]:
        """Answer 'are you getting smarter?' with MEASURED numbers — the
        DecisionLog's independence metric plus the notebook's growth — never a
        vibe. Returns None unless asked; never raises."""
        if not self._INDEP_RE.search(command or ""):
            return None
        try:
            stats = self._log().independence()
        except Exception:  # noqa: BLE001
            log.debug("independence query failed", exc_info=True)
            return None
        if not stats or not stats.get("total"):
            return ("I haven't made enough decisions to measure yet — "
                    "ask me again after we've talked a while.")
        pct = stats.get("independence_pct")
        answer = (f"Measured, not guessed: I've answered {pct}% of my "
                  f"{stats['total']} decisions entirely on my own, no cloud.")
        if self.distiller is not None:
            try:
                d = self.distiller.status()
                if d.get("distilled"):
                    n = d["distilled"]
                    answer += (f" I've also distilled {n} topic"
                               f"{'s' if n != 1 else ''} into my own knowledge"
                               + (f", with {d['pending']} more queued to study."
                                  if d.get("pending") else "."))
            except Exception:  # noqa: BLE001
                pass
        if self.neural is not None:
            try:                             # her own weights: the growth curve
                core = (self.neural.status() or {}).get("core") or {}
                if core.get("steps_trained"):
                    answer += (f" And my own neural core has trained "
                               f"{core['steps_trained']} steps on my life "
                               f"so far.")
            except Exception:  # noqa: BLE001
                pass
        return answer

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
                    self._pending_paused = None       # one confirm flow at a time
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

    # ── human-in-the-loop: approve a paused autonomous goal (M59.2) ──────────────
    _PAUSED_LIST_RE = re.compile(
        r"\b(any|what|which|list|show|are there)\b.{0,30}\b(paused|waiting|"
        r"pending|blocked)\b.{0,20}\b(goals?|actions?|approvals?|tasks?)\b|"
        r"\bwhat('?s| is) (waiting|pending) (for )?(my )?approval\b|"
        r"\bwhat (needs|is awaiting) (my )?approval\b", re.I)
    _PAUSED_APPROVE_RE = re.compile(
        r"\b(approve|resume|allow|go ahead with|authori[sz]e)\b.{0,24}\b"
        r"(paused|blocked|waiting|pending)?\s*(goal|task|action)\b|"
        r"\b(approve|resume) (it|that|the goal)\b", re.I)
    _PAUSED_REJECT_RE = re.compile(
        r"\b(reject|deny|decline|drop|cancel|forget)\b.{0,24}\b"
        r"(paused|blocked|waiting|pending)?\s*(goal|task|action)\b", re.I)

    def _paused_goals(self, command: str) -> Optional[str]:
        """Voice control for goals the autonomous workflow paused awaiting the
        owner's approval (M59.2). List, approve (two-step confirm, M29 style —
        she names the exact skill and waits for 'confirm' within 60 s so a
        stray phrase can't authorize an action), or reject. Only USER_APPROVAL
        -tier steps are voice-approvable; admin/system stay unreachable."""
        if self.agentic is None:
            return None
        q = (command or "").lower()

        # a pending paused-goal approval waits for exactly one thing: 'confirm'
        pending = self._pending_paused
        if pending is not None:
            self._pending_paused = None              # single-shot, always cleared
            goal_id, title, skill, expires_at = pending
            if time.time() <= expires_at:
                if re.search(r"\b(confirm|confirmed|go ahead|do it|yes)\b", q):
                    try:
                        ok = self.agentic.approve_paused(goal_id)
                    except Exception:  # noqa: BLE001
                        log.debug("paused approval failed", exc_info=True)
                        ok = None
                    if ok is not None:
                        return (f"Approved — I'll run {ok['skill']} for "
                                f"'{ok['title']}' now.")
                    return ("I couldn't approve that — it's no longer waiting, "
                            "or it needs rights I can't grant by voice.")
                if re.search(r"\b(cancel|no|don'?t|never ?mind|stop)\b", q):
                    return f"Okay, I'll leave '{title}' paused."
            # anything else: the confirmation is dropped, fall through

        wants_list = bool(self._PAUSED_LIST_RE.search(q))
        wants_approve = bool(self._PAUSED_APPROVE_RE.search(q))
        wants_reject = bool(self._PAUSED_REJECT_RE.search(q))
        if not (wants_list or wants_approve or wants_reject):
            return None
        try:
            paused = self.agentic.list_paused()
        except Exception:  # noqa: BLE001
            log.debug("list_paused failed", exc_info=True)
            return None
        if not paused:
            return "Nothing is waiting for your approval right now."
        if wants_approve:
            g = paused[0]                            # oldest first
            self._pending_approval = None            # only one confirm flow at a time
            self._pending_paused = (g["goal_id"], g["title"], g["skill"],
                                    time.time() + self._APPROVAL_TTL_S)
            return (f"'{g['title']}' needs to run {g['skill']} "
                    f"({g['permission'].replace('_', ' ').lower()}). "
                    f"Say 'confirm' and I'll run it.")
        if wants_reject:
            g = paused[0]
            self.agentic.reject_paused(g["goal_id"])
            return f"Dropped the paused goal: {g['title']}."
        titles = "; ".join(f"{g['title']} (needs {g['skill']})"
                           for g in paused[:3])
        return (f"{len(paused)} goal{'s' if len(paused) != 1 else ''} waiting "
                f"for your approval: {titles}. Say 'approve the goal' to review.")

    # ── understanding vs ACTION (M59.1): the command gate ────────────────────────
    # A clear device command must ACT, request approval, or honestly decline —
    # never fall through to a reasoner that writes an essay about how one
    # might do it. Speech-act verbs (tell/explain/summarize/write...) are
    # deliberately absent: those are understanding, and understanding keeps
    # its existing path untouched.
    _DEVICE_VERBS = ("open", "launch", "close", "quit", "exit", "kill",
                     "minimize", "maximize", "focus", "mute", "unmute", "pause",
                     "resume", "click", "type", "press", "restart", "reboot",
                     "shutdown", "sleep", "lock", "eject", "uninstall", "install")
    _IMPERATIVE_RE = re.compile(
        r"^(?:please\s+|friday[,\s]+)*(" + "|".join(_DEVICE_VERBS) + r")\b(.*)$",
        re.I)
    # admin/system-tier commands: never runnable by voice (clearance blocks
    # them too — this is the honest one-liner, not an essay)
    _ADMIN_REFUSE_RE = re.compile(
        r"^(?:please\s+|friday[,\s]*)*(restart|reboot|shut\s*down|shutdown|"
        r"sleep|hibernate|log\s*off|sign\s*out|run\s+(?:the\s+)?shell|execute)\b",
        re.I)
    # USER_APPROVAL-tier device commands a two-step voice confirm may RUN
    # (built lazily). Each: (pattern, skill, args-from-match, describe).
    _CONFIRM_ROUTES = None

    @classmethod
    def _confirm_routes(cls):
        if cls._CONFIRM_ROUTES is not None:
            return cls._CONFIRM_ROUTES
        def _app(m):
            return {"name": cls._clean_app_name(m.group("name"))}
        routes = [
            (r"^(?:please\s+|friday[,\s]*)*(?:close|quit|exit)\s+(?:the\s+)?"
             r"(?P<name>.+)$", "app.close", _app,
             lambda a: f"close {a['name']}"),
            (r"^(?:please\s+|friday[,\s]*)*type\s+(?P<text>.+)$",
             "input.type_text", lambda m: {"text": m.group("text").strip()},
             lambda a: f"type that"),
            (r"^(?:please\s+|friday[,\s]*)*press\s+(?:the\s+)?"
             r"(?P<key>[\w ]+?)(?:\s+key)?$", "input.press_key",
             lambda m: {"key": m.group("key").strip()},
             lambda a: f"press {a['key']}"),
        ]
        cls._CONFIRM_ROUTES = [(re.compile(p, re.I), s, a, d)
                               for p, s, a, d in routes]
        return cls._CONFIRM_ROUTES

    @staticmethod
    def _clean_app_name(raw: str) -> str:
        name = (raw or "").strip().strip("'\"").strip()
        name = re.sub(r"\s+(window|app|application|browser|program)$", "",
                      name, flags=re.I)
        return name.strip()

    def _command_gate(self, command: str) -> Optional[tuple]:
        """Runs AFTER the skill routes: a device imperative that no SAFE route
        matched. A USER_APPROVAL command (close app, type, press a key) is RUN
        via a two-step voice confirm — she names it, waits for 'confirm', then
        acts. Admin/system commands are refused (clearance blocks them too).
        Anything else gets an honest one-liner — never an essay, never the
        cloud. Questions never enter here. Never raises."""
        q = (command or "").strip()
        if not q or q.endswith("?"):
            return None

        # (1) a pending direct-command confirm waits for exactly 'confirm'
        pending = self._pending_command
        if pending is not None:
            self._pending_command = None             # single-shot, always cleared
            skill_name, args, describe, expires_at = pending
            low = q.lower()
            if time.time() <= expires_at:
                if re.search(r"\b(confirm|confirmed|go ahead|do it|yes)\b", low):
                    return self._run_confirmed_command(skill_name, args, describe)
                if re.search(r"\b(cancel|no|don'?t|never ?mind|stop)\b", low):
                    return (f"skill:{skill_name}:cancelled",
                            f"Okay, I won't {describe(args)}.")
            # anything else: confirmation dropped, fall through to fresh parse

        # (2) admin/system device commands — never by voice
        if self._ADMIN_REFUSE_RE.match(q):
            return ("command:refused_admin",
                    "That needs administrator rights I can't grant by voice.")

        # (3) a USER_APPROVAL device command → arm a two-step confirm to RUN it
        if self.skills is not None:
            for pattern, skill_name, args_fn, describe in self._confirm_routes():
                m = pattern.match(q)
                if not m:
                    continue
                try:
                    args = args_fn(m)
                except Exception:  # noqa: BLE001
                    continue
                if not any(str(v).strip() for v in args.values()):
                    continue                         # empty target → not a command
                self._pending_approval = None        # one confirm flow at a time
                self._pending_paused = None
                self._pending_send = None            # never let 'confirm' send a stale draft
                self._pending_command = (skill_name, args, describe,
                                         time.time() + self._APPROVAL_TTL_S)
                return (f"skill:{skill_name}:await_confirm",
                        f"Say 'confirm' and I'll {describe(args)}.")

        # (4) any other imperative: honest one-liner
        if not self._IMPERATIVE_RE.match(q):
            return None
        return ("command:unavailable",
                "That sounds like a command, but I don't have an action for "
                "it yet — ask me 'what can you do' for my action list.")

    def _run_confirmed_command(self, skill_name: str, args: dict,
                               describe) -> tuple:
        """Execute a confirmed USER_APPROVAL command through the full M47
        pipeline, with the human-approval step satisfied by the confirmation.
        Clearance still applies — an admin skill that slipped through refuses."""
        if self.skills is None:
            return (f"skill:{skill_name}:refused", "I can't run actions right now.")
        try:
            from core.skills.permissions import Permission
            skill = self.skills._registry.get(skill_name)
            if skill.permission > Permission.USER_APPROVAL:
                return (f"skill:{skill_name}:refused",
                        "That needs administrator rights I can't grant by voice.")
            from core.executive.agentic import run_one_shot_approved
            result = run_one_shot_approved(self.skills, skill_name, args)
        except Exception:  # noqa: BLE001 — an action fault never breaks the turn
            log.debug("confirmed command failed: %s", skill_name, exc_info=True)
            return (f"skill:{skill_name}", "I couldn't do that just now.")
        if getattr(result, "success", False):
            return (f"skill:{skill_name}", "Done.")
        return (f"skill:{skill_name}",
                f"I couldn't {describe(args)} — "
                f"{getattr(result, 'error', 'it failed')}.")

    # ── her screen sight (M52): read the screen, on-device ───────────────────────
    _SCREEN_RE = re.compile(
        r"\b(read|scan|look at|check|what'?s?( is)? on|what does).{0,20}\b(my |the )?"
        r"screen\b|\bwhat am i (looking at|seeing)\b|\bwhat'?s this (error|on screen)\b",
        re.I)

    def _read_screen(self, command: str) -> Optional[tuple]:
        """Capture + OCR the screen locally and answer about it. The screenshot
        NEVER leaves the machine — only the extracted text is reasoned over.
        Returns (route_key, answer) or None. Never raises."""
        if not self._SCREEN_RE.search(command or ""):
            return None
        try:
            from core.io import screen
            if not screen.available():
                return ("screen", "I can't read your screen yet — the on-device "
                        "text reader isn't installed.")
            result = screen.read_screen()
            if not result.get("ok"):
                return ("screen", "I couldn't read any text on your screen just now.")
            text = result["text"]
            # UNDERSTAND the screen and answer conversationally — never read the
            # OCR back like a text reader. The image stays local; only the
            # extracted text is reasoned over.
            answer = self._comprehend_screen(text, command)
            if answer:
                return ("screen", answer)
            # last resort: no reasoning model is available (e.g. a keyless box).
            # Be honest about it instead of robotically dumping the raw text.
            snippet = text[:240].strip() + ("…" if len(text) > 240 else "")
            return ("screen", "I can see your screen, but I need my reasoning "
                    "brain online to actually make sense of it. The gist of the "
                    "text is: " + snippet)
        except Exception:  # noqa: BLE001 — screen reading must never break a turn
            log.debug("screen read failed", exc_info=True)
            return None

    def _comprehend_screen(self, text: str, command: str) -> Optional[str]:
        """Turn on-screen text into a natural, spoken-style answer to what was
        actually asked — summarise/explain, don't recite. Cloud reasoner first
        (the real comprehension), then her own on-device reasoner. Returns a
        confident answer or None. Never raises."""
        prompt = (
            "You are FRIDAY, speaking out loud to your owner in a warm, natural "
            "voice. You just glanced at his screen. Here is the text OCR pulled "
            f"from it:\n\"\"\"\n{text[:4000]}\n\"\"\"\n\n"
            f"He said: \"{command}\"\n\n"
            "Reply in one or two short, spoken sentences, the way a person would "
            "after a glance at the screen. Understand what he's really asking and "
            "answer THAT. Do NOT read the text back word-for-word or list it out "
            "— summarise, explain, or answer conversationally. If what he asked "
            "about isn't on the screen, just say so.")
        if self.reasoner is not None and self.reasoner.available():
            try:
                r = self.reasoner.reason(prompt)
                if getattr(r, "ok", False) and (getattr(r, "answer", "") or "").strip():
                    return r.answer.strip()
            except Exception:  # noqa: BLE001
                log.debug("cloud screen comprehension failed", exc_info=True)
        if self.local_reasoner is not None and self.local_reasoner.available():
            try:
                r = self.local_reasoner.reason(prompt, context={})
                if getattr(r, "ok", False) and (getattr(r, "answer", "") or "").strip() \
                        and float(getattr(r, "confidence", 0) or 0) >= self.escalate_threshold:
                    return r.answer.strip()
            except Exception:  # noqa: BLE001
                log.debug("local screen comprehension failed", exc_info=True)
        return None

    # ── show / hide herself from screen capture (the private overlay, M51) ───────
    _SHOW_SELF_RE = re.compile(
        r"\b(show yourself|show your ?self|make yourself visible|reveal yourself|"
        r"let (?:them|everyone) see you|become visible|show your face|"
        r"come out of hiding)\b", re.I)
    _HIDE_SELF_RE = re.compile(
        r"\b(hide yourself|hide your ?self|go (?:private|invisible|hidden)|"
        r"become invisible|hide your face|stay hidden|go back to private)\b", re.I)

    def _visibility(self, command: str) -> Optional[tuple]:
        """'Show yourself' makes the overlay VISIBLE to everyone — screenshots,
        screen sharing, live streams (drops the capture exclusion). 'Hide
        yourself' returns her to private (the default). Returns (key, answer) or
        None. Never raises."""
        if self.overlay is None:
            return None
        q = command or ""
        if self._SHOW_SELF_RE.search(q):
            try:
                self.overlay.show_self()
            except Exception:  # noqa: BLE001
                log.debug("overlay show_self failed", exc_info=True)
            return ("overlay:show", "Okay — I'm showing myself now. Everyone can "
                    "see me on your screen, in screenshots and screen sharing.")
        if self._HIDE_SELF_RE.search(q):
            try:
                self.overlay.hide_self()
            except Exception:  # noqa: BLE001
                log.debug("overlay hide_self failed", exc_info=True)
            return ("overlay:hide", "Done — I'm hidden from screenshots and screen "
                    "sharing again, just for you.")
        return None

    # -- her hands: owner-confirmed code execution in the isolated sandbox --------
    # Running code is consequential, so it is OWNER-CONFIRMED (Build & Behavior
    # Directive s4 / the M59.2 two-step pattern): she shows exactly what will run
    # and only runs it after an explicit "confirm". Execution uses the hardened
    # WorkspaceSandbox (curated stdlib, workdir-only files, no OS/network) --
    # never the real shell. Generated code is shown for review before it runs.
    _CONFIRM_RUN_RE = re.compile(
        r"^\s*(confirm|yes,? run it|go ahead(?:,? run it)?|run it|do it)\s*$", re.I)
    _CANCEL_RUN_RE = re.compile(
        r"^\s*(cancel|no|don'?t|stop|never ?mind)\b", re.I)
    _SHOWME_RE = re.compile(
        r"\bshow me\b|\bshow your work\b|\bwhat did you run\b|\bopen the code\b|"
        r"\bshow the (?:code|work|output)\b", re.I)

    def _run_code(self, command: str) -> Optional[tuple]:
        """Owner-confirmed code execution in the isolated sandbox. Returns
        (route_key, answer) or None. Never raises."""
        try:
            pending = getattr(self, "_pending_code", None)
            if pending is not None:
                if self._CONFIRM_RUN_RE.match(command or ""):
                    self._pending_code = None
                    from core.security.workspace import run_task
                    return ("code.run",
                            self._describe_run(run_task(pending, task="owner-confirmed")))
                if self._CANCEL_RUN_RE.match(command or ""):
                    self._pending_code = None
                    return ("code.run", "Okay -- I won't run it.")
                self._pending_code = None      # stale; fall through to normal routing
            code = self._extract_runnable(command)
            if not code:
                return None
            self._pending_code = code
            self._pending_command = None      # one confirm flow at a time, like
            self._pending_approval = None      # _command_gate does when it arms
            self._pending_paused = None
            self._pending_send = None          # never let 'confirm' send a stale draft
            preview = code if len(code) <= 300 else code[:300] + " ..."
            return ("code.run",
                    "That runs in an isolated sandbox (no internet, no system "
                    "access). Here's exactly what I'll run:\n" + preview
                    + "\nSay 'confirm' to run it.")
        except Exception:  # noqa: BLE001 -- running code must never break a turn
            log.debug("run_code route failed", exc_info=True)
            self._pending_code = None
            return None

    def _show_work(self, command: str) -> Optional[tuple]:
        """Reveal the last sandbox run (code + output + artifacts) on request --
        the transparency half of the contract. None if nothing to show."""
        if not self._SHOWME_RE.search(command or ""):
            return None
        try:
            from core.security.workspace import get_execution_ledger
            rec = get_execution_ledger().last()
        except Exception:  # noqa: BLE001
            return None
        if rec is None:
            return None
        lines = ["Here's what I ran:", rec.code, ""]
        if (rec.output or "").strip():
            lines += ["Output:", rec.output.rstrip()]
        elif rec.value is not None:
            lines.append("Result: " + str(rec.value))
        if not rec.ok:
            lines.append("(error: " + rec.error + ")")
        if rec.artifacts:
            lines.append("Files: " + ", ".join(a["name"] for a in rec.artifacts))
        return ("show_work", "\n".join(lines))

    @staticmethod
    def _describe_run(rec) -> str:
        """A concise, honest result line from an ExecutionRecord."""
        if not rec.ok:
            return "It didn't run cleanly -- " + rec.error
        out = (rec.output or "").strip()
        if out:
            base = "Done. It printed:\n" + (out if len(out) <= 500 else out[:500] + " ...")
        elif rec.value is not None:
            base = "Done. It evaluated to " + str(rec.value) + "."
        else:
            base = "Done -- it ran with no output."
        if rec.artifacts:
            base += " It created " + ", ".join(a["name"] for a in rec.artifacts) + "."
        return base + " Say 'show me' to see the code and full output."

    @staticmethod
    def _extract_runnable(command: str) -> str:
        """Pull a runnable snippet from an EXPLICIT run request -- a fenced block
        or text after 'run this code:'/'execute:'. Empty if no clear code or no
        run intent (so 'what does this print' still goes to code-reasoning)."""
        q = command or ""
        if not re.search(r"\b(run|execute)\b", q, re.I):
            return ""
        try:
            from core.reasoning import code as codemod
            m = codemod._FENCE_RE.search(q)
            if m:
                return m.group(1).strip()
            for lead in ("run this code:", "run the code:", "execute this code:",
                         "execute this:", "execute:", "run this:", "run the script:",
                         "run:"):
                i = q.lower().find(lead)
                if i != -1:
                    cand = q[i + len(lead):].strip()
                    if cand and codemod._looks_like_code(cand):
                        return cand
        except Exception:  # noqa: BLE001
            log.debug("extract_runnable failed", exc_info=True)
        return ""

    # -- safety: a destructive request with vague scope is CLARIFIED, not run ----
    # Build & Behavior Directive s4: ask when an action is destructive AND the
    # scope is ambiguous. "delete the old files" names no concrete target, so she
    # asks which files rather than guessing -- deleting is irreversible.
    _DESTRUCTIVE_RE = re.compile(
        r"\b(delete|remove|wipe|erase|get rid of|trash|purge|format)\b", re.I)
    _VAGUE_SCOPE_RE = re.compile(
        r"\b(?:old|all|every|these|those|some|my|the|junk|unnecessary|useless|"
        r"temp(?:orary)?)\b.{0,20}?\b(files?|folders?|stuff|documents?|photos?|"
        r"pictures?|data|things?|everything)\b|\beverything\b|\bthem all\b", re.I)
    _SPECIFIC_PATH_RE = re.compile(r"[A-Za-z]:\\|/[\w.-]+/|\b[\w-]+\.\w{2,4}\b")

    def _clarify_destructive(self, command: str) -> Optional[tuple]:
        """A destructive request with vague scope is CLARIFIED, never executed.
        Returns (route_key, question) or None. Never raises."""
        q = command or ""
        if not self._DESTRUCTIVE_RE.search(q):
            return None
        if not self._VAGUE_SCOPE_RE.search(q):
            return None                 # no vague bulk target -> not this route
        if self._SPECIFIC_PATH_RE.search(q):
            return None                 # a concrete file/path -> unambiguous
        return ("clarify:destructive",
                "Deleting is permanent, so I want to be sure first: which files "
                "exactly, and from where? Point me at a folder or a pattern "
                "(like *.tmp in Downloads) and I'll show you what matches before "
                "removing anything.")

    # -- her accounts: ACT (send an email / WhatsApp message) -- owner-confirmed --
    # High-stakes: she sends AS you. The gate is mandatory and two-step: she DRAFTS
    # (opens a pre-filled, VISIBLE compose window) and reads it back, then SENDS
    # only after you say "send it". Never auto-sends. Recipients resolve through a
    # local contacts map or a spoken address/number -- she refuses if she can't
    # resolve who. Instagram posting isn't reliably automatable and isn't offered.
    _SEND_EMAIL_RE = re.compile(
        r"^\s*(?:send (?:an? )?email to|e-?mail)\s+(?P<to>.+?)"
        r"(?:\s+subject\s+(?P<subj>.+?))?"
        r"\s+(?:saying|that says?|with the message|message:?)\s+(?P<body>.+?)\s*$",
        re.I)
    _SEND_WA_RE = re.compile(
        r"^\s*(?:whatsapp|text|message)\s+(?P<to>.+?)\s+"
        r"(?:on whatsapp\s+)?(?:saying|that says?|message:?)\s+(?P<body>.+?)\s*$",
        re.I)
    _SEND_CONFIRM_RE = re.compile(
        r"^\s*(send(?: it)?|yes,? send(?: it)?|confirm|go ahead)\s*$", re.I)

    def _account_action(self, command: str) -> Optional[tuple]:
        """Compose + owner-confirmed send on an account. Returns (route_key,
        answer) or None. Never raises; never auto-sends."""
        q = (command or "").strip()
        pending = self._pending_send
        if pending is not None:                      # a draft is waiting
            if time.time() > pending.get("expires_at", 0):
                self._pending_send = None            # a forgotten draft expires — never sends late
            elif self._SEND_CONFIRM_RE.match(q):
                self._pending_send = None
                return ("account.send", self._do_send(pending))
            elif self._CANCEL_RUN_RE.match(q):
                self._pending_send = None
                return ("account.send", "Okay -- I won't send it.")
            else:
                self._pending_send = None            # any other turn drops the draft; fall through
        if not q:
            return None
        try:
            from core.web.browser import BrowserController
            m = self._SEND_EMAIL_RE.match(q)
            if m:
                return self._draft_email(m.group("to"), m.group("subj"),
                                         m.group("body"), BrowserController)
            m = self._SEND_WA_RE.match(q)
            if m and "whatsapp" in q.lower():
                return self._draft_whatsapp(m.group("to"), m.group("body"),
                                            BrowserController)
        except Exception:  # noqa: BLE001 -- an account fault never breaks the turn
            log.debug("account action route failed", exc_info=True)
        return None

    def _draft_email(self, to_raw, subj_raw, body_raw, BrowserController):
        from core.web.accounts import compose_email, resolve_contact
        to = resolve_contact(to_raw, "email")
        if to is None:
            return ("account.send:no_contact",
                    f"I don't have an email address for {(to_raw or '').strip()!r}. "
                    "Add them to contacts or tell me the address.")
        if not BrowserController.available():
            return ("account.send", "I can't drive a browser to send that yet.")
        subject = (subj_raw or "").strip() or "(no subject)"
        body = (body_raw or "").strip()
        if not compose_email(to, subject, body).get("ok"):
            return ("account.send", "I couldn't open the email draft.")
        self._arm_send({"account": "Gmail", "to": to, "subject": subject,
                        "body": body, "host": "mail.google.com"})
        return ("account.send:await_confirm",
                f"Draft ready in Gmail -- to {to}, subject '{subject}', saying: "
                f"{body[:160]}. Say 'send it' to send, or 'cancel'.")

    def _draft_whatsapp(self, to_raw, body_raw, BrowserController):
        from core.web.accounts import compose_whatsapp, resolve_contact
        phone = resolve_contact(to_raw, "phone")
        if phone is None:
            return ("account.send:no_contact",
                    f"I don't have a WhatsApp number for {(to_raw or '').strip()!r}. "
                    "Add them to contacts or tell me the number with country code.")
        if not BrowserController.available():
            return ("account.send", "I can't drive a browser to send that yet.")
        body = (body_raw or "").strip()
        if not compose_whatsapp(phone, body).get("ok"):
            return ("account.send", "I couldn't open the WhatsApp chat.")
        self._arm_send({"account": "WhatsApp", "to": phone, "body": body,
                        "host": "web.whatsapp.com"})
        return ("account.send:await_confirm",
                f"Draft ready in WhatsApp -- to {phone}, saying: {body[:160]}. "
                "Say 'send it' to send, or 'cancel'.")

    def _arm_send(self, pending: dict) -> None:
        """Arm a pending send and clear every other confirm flow (only one at a
        time), the way _command_gate / _run_code do when they arm. A draft
        expires on the same 60s window as the other confirm gates, so a forgotten
        draft can't be fired by a much-later stray 'confirm'/'go ahead'."""
        pending["expires_at"] = time.time() + self._APPROVAL_TTL_S
        self._pending_send = pending
        self._pending_command = None
        self._pending_approval = None
        self._pending_paused = None
        self._pending_code = None
        self._pending_browser = None

    def _do_send(self, pending: dict) -> str:
        from urllib.parse import urlparse

        from core.web.accounts import send_open_draft
        from core.web.browser import get_browser
        account, who = pending["account"], pending.get("to", "")
        try:
            # the shared browser page must still be ON the drafted compose — never
            # press send/Enter on whatever page happens to be focused now (it could
            # send Enter in the wrong chat). Verify the host before pressing.
            cur = get_browser().current()
            host = (urlparse(cur.get("url", "")).hostname or "") if cur.get("ok") else ""
            if pending.get("host") and pending["host"] not in host:
                return ("The draft isn't open anymore, so I won't send it to the "
                        "wrong place — ask me to compose it again.")
            ok = send_open_draft(account).get("ok")
        except Exception:  # noqa: BLE001
            log.debug("send failed", exc_info=True)
            ok = False
        if ok:
            return f"Sent your {account} message to {who}."
        return (f"I opened the {account} draft but couldn't send it "
                "automatically -- it's ready in the window if you want to send it.")

    # -- her accounts (Gmail / Instagram / WhatsApp / Google): READ side ----------
    # "open my gmail" navigates her Chrome there (you log in once); "check my
    # email" / "any new whatsapp" opens + reads it. This is the read/navigate
    # path only — ACTING on an account (send / post / message) is a separate,
    # owner-confirmed flow and is deliberately NOT wired here yet.
    _ACCOUNT_RE = re.compile(
        r"\b(open|check|read|show|look at|any(?:\s+new)?|got any|what'?s on|"
        r"do i have)\b[^.?!]*?\b"
        r"(gmail|e-?mails?|inbox|instagram|insta|whatsapp|"
        r"google calendar|calendar|google)\b", re.I)
    _ACCOUNT_READ_RE = re.compile(
        r"\b(check|read|show|any|got|what|do i have|look)\b", re.I)

    def _check_account(self, command: str) -> Optional[tuple]:
        """Open (and optionally read) one of the owner's signed-in accounts in
        her browser. Returns (route_key, answer) or None. Never raises. Read-only
        — never sends or posts. The caller passes no command= (account content is
        personal and must not ride the conversation window to the cloud)."""
        q = (command or "").strip()
        m = self._ACCOUNT_RE.search(q) if q else None
        if not m:
            return None
        from core.web.accounts import resolve
        hit = resolve(m.group(2))
        if hit is None:
            return None
        label = hit[0]
        try:
            from core.web.browser import BrowserController
            if not BrowserController.available():
                return ("account:" + label,
                        "I can open that in my browser, but browser control "
                        "isn't set up yet.")
            if self._ACCOUNT_READ_RE.search(q):
                from core.web.accounts import read_account
                r = read_account(m.group(2))
                if not r.get("ok"):
                    return ("account:" + label, f"I couldn't open {label} just now.")
                if not r.get("logged_in", True):
                    return ("account:" + label,
                            f"I opened {label}, but you're not signed in yet — log "
                            f"into {label} once in my browser window and I'll be "
                            "able to read it.")
                text = " ".join(ln.strip() for ln in
                                (r.get("text") or "").splitlines() if ln.strip())
                if not text:
                    return ("account:" + label,
                            f"I opened {label} but there was nothing to read.")
                return ("account:" + label, f"On your {label}: {text[:400]}")
            from core.web.accounts import open_account
            r = open_account(m.group(2))
            if not r.get("ok"):
                return ("account:" + label, f"I couldn't open {label} just now.")
            return ("account:" + label,
                    f"Opened {label} in my browser. If it asks you to sign in, "
                    "log in once and I'll remember it from now on.")
        except Exception:  # noqa: BLE001 — an account fault never breaks the turn
            log.debug("account route failed", exc_info=True)
            return ("account:" + label, f"I ran into trouble with {label}.")

    # -- driving Chrome: owner-confirmed click on the OPEN page --------------------
    # Guardrails (2026-08-08 security review): the confirm names the EXACT text
    # AND the site; sensitive hosts (banking/checkout/admin) are refused by voice;
    # browser.click matches exactly (refuses ambiguity); the confirmed click runs
    # through the governed executor so clearance still applies. Typing by voice is
    # deliberately NOT wired (blind insert / password-field risk) -- next, after
    # a selector/password-field guard.
    _BROWSER_CLICK_RE = re.compile(
        r"^\s*click(?:\s+on)?\s+(?P<text>.{1,80}?)\s*[.?!]?\s*$", re.I)
    # substring match on purpose: a safety denylist should over-refuse (better to
    # decline a voice click on "mybank.com" than to miss it)
    _SENSITIVE_HOST_RE = re.compile(
        r"(bank|chase|wellsfargo|citi|hsbc|barclays|paypal|venmo|coinbase|"
        r"binance|robinhood|fidelity|schwab|vanguard|checkout|payment|billing)"
        r"|accounts\.google|/(?:admin|gp/(?:buy|checkout))", re.I)

    def _browser_action(self, command: str) -> Optional[tuple]:
        """Owner-confirmed click on the page open in FRIDAY's Chrome. Returns
        (route_key, answer) or None. Never raises."""
        try:
            pending = getattr(self, "_pending_browser", None)
            if pending is not None:
                if self._CONFIRM_RUN_RE.match(command or ""):
                    self._pending_browser = None
                    return ("browser.click", self._do_browser_click(pending))
                if self._CANCEL_RUN_RE.match(command or ""):
                    self._pending_browser = None
                    return ("browser.click", "Okay -- I won't click it.")
                self._pending_browser = None          # stale; fall through
            if self.skills is None:
                return None
            m = self._BROWSER_CLICK_RE.match((command or "").strip())
            if not m:
                return None
            from core.web.browser import get_browser
            cur = get_browser().current()
            if not (isinstance(cur, dict) and cur.get("ok")):
                return None                            # no page open -> not a web click
            url = cur.get("url", "") or ""
            host = ""
            try:
                from urllib.parse import urlparse
                host = urlparse(url).hostname or ""
            except Exception:  # noqa: BLE001
                host = ""
            if url and self._SENSITIVE_HOST_RE.search(url):
                return ("browser.click:refused",
                        "That's a sensitive site (" + (host or url) + ") -- I won't "
                        "click there by voice. Please do that one yourself.")
            text = m.group("text").strip(" .?!'\"")
            if not text:
                return None
            self._pending_browser = text
            self._pending_command = None
            self._pending_approval = None
            self._pending_paused = None
            self._pending_code = None
            self._pending_send = None          # never let 'confirm' send a stale draft
            where = (" on " + host) if host else " on the open page"
            return ("browser.click:await_confirm",
                    "Say 'confirm' and I'll click '" + text + "'" + where + ".")
        except Exception:  # noqa: BLE001
            log.debug("browser_action route failed", exc_info=True)
            self._pending_browser = None
            return None

    def _do_browser_click(self, text: str) -> str:
        """Execute a confirmed click through the governed executor -- clearance
        still applies, so an owner-confirmed voice click never bypasses M47."""
        try:
            from core.executive.agentic import run_one_shot_approved
            result = run_one_shot_approved(self.skills, "browser.click", {"text": text})
        except Exception:  # noqa: BLE001
            log.debug("confirmed browser click failed", exc_info=True)
            return "I couldn't click that just now."
        data = getattr(result, "data", None) or {}
        if getattr(result, "success", False) and data.get("ok"):
            return "Done -- clicked '" + text + "'."
        reason = data.get("error") or getattr(result, "error", "it didn't work")
        return "I couldn't click '" + text + "' -- " + str(reason) + "."

    # -- searching the web: drive her Chrome to a search engine, read the results -
    _WEBSEARCH_RE = re.compile(
        r"\b(?:search (?:the web|online|the internet|google)?\s*(?:for\s+)?|"
        r"google\s+|look up\s+|what does the internet say about\s+)"
        r"(?P<q>.{2,120}?)\s*(?:online|on the web|on the internet)?\s*[.?!]?$", re.I)

    def _web_search(self, command: str) -> Optional[tuple]:
        """Search the web by driving her Chrome to DuckDuckGo and reading the
        results page. Read-only. Returns (route_key, answer) or None."""
        m = self._WEBSEARCH_RE.search((command or "").strip())
        if not m:
            return None
        query = m.group("q").strip(" .?!'\"")
        if len(query) < 2:
            return None
        try:
            from urllib.parse import quote_plus
            from core.web.browser import get_browser
            b = get_browser()
            if not b.available():
                return ("web.search", "I can't search the web yet -- install "
                        "Playwright first (pip install playwright).")
            opened = b.open("https://duckduckgo.com/html/?q=" + quote_plus(query))
            if not (isinstance(opened, dict) and opened.get("ok")):
                return ("web.search", "I couldn't run that search just now.")
            read = b.read(max_chars=1500)
            text = (read.get("text") or "").strip() if isinstance(read, dict) else ""
            if not text:
                return ("web.search", "I searched but couldn't read the results.")
            return ("web.search", "Here's what I found for '" + query + "':\n"
                    + text[:700])
        except Exception:  # noqa: BLE001
            log.debug("web_search failed", exc_info=True)
            return None

    # ── her body: the governed action layer (M47) ───────────────────────────────
    # action-shaped voice commands run through the SkillExecutor, which enforces
    # the M3 security pipeline (policy → clearance → approval → sandbox → audit).
    # VOICE POLICY: only SAFE-permission skills run hands-free. Anything needing
    # approval (app.close, input.*, keystrokes) or admin (shell.run, power.*,
    # startup.*) is refused from voice — a mic is untrusted (anyone in the room),
    # and the executor's approval path blocks, which a real-time turn cannot.
    #
    # Each route: (compiled pattern, skill name, args builder, spoken response).
    # `args` receives the regex match; `render` receives the skill Result.data.
    _SKILL_ROUTES = None            # built lazily (see _skill_routes)

    @classmethod
    def _skill_routes(cls):
        if cls._SKILL_ROUTES is not None:
            return cls._SKILL_ROUTES
        def _num(m):
            return {"level": max(0, min(100, int(m.group("n"))))}   # clamp 0–100
        def _home_msg(d):
            if not isinstance(d, dict):
                return "I couldn't reach your home hub just now."
            reason = d.get("reason")
            if reason == "not_configured":
                return ("I'm not connected to your home hub yet. Add your Home "
                        "Assistant address to friday_config.json and your token "
                        "to .env as HASS_TOKEN, then I can control your devices.")
            if reason == "not_found":
                return ("I couldn't find a device called \"" + d.get("device", "")
                        + "\" -- ask me to 'list my devices' to hear the names.")
            return "I couldn't do that on your home hub just now."
        def _browser_msg(d):
            if not isinstance(d, dict):
                return "I couldn't drive the browser just now."
            reason = d.get("reason")
            if reason == "not_available":
                return ("I can't drive Chrome yet -- install Playwright (pip "
                        "install playwright), then log into the sites you want "
                        "me to use in the Chrome window I open.")
            if reason == "bad_url":
                return "That doesn't look like a web address I can open."
            return ("I couldn't do that in the browser -- "
                    + str(d.get("error", "it failed")))
        routes = [
            (r"\b(take|grab|capture)\b.*\bscreenshot\b|\bscreenshot\b", "system.screenshot",
             None, lambda d: "I've taken a screenshot."),
            (r"\b(what'?s|whats|my|check).{0,12}\bip\b|\bip address\b", "net.ip",
             None, lambda d: f"Your IP address is {d}."),
            (r"\b(am i (online|connected)|check (the )?internet|do i have internet)\b",
             "net.check_internet", None,
             lambda d: "Yes, you're online." if d else "No, you appear to be offline."),
            (r"\b(wifi|wi-fi|wireless)\b.{0,10}\b(status|network|connected)\b|\bwhat wifi\b",
             "net.wifi_status", None,
             lambda d: (f"You're connected to {d.get('ssid') or 'Wi-Fi'}."
                        if isinstance(d, dict) and d.get("connected")
                        else "You're not connected to Wi-Fi.")),
            (r"\b(system (status|summary|health)|how'?s the (system|computer|machine)|"
             r"how are you doing|status report)\b", "system.summary",
             None, lambda d: str(d)),
            (r"\bmute\b", "audio.mute", None, lambda d: "Muted."),
            (r"\bunmute\b", "audio.unmute", None, lambda d: "Unmuted."),
            (r"\b(set (the )?volume to|volume to)\s+(?P<n>\d{1,3})\b", "audio.set_volume",
             _num, lambda d: "Done."),
            # her "Ultron" move: one command, every configured phone starts playing
            # (checked before the PC media route so "on my phones" isn't the laptop)
            (r"\bplay music on (?:my |all )?(?:phones?|mobiles?)\b"
             r"|(?:open|wake)\b.{0,25}\b(?:phones?|mobiles?)\b.{0,25}\bplay\b"
             r"|\bplay(?:\s+(?:some|the))?\s+music\s+on\s+all\b",
             "phone.play_music", None,
             lambda d: (("Playing on " + str(len(d.get("played", []))) + " phone"
                         + ("s" if len(d.get("played", [])) != 1 else "") + ".")
                        if isinstance(d, dict) and d.get("ok") else _home_msg(d))),
            # "play music" / "put on some music" ACTUALLY starts music (Spotify),
            # checked before the bare play/pause toggle below — a media key on an
            # empty queue plays nothing, which is why this used to no-op silently
            (r"\b(?:play|put on|start)\b(?:\s+(?:some|the|my))?\s+music\b",
             "media.play_music", None,
             lambda d: d if isinstance(d, str) else "Playing music."),
            (r"\b(play|pause|play ?pause|resume)\b.{0,10}(music|media|track|song|it)?\b",
             "media.play_pause", None, lambda d: "Done."),
            (r"\bnext (track|song)\b|\bskip\b", "media.next", None, lambda d: "Next track."),
            (r"\b(previous|last) (track|song)\b|\bgo back a (track|song)\b", "media.prev",
             None, lambda d: "Previous track."),
            (r"\bbrightness up\b|\bbrighter\b", "display.brightness_up",
             None, lambda d: "Brightness up."),
            (r"\bbrightness down\b|\bdimmer\b|\bdim (the )?screen\b", "display.brightness_down",
             None, lambda d: "Brightness down."),
            # ── understanding vs ACTION (M59.1): clear commands act ──────────
            (r"\b(?:set (?:the )?brightness to|brightness to)\s+(?P<n>\d{1,3})\b",
             "display.set_brightness", _num, lambda d: "Done."),
            (r"\b(?:open|go to|visit)\s+(?P<url>(?:https?://\S+|[\w.-]+\.(?:com|org|net|io|dev|ai|gov|edu)\S*))",
             "web.open_url",
             lambda m: {"url": (m.group("url") if m.group("url").startswith("http")
                                else "https://" + m.group("url"))},
             lambda d: "Opening it in your browser."),
            (r"\b(?:open|launch|start)\s+(?:the\s+)?(?P<name>[A-Za-z][\w .+-]{1,40})$",
             "app.open", lambda m: {"name": m.group("name").strip()},
             lambda d: d if isinstance(d, str) and d.startswith("Opened")
                       else "Opening it now."),
            (r"\b(?:focus|switch to)\s+(?:the\s+)?(?P<title>[\w .+-]{2,40})\s*(?:window)?$",
             "window.focus", lambda m: {"title": m.group("title").strip()},
             lambda d: ("I couldn't find that window."
                        if isinstance(d, str) and d.startswith("Window not found")
                        else "Focused.")),
            (r"\bminimi[sz]e\b.{0,15}\bwindow\b|\bminimi[sz]e (?:this|it)\b",
             "window.minimize", None,
             lambda d: "There's no window to minimize."
                       if isinstance(d, str) and "No window" in d else "Minimized."),
            (r"\bmaximi[sz]e\b.{0,15}\bwindow\b|\bmaximi[sz]e (?:this|it)\b",
             "window.maximize", None,
             lambda d: "There's no window to maximize."
                       if isinstance(d, str) and "No window" in d else "Maximized."),
            (r"\bsearch (?:my )?files (?:for|named)\s+(?P<q>.{2,60})$|"
             r"\bfind (?:the |a )?files?\s+(?:named|called|for)\s+(?P<q2>.{2,60})$",
             "files.search",
             lambda m: {"query": (m.group("q") or m.group("q2") or "").strip(" ?.")},
             lambda d: (f"I found {len(d)} matching files."
                        if isinstance(d, list) else "Search done.")),
            (r"\b(?:recent files|what files did i (?:change|edit) recently)\b",
             "files.recent", None,
             lambda d: (f"Your most recent files: "
                        + ", ".join(str(x) for x in d[:3]) if isinstance(d, list)
                        else "Done.")),
            (r"\b(?:what'?s (?:on|in) (?:my|the) clipboard|read (?:my|the) clipboard)\b",
             "clipboard.get", None,
             lambda d: (f"Your clipboard says: {str(d)[:180]}" if d
                        else "Your clipboard is empty.")),
            # ── the home: lights / fans / TV / plugs / phone via Home Assistant ──
            (r"\bturn\s+on\s+(?:the\s+|my\s+)?(?P<device>[\w .'-]{2,40}?)\s*$"
             r"|\bswitch\s+on\s+(?:the\s+|my\s+)?(?P<device2>[\w .'-]{2,40}?)\s*$"
             r"|\bturn\s+(?:the\s+|my\s+)?(?P<device3>[\w .'-]{2,40}?)\s+on\b",
             "home.turn_on",
             lambda m: {"device": (m.group("device") or m.group("device2")
                                   or m.group("device3") or "").strip()},
             lambda d: ("Done -- " + d.get("device", "it") + " is on."
                        if isinstance(d, dict) and d.get("ok") else _home_msg(d))),
            (r"\bturn\s+off\s+(?:the\s+|my\s+)?(?P<device>[\w .'-]{2,40}?)\s*$"
             r"|\bswitch\s+off\s+(?:the\s+|my\s+)?(?P<device2>[\w .'-]{2,40}?)\s*$"
             r"|\bturn\s+(?:the\s+|my\s+)?(?P<device3>[\w .'-]{2,40}?)\s+off\b",
             "home.turn_off",
             lambda m: {"device": (m.group("device") or m.group("device2")
                                   or m.group("device3") or "").strip()},
             lambda d: ("Done -- " + d.get("device", "it") + " is off."
                        if isinstance(d, dict) and d.get("ok") else _home_msg(d))),
            (r"\b(?:ring|find|ping)\s+my\s+phone\b|\bwhere'?s\s+my\s+phone\b",
             "phone.notify",
             lambda m: {"message": "FRIDAY: here's your phone.", "target": "notify"},
             lambda d: ("I've pinged your phone."
                        if isinstance(d, dict) and d.get("ok") else _home_msg(d))),
            (r"\blist (?:my )?(?:smart )?devices\b|\bwhat can you control\b|"
             r"\bwhat (?:smart )?devices\b.{0,20}\bcontrol\b",
             "home.list", None,
             lambda d: (("You can control: " + ", ".join(d.get("devices", [])[:12])
                         + ".") if isinstance(d, dict) and d.get("ok")
                        and d.get("devices")
                        else (_home_msg(d) if isinstance(d, dict) and not d.get("ok")
                              else "I don't see any controllable devices yet."))),
            # ── driving Chrome: open / read a page (click & type are governed) ──
            (r"\bbrowse to\s+(?P<url>\S+)"
             r"|\bopen (?:the )?(?:website|web ?page|page|site)\s+(?P<url2>\S+)",
             "browser.open",
             lambda m: {"url": (m.group("url") or m.group("url2") or "").strip(" .?")},
             lambda d: (("Opened " + (d.get("title") or d.get("url") or "the page")
                         + ".") if isinstance(d, dict) and d.get("ok")
                        else _browser_msg(d))),
            (r"\bread (?:the|this) (?:page|website|site|article)\b"
             r"|\bwhat(?:'s| is) on (?:this|the) (?:web ?)?page\b",
             "browser.read", None,
             lambda d: (((d.get("title") or "This page") + ": "
                         + (d.get("text") or "")[:400]
                         + ("..." if len(str(d.get("text") or "")) > 400 else ""))
                        if isinstance(d, dict) and d.get("ok") and d.get("text")
                        else _browser_msg(d))),
        ]
        cls._SKILL_ROUTES = [(re.compile(p, re.I), name, args, render)
                             for p, name, args, render in routes]
        return cls._SKILL_ROUTES

    def _try_skill(self, command: str) -> Optional[tuple]:
        """Run an action-shaped command through the governed executor. Returns
        (route_key, spoken_answer) or None (→ normal path). Never raises."""
        if self.skills is None:
            return None
        q = (command or "").strip()
        for pattern, skill_name, args_fn, render in self._skill_routes():
            m = pattern.search(q)
            if not m:
                continue
            try:
                from core.skills.permissions import Permission
                skill = self.skills._registry.get(skill_name)
                if skill.permission != Permission.SAFE:
                    # matched a governed action above SAFE — never voice-run it
                    return (f"skill:{skill_name}:refused",
                            "That action needs your approval, which I can't take "
                            "by voice yet.")
                args = args_fn(m) if args_fn else {}
                result = self.skills.execute(skill_name, args)
            except Exception:  # noqa: BLE001 — an action fault never breaks the turn
                log.debug("skill route failed: %s", skill_name, exc_info=True)
                return None
            if getattr(result, "success", False):
                try:
                    answer = render(result.data)
                except Exception:  # noqa: BLE001
                    answer = "Done."
                return (f"skill:{skill_name}", answer)
            return (f"skill:{skill_name}",
                    f"I couldn't do that — {getattr(result, 'error', 'it failed')}.")
        return None

    # ── addressable brain society (M46) ──────────────────────────────────────────
    # every module has a brain, and every brain answers for itself when named:
    # "ask the vision brain what you see" / "memory brain status" / "which
    # brains do you have". Answers come straight from the brain's LAST report
    # (read-only — never a fresh tick, never the cloud).
    _BRAIN_ALIASES = {
        "vision": "vision_brain", "audio": "audio_brain", "hearing": "audio_brain",
        "spatial": "spatial_brain", "space": "spatial_brain",
        "memory": "memory_brain", "learning": "learning_brain",
        "emotion": "emotion_brain", "automation": "automation_brain",
        "pc": "automation_brain", "computer": "automation_brain",
        "laptop": "automation_brain",
        "runtime": "runtime_brain", "system": "runtime_brain",
        "knowledge": "knowledge_brain", "library": "knowledge_brain",
        "goal": "goal_brain", "goals": "goal_brain",
        "voice": "voice_brain", "conversation": "voice_brain",
        "reasoning": "reasoning_brain", "reasoner": "reasoning_brain",
        "simulation": "simulation_brain", "executive": "executive_brain",
        "trading": "trading_brain", "athena": "trading_brain",
        "market": "trading_brain", "stocks": "trading_brain",
    }
    _ROSTER_RE = re.compile(r"\b(which|what|list)\b.{0,24}\bbrains\b", re.I)
    _ASK_BRAIN_RE = re.compile(
        r"\b(" + "|".join(sorted(_BRAIN_ALIASES, key=len, reverse=True))
        + r")\s+brain\b", re.I)

    def _ask_brain(self, command: str) -> Optional[tuple]:
        """Direct route to a named brain. Returns (route_key, answer) or None
        (→ the normal path runs). Never raises — a broken brain still answers."""
        q = (command or "").lower()
        if "brain" not in q:
            return None
        if self.brains and self._ROSTER_RE.search(q):
            names = sorted(n.replace("_brain", "").replace("_", " ")
                           for n in self.brains)
            return ("roster", f"I have {len(names)} brains online: "
                    + ", ".join(names) + ". Ask any of them by name.")
        m = self._ASK_BRAIN_RE.search(q)
        if not m:
            return None
        alias = m.group(1)
        key = self._BRAIN_ALIASES[alias]
        brain = self.brains.get(key)
        if brain is None:
            return (key, f"My {alias} brain isn't online right now.")
        label = key.replace("_brain", "").replace("_", " ")
        try:
            # READ-ONLY by design (security review): an on-demand tick() would
            # run real side effects from an untrusted transcript (memory
            # promotion/forgetting/consolidation) and publish a guest-timed
            # report onto the coordinator bus. The route answers from what the
            # brain already knows — the society's own cycle stays the only
            # thing that ticks brains.
            health = brain.health() if hasattr(brain, "health") else {}
            summary = health.get("last_report") or ""
            if not summary:
                summary = (f"The {label} brain is {health.get('status', 'ok')}; "
                           "nothing to report right now.")
            if "status" in q or "health" in q:
                metrics = brain.metrics() if hasattr(brain, "metrics") else {}
                summary += (f" (status: {health.get('status', 'ok')}, "
                            f"{metrics.get('ticks', 0)} ticks, "
                            f"{metrics.get('errors', 0)} errors)")
            return (key, summary)
        except Exception:  # noqa: BLE001 — a faulty brain must not break the turn
            log.debug("brain address failed: %s", key, exc_info=True)
            return (key, f"The {label} brain is degraded and couldn't answer "
                         "just now.")

    # ── Athena, the trading subagent (M63) ───────────────────────────────────────
    # Trading questions delegate to the Trading Brain, which wraps Athena (the
    # vendored analyst). Unlike the read-only _ask_brain route, this makes a LIVE
    # call so "Athena, should I buy AAPL?" gets a real, current answer. Advisory
    # only — the subagent reads and analyses, it never places orders by voice.
    _ATHENA_RE = re.compile(
        r"\b(athena|trading brain)\b|\b(should i (buy|sell)|trade idea|"
        r"stock (tip|idea|advice)|my (portfolio|holdings)|buy or sell)\b", re.I)

    def _ask_athena(self, command: str) -> Optional[tuple]:
        """Delegate a trading question to Athena. Returns (route_key, answer) or
        None (→ the normal path runs). Never raises."""
        if not self.brains:
            return None
        q = (command or "").strip()
        if not q or not self._ATHENA_RE.search(q):
            return None
        brain = self.brains.get("trading_brain")
        if brain is None or not hasattr(brain, "ask"):
            return None
        try:
            return ("trading", brain.ask(q))
        except Exception:  # noqa: BLE001 — a trading fault never breaks the turn
            log.debug("athena route failed", exc_info=True)
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
        if self.overlay is not None:                 # show it on the private layer
            try:
                self.overlay.answer(text)
                self.overlay.set_state("speaking")
            except Exception:  # noqa: BLE001 — the overlay is best-effort
                log.debug("overlay answer failed", exc_info=True)
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

    def _nonprivate_facts(self, command: str):
        """Recall grounding facts, keeping ONLY non-private memories — this is
        the cloud boundary: nothing marked private may leave the box. Returns
        (facts, memory_used_ids)."""
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
        return facts, memory_used

    def _cloud_available(self) -> bool:
        """A cloud turn is possible if the multi-provider council OR the single
        cloud reasoner has a reachable model."""
        if self.harness is not None:
            try:
                if self.harness.has_available_provider():
                    return True
            except Exception:  # noqa: BLE001
                pass
        return self.reasoner is not None and self.reasoner.available()

    def _cloud_pass(self, command: str):
        """The cloud turn, grounded in the conversation window plus privacy-
        filtered local memories. Prefers the multi-provider COUNCIL (several of
        the user's AI subscriptions answer in parallel; a hard question is
        cross-checked and synthesized), and falls back to the single cloud
        reasoner (M42). Returns (RouterResponse, memory_used_ids) on success,
        (None, []) otherwise — the local chain then runs exactly as before."""
        facts, memory_used = self._nonprivate_facts(command)
        context = {"recent_turns": list(self._window), "facts": facts[:5],
                   "standing": self._standing(command)}
        from core.intelligence.router import RouterResponse

        # 1) the council over the user's subscriptions (never breaks a turn)
        if self.harness is not None:
            try:
                if self.harness.has_available_provider():
                    task = self.harness.run_auto_sync(command, context=context)
                    answer = getattr(getattr(task, "result", None), "text", "") or ""
                    if getattr(task, "succeeded", False) and answer.strip():
                        meta = task.result.meta or {}
                        used = meta.get("council") or [task.result.provider]
                        synth = bool(meta.get("synthesized"))
                        response = RouterResponse(
                            task="general",
                            complexity="council" if synth else "cloud",
                            strategy="harness_council" if synth
                            else f"harness:{task.result.provider}",
                            ok=True, answer=answer.strip(),
                            confidence=task.result.confidence or 0.9,
                            models_used=[f"harness:{m}" for m in used],
                            latency_ms=task.result.latency_ms)
                        return response, memory_used
            except Exception:  # noqa: BLE001 — the council must never break a turn
                log.debug("harness cloud pass failed", exc_info=True)

        # 2) fallback: the original single cloud reasoner
        if self.reasoner is None or not self.reasoner.available():
            return None, []
        reasoned = self.reasoner.reason(command, context=context)
        if not getattr(reasoned, "ok", False):
            return None, []
        response = RouterResponse(
            task="general", complexity="cloud", strategy="cloud_reasoner",
            ok=True, answer=reasoned.answer, confidence=0.9,
            models_used=[f"groq:{reasoned.model}"],
            latency_ms=reasoned.latency_ms)
        return response, memory_used

    def _local_pass(self, command: str):
        """(M54) Her OWN local reasoning brain: a real on-device model behind a
        draft→self-critique→final scaffold, grounded in local memory. Runs when
        the cloud didn't answer (off, personal, or failed), ahead of the
        keyword team / librarian / teacher.

        Unlike the cloud pass this MAY reason over private memory — nothing
        leaves the box — so it is the brain personal questions are meant for.
        Returns (RouterResponse, memory_used_ids) on a confident answer, else
        (None, [])."""
        facts: list[str] = []
        memory_used: list = []
        if self.memory is not None:
            try:
                for m in self.memory.recall(command, k=6):
                    if isinstance(m, dict) and (m.get("content") or "").strip():
                        facts.append(m["content"])
                        if m.get("id") is not None:
                            memory_used.append(m["id"])
            except Exception:  # noqa: BLE001 — grounding is best-effort
                log.debug("memory recall for local pass failed", exc_info=True)
        try:                              # local stays on-box → private is fine
            standing = self.core.render_block(include_private=True, query=command)
        except Exception:  # noqa: BLE001
            log.debug("core memory render (local) failed", exc_info=True)
            standing = ""
        reasoned = self.local_reasoner.reason(command, context={
            "recent_turns": list(self._window), "facts": facts[:5],
            "standing": standing})
        if not getattr(reasoned, "ok", False) or not (reasoned.answer or "").strip():
            return None, []
        # honest confidence: a weak local answer (e.g. reasoning over the plain
        # model team) DEFERS — return None so the chain escalates (deep pass →
        # librarian → teacher). A confident local answer (exact math, or the
        # pulled model) stands. Exact-grounded answers report ~1.0.
        confidence = float(getattr(reasoned, "confidence", 0.9) or 0.0)
        if confidence < self.escalate_threshold:
            return None, []
        from core.intelligence.router import RouterResponse
        response = RouterResponse(
            task="general", complexity="local", strategy="local_reasoner",
            ok=True, answer=reasoned.answer, confidence=confidence,
            models_used=[f"local:{reasoned.model}"],
            latency_ms=reasoned.latency_ms)
        return response, memory_used

    # ── the notebook trick (M55): her own distilled notes answer FIRST ───────────
    @staticmethod
    def _query_keywords(text: str) -> set:
        stop = {"the", "a", "an", "to", "of", "and", "or", "is", "are", "it",
                "how", "do", "does", "i", "you", "what", "whats", "why", "when",
                "where", "who", "this", "that", "with", "for", "in", "on",
                "tell", "me", "about", "can", "please", "friday"}
        return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
                if w not in stop and len(w) >= 3}

    def _notebook_pass(self, command: str):
        """Answer from her OWN knowledge base before phoning the cloud. Only a
        note that clearly covers the question counts (keyword coverage + stored
        confidence); her reader grounds the answer on the note, so it's
        provenance over generation. Returns (RouterResponse, [note_id]) or
        (None, []). Never raises."""
        if self.knowledge is None:
            return None, []
        kws = self._query_keywords(command)
        if len(kws) < 2:
            return None, []                      # too thin to look up
        try:
            entries = self.knowledge.search_knowledge(command, k=3)
        except Exception:  # noqa: BLE001 — the notebook must never break a turn
            log.debug("notebook search failed", exc_info=True)
            return None, []
        best, best_cov = None, 0.0
        for e in entries or []:
            if float(getattr(e, "confidence", 0.0) or 0.0) < 0.6:
                continue
            body = f"{getattr(e, 'title', '')} {getattr(e, 'content', '')}".lower()
            cov = sum(1 for w in kws if w in body) / len(kws)
            if cov > best_cov:
                best, best_cov = e, cov
        if best is None or best_cov < 0.6:
            return None, []                      # the notebook doesn't cover it
        try:
            grounded = self.ios.think(command, context={
                "query": command, "memories": [],
                "knowledge": [{"title": best.title, "content": best.content,
                               "confidence": best.confidence}]},
                build_context=False, use_mini_brains=False)
        except Exception:  # noqa: BLE001
            log.debug("notebook grounding failed", exc_info=True)
            return None, []
        if not getattr(grounded, "ok", False) or \
                float(getattr(grounded, "confidence", 0.0) or 0.0) < self.escalate_threshold:
            return None, []
        return grounded, [getattr(best, "id", None)]

    # "Friday, study quantum computing" — deliberate growth by owner intent
    _STUDY_RE = re.compile(
        r"^(?:please\s+)?(?:study|learn about|read up on|research)\s+"
        r"(?!my\b|me\b)(.{3,90}?)[.?!]?$", re.I)

    def _study(self, command: str) -> Optional[str]:
        """Owner-directed curriculum by voice: queue a topic for background
        distillation. Returns the confirmation, or None (→ normal routing)."""
        m = self._STUDY_RE.match((command or "").strip())
        if not m:
            return None
        topic = m.group(1).strip()
        if self.distiller is None:
            return ("I can't study on my own right now — my teacher tier "
                    "isn't configured.")
        try:
            if self.distiller.note_gap(topic, deliberate=True):
                return (f"Added to my study queue: {topic}. I'll distill it "
                        f"into my own knowledge in the background.")
            return f"I've already studied or queued {topic}."
        except Exception:  # noqa: BLE001 — a study request never breaks a turn
            log.debug("study request failed", exc_info=True)
            return None

    def _note_gap(self, command: str) -> None:
        """The cloud just answered — that's a gap in her notebook. Queue the
        topic for background distillation (personal never queues)."""
        if self.distiller is not None:
            try:
                self.distiller.note_gap(command)
            except Exception:  # noqa: BLE001 — harvesting never breaks a turn
                log.debug("note_gap failed", exc_info=True)

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

    def _standing(self, command: str) -> str:
        """The cloud-safe slice of core memory (M43): only memories explicitly
        marked private=false may ground a cloud model."""
        try:
            return self.core.render_block(include_private=False, query=command)
        except Exception:  # noqa: BLE001 — standing memory is best-effort
            log.debug("core memory render failed", exc_info=True)
            return ""

    def _teacher_context(self, reasoned_ctx: dict) -> dict:
        """Only what may leave the box: the conversation window plus memories
        NOT marked private. Anything without an explicit private=False stays
        local (unknown provenance is treated as private)."""
        facts = [m.get("content") for m in reasoned_ctx.get("memories", [])
                 if isinstance(m, dict) and m.get("private") is False
                 and (m.get("content") or "").strip()]
        return {"recent_turns": list(self._window), "facts": facts[:5],
                "standing": self._standing(reasoned_ctx.get("query", ""))}

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

        # surface what she heard on the private overlay + show she's working
        if self.overlay is not None:
            try:
                self.overlay.heard(command)
                self.overlay.set_state("thinking")
            except Exception:  # noqa: BLE001
                log.debug("overlay heard failed", exc_info=True)

        # heard badly → ask again instead of guessing (once, then stay quiet)
        heard = ctx.get("audio_confidence")
        if heard is not None and float(heard) < self.clarify_threshold:
            return self._clarify(turn, float(heard), t0)

        # small talk (greetings / thanks / how-are-you) is answered directly,
        # BEFORE any retrieval — otherwise "hello" recalls a past stored turn
        # and she parrots your own words back ("hello friday, i am fine friday")
        chit = self._smalltalk(command)
        if chit is not None:
            return self._respond_directly(turn, "smalltalk", chit, t0)

        # self-questions are answered from the Self Model, not a language model
        introspective = self._introspect(command)
        if introspective is not None:
            return self._respond_directly(turn, "self_model", introspective, t0,
                                          command=command)

        # "are you getting smarter?" → the measured answer (DecisionLog +
        # notebook growth), never a vibe
        measured = self._independence(command)
        if measured is not None:
            return self._respond_directly(turn, "independence", measured, t0,
                                          command=command)

        # "study X" → owner-directed curriculum into the distiller (M55)
        studied = self._study(command)
        if studied is not None:
            return self._respond_directly(turn, "study", studied, t0)

        # goal proposals (M28): list / approve / reject straight from the store
        proposal_answer = self._proposals(command)
        if proposal_answer is not None:
            return self._respond_directly(turn, "goal_proposals", proposal_answer,
                                          t0, command=command)

        # paused autonomous goals (M59.2): list / approve (two-step) / reject.
        # No `command=`: an approval control turn is not conversational context.
        paused_answer = self._paused_goals(command)
        if paused_answer is not None:
            return self._respond_directly(turn, "goal_approval", paused_answer, t0)

        # her accounts -- ACT: compose + owner-confirmed send ("email X saying Y",
        # "whatsapp Y saying Z"). Two-step: she drafts + reads it back, and sends
        # only on "send it". Checked early so a pending "send it"/"cancel" is caught.
        # No command= -- recipient and message are personal, off the cloud window.
        sent = self._account_action(command)
        if sent is not None:
            key, answer = sent
            return self._respond_directly(turn, key, answer, t0)

        # Athena (M63): trading questions delegate to the trading subagent, LIVE.
        # No `command=` — a portfolio/analysis answer may carry account data and
        # must not ride the conversation window to the cloud.
        traded = self._ask_athena(command)
        if traded is not None:
            key, answer = traded
            return self._respond_directly(turn, f"brain:{key}", answer, t0)

        # addressable brains (M46): a named brain answers for itself, directly.
        # No `command=` on purpose (security review): brain answers carry
        # sensor-derived state with no privacy marking — they must not enter
        # the conversation window, which rides to the cloud in recent_turns.
        asked = self._ask_brain(command)
        if asked is not None:
            key, answer = asked
            return self._respond_directly(turn, f"brain:{key}", answer, t0)

        # show / hide herself from screen capture ("show yourself" → visible to
        # everyone; the overlay is capture-excluded by default)
        visible = self._visibility(command)
        if visible is not None:
            key, answer = visible
            return self._respond_directly(turn, key, answer, t0)

        # her body (M47): action-shaped commands ("take a screenshot", "system
        # status", "set volume to 40") run through the governed skill executor.
        # No `command=` — an action confirmation is not conversational context.
        acted = self._try_skill(command)
        if acted is not None:
            key, answer = acted
            self._skill_turns += 1
            return self._respond_directly(turn, key, answer, t0)

        # her hands: owner-confirmed code execution + the "show me" that reveals
        # the last run. Both funnel to the ONE hardened WorkspaceSandbox; no
        # `command=` — a run confirmation is not conversational context.
        ran = self._run_code(command)
        if ran is not None:
            key, answer = ran
            return self._respond_directly(turn, key, answer, t0)

        shown = self._show_work(command)
        if shown is not None:
            key, answer = shown
            return self._respond_directly(turn, key, answer, t0)

        # safety: a destructive request with vague scope is clarified, not acted on
        clarified = self._clarify_destructive(command)
        if clarified is not None:
            key, answer = clarified
            return self._respond_directly(turn, key, answer, t0)

        # her accounts (Gmail / Instagram / WhatsApp / Google): "open my gmail",
        # "check my email", "any new whatsapp" — opens + reads in her browser.
        # No command= — account content is personal and stays off the cloud window.
        account = self._check_account(command)
        if account is not None:
            key, answer = account
            return self._respond_directly(turn, key, answer, t0)

        # driving Chrome: owner-confirmed click on the open page (guardrailed)
        web_acted = self._browser_action(command)
        if web_acted is not None:
            key, answer = web_acted
            return self._respond_directly(turn, key, answer, t0)

        # searching the web (drives her Chrome, reads the results page)
        searched = self._web_search(command)
        if searched is not None:
            key, answer = searched
            return self._respond_directly(turn, key, answer, t0)

        # her screen sight (M52): "read my screen" / "what's this error" — OCR
        # on-device, answer grounded in the text; the image stays local
        seen = self._read_screen(command)
        if seen is not None:
            key, answer = seen
            self._screen_reads += 1
            return self._respond_directly(turn, key, answer, t0, command=command)

        # the command gate (M59.1): an imperative no route matched is STILL a
        # command — approval-refuse or honestly decline; never essay about it
        gated = self._command_gate(command)
        if gated is not None:
            key, answer = gated
            return self._respond_directly(turn, key, answer, t0)

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

        # (M55) THE NOTEBOOK FIRST: a question her own distilled notes clearly
        # cover is answered locally — no cloud call. This is the independence
        # flywheel: every cloud answer below queues its topic for distillation,
        # so this branch catches more turns over time.
        response, memory_used = self._notebook_pass(command)
        if response is not None:
            route.append("notebook")
            self._notebook_turns += 1

        # (M56) SHE IS THE REASONING MODEL: her own deliberate mind gets first
        # shot at every turn — exact tools (math, logic, dates, units), native
        # reasoning over her own knowledge — confidence-gated, so she only
        # keeps answers she can stand behind. The cloud is demoted to the
        # fallback teacher for what she can't yet cover. This path may use
        # private memory — nothing leaves the box.
        if response is None and self.local_reasoner is not None \
                and self.local_reasoner.available():
            local_resp, memory_used = self._local_pass(command)
            if local_resp is not None:
                response = local_resp
                route.append("local_reasoner")
                self._local_turns += 1

        if response is None and self._cloud_available() \
                and not self._is_personal(command):
            cloud_tried = True
            response, memory_used = self._cloud_pass(command)
            if response is not None:
                route.append("cloud_reasoner")
                self._cloud_turns += 1
                self._note_gap(command)      # the notebook studies this topic

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
                    self._note_gap(command)  # taught once → distilled forever

            # she failed the turn everywhere → that's the STRONGEST gap signal:
            # queue the topic so a later distiller cycle studies it, and next
            # time she knows (learning from failure, not only from the cloud)
            ended_weak = (not getattr(response, "ok", False)
                          or float(getattr(response, "confidence", 0.0) or 0.0)
                          < self.escalate_threshold)
            if ended_weak and not self._is_personal(command):
                self._note_gap(command)

        answer = getattr(response, "answer", "") or ""

        # (friday-v0) VERIFY STAGE — after the chat box, rule ONE verdict on the
        # answer before it is trusted enough to be saved. The gate returns a
        # single result contract (success true/false + tier + detail). It runs
        # on-device only: it never speaks and never calls out — a failed verdict
        # simply withholds learning, it does not change what she says.
        verdict = self._verify_answer(answer, response)
        route.append("verify:" + verdict.verdict)

        self._record(turn=turn, route=route, response=response,
                     latency_ms=int((time.perf_counter() - t0) * 1000),
                     memory_used=memory_used, verify=verdict)

        # selective learning: the gate decides what (if anything) becomes memory —
        # explicit requests + personal info stored (private, local), noise dropped;
        # an unverified answer is withheld from the substantive/taught store paths.
        decision = self.gate.decide(
            command, answer,
            confidence=float(getattr(response, "confidence", 0.0) or 0.0),
            route=tuple(route), verified=verdict.success)
        self.gate.apply(self.memory, decision, command, answer, core=self.core)

        if getattr(response, "ok", False):
            self._remember_turn(command, answer)
        if self.speak_answers and getattr(response, "ok", False):
            self._say(getattr(response, "answer", ""))
        return response

    def _reopen_window(self) -> None:
        """Reopen the follow-up window when she finishes speaking, so a reply
        needs no wake word (the window is measured from her last word)."""
        state = self._conversation_state
        if state is not None:
            try:
                state.open()
            except Exception:  # noqa: BLE001
                log.debug("conversation window reopen failed", exc_info=True)

    # ── wake acknowledgment (the pipeline heard only the wake word) ──────────────
    def wake_acknowledge(self, speaker: str = "") -> None:
        """The user said her name and nothing else — answer like a person
        would instead of ignoring them; the pipeline has already opened the
        follow-up window so their next words route without re-waking."""
        if self.speak_answers:
            self._say("Yes?")

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
                "local_turns": self._local_turns,
                "notebook_turns": self._notebook_turns,
                "skill_turns": self._skill_turns,
                "screen_reads": self._screen_reads,
                "echoes_dropped": self._echoes_dropped,
                "noise_dropped": self._noise_dropped,
                "reasoner": self.reasoner.status() if self.reasoner
                else {"primary": "local"},
                "local_reasoner": self.local_reasoner.status()
                if self.local_reasoner else {"available": False},
                "distiller": self.distiller.status()
                if self.distiller else {"enabled": False},
                "neural": self.neural.status()
                if self.neural else {"enabled": False},
                "teacher": self.teacher.status() if self.teacher else {"enabled": False},
                "core_memory": self.core.status(),
                "learning": self.gate.status(),
                "degradation": self._degradation_report()}

    @staticmethod
    def _degradation_report() -> dict:
        """What isn't fully working right now — so a running FRIDAY is honest
        about her own state instead of looking fine while subtly degraded."""
        try:
            from core.observability import get_degradation_ledger
            return get_degradation_ledger().report()
        except Exception:  # noqa: BLE001 — never let self-reporting break status()
            return {"healthy": True, "failed": 0, "degraded": 0, "skipped": 0,
                    "subsystems": {}, "recent": []}

    def close(self) -> None:
        self.speech.stop()
