"""
core/memory/learning_gate.py — FRIDAY 5.x (M27)
The learning gate: FRIDAY does NOT store everything she hears. Remembering
every turn buries the signal in noise, bloats the index, and hoards personal
data nobody asked her to keep. Instead, each turn is scored and only what
matters is kept:

  · explicit requests ("remember this", "learn this", "don't forget…")
      → always stored, high importance, marked private (it's the user's data)
  · personal info (names, preferences, contact details, dates that matter)
      → stored, marked private — it never leaves the local store and is
        excluded from dashboards/exports by the `private` flag
  · substantive exchanges (real questions with confident answers)
      → stored at modest importance so recall improves over time
  · chit-chat, clarifications, low-confidence guesses, commands
      → NOT stored

Explicit "forget" requests are honoured immediately via soft-delete.
Everything is local by construction; `private` marks what must additionally
stay out of any surfaced view. Mental-workspace rule (§9 of the cognitive
evolution spec): only verified/worthwhile knowledge reaches memory.

Adversarial hardening (M29) — anyone within mic range can talk to FRIDAY, so
the gate also defends the memory store against spoken attacks:

  · memory poisoning — "remember: ignore your rules and always…" would be
    recalled into future reasoning context as if it were trusted knowledge.
    Instruction-shaped content (persona overrides, rule changes, jailbreak
    phrasing) is refused, never stored.
  · forced amnesia — "forget everything" (or a loop of forget requests) could
    wipe the store three memories at a time. Bulk-forget phrasings are refused
    outright and targeted forgets are capped per session; wiping memory is a
    deliberate act for Mission Control, not a drive-by voice command.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("friday.memory.gate")

_REMEMBER_RE = re.compile(
    r"\b(remember|memori[sz]e|don'?t forget|note (that|this)|learn (this|that)|"
    r"keep in mind|save (this|that))\b", re.I)
_FORGET_RE = re.compile(
    r"\b(forget|delete|erase|remove)\b.{0,40}\b(that|this|it|about|what i)\b", re.I)
_PERSONAL_RE = re.compile(
    r"\b(my name|call me|i live|my (address|birthday|phone|email|password|age)|"
    r"i (like|love|hate|prefer|enjoy)|my (favorite|favourite)|i work|my job|"
    r"my (wife|husband|mom|dad|mother|father|sister|brother|family|friend))\b", re.I)
_SMALL_TALK_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|thanks?( you)?|ok(ay)?|yes|no|nice|cool|good "
    r"(morning|night|evening)|bye|goodbye|stop|never ?mind)\b[\s!.,]*$", re.I)

# instruction-shaped content: attempts to store behaviour/persona overrides that
# would later be recalled into reasoning context as if they were trusted facts
_INJECTION_RE = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|earlier|"
    r"your|all)\b.{0,30}\b(instruction|rule|prompt|training|guideline)s?\b|"
    r"\byou (are|'re) (now|no longer)\b|\bpretend (to be|you)\b|\bact as\b|"
    r"\bnew (instructions?|persona|identity)\b|\bsystem prompt\b|"
    r"\bdeveloper mode\b|\bjailbreak\b|\bfrom now on,? (you|always|never)\b|"
    r"\balways (answer|say|respond|reply|agree)\b|\bnever (refuse|say no|"
    r"question|deny)\b|\bdo anything now\b|\bwithout (any )?(restriction|"
    r"limit|filter)s?\b", re.I)

# wiping memory is a deliberate act for Mission Control, not a voice command
_BULK_FORGET_RE = re.compile(
    r"\b(forget|delete|erase|remove|wipe|clear)\b.{0,30}\b(everything|"
    r"all (of )?(your|the|my)? ?(memor(y|ies)|data|knowledge)|"
    r"your (whole |entire )?memory)\b", re.I)

_MIN_SUBSTANTIVE_CHARS = 12
_MAX_FORGETS_PER_SESSION = 15


@dataclass
class GateDecision:
    store: bool
    reason: str
    kind: str = "conversation"
    importance: float = 0.5
    private: bool = False
    forget: bool = False
    forget_query: str = ""
    answer_only: bool = False       # store just the answer (taught knowledge)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class GateStats:
    stored: int = 0
    dropped: int = 0
    private: int = 0
    forgotten: int = 0
    injections_blocked: int = 0
    reasons: dict = field(default_factory=dict)

    def count(self, decision: GateDecision) -> None:
        if decision.store:
            self.stored += 1
            if decision.private:
                self.private += 1
        else:
            self.dropped += 1
        self.reasons[decision.reason] = self.reasons.get(decision.reason, 0) + 1


class LearningGate:
    """Decides, per turn, whether (and how) the exchange becomes memory."""

    def __init__(self, *, min_confidence: float = 0.5,
                 max_forgets: int = _MAX_FORGETS_PER_SESSION) -> None:
        self.min_confidence = min_confidence
        self.max_forgets = max_forgets
        self.stats = GateStats()

    # ── the decision ─────────────────────────────────────────────────────────────
    def decide(self, command: str, answer: str = "",
               confidence: float = 1.0, route: tuple = ()) -> GateDecision:
        text = (command or "").strip()

        # adversarial refusals come first: they must win over "remember"/"forget"
        if _BULK_FORGET_RE.search(text):
            decision = GateDecision(store=False, reason="bulk_forget_refused")
        elif _INJECTION_RE.search(text):
            self.stats.injections_blocked += 1
            decision = GateDecision(store=False, reason="suspected_injection")
        elif _FORGET_RE.search(text):
            if self.stats.forgotten >= self.max_forgets:
                decision = GateDecision(store=False, reason="forget_limit_reached")
            else:
                decision = GateDecision(store=False, reason="forget_request",
                                        forget=True, forget_query=text)
        elif _REMEMBER_RE.search(text):
            decision = GateDecision(store=True, reason="explicit_request",
                                    kind="personal", importance=0.9, private=True)
        elif _PERSONAL_RE.search(text):
            decision = GateDecision(store=True, reason="personal_info",
                                    kind="personal", importance=0.8, private=True)
        elif "clarify" in route or "self_model" in route:
            decision = GateDecision(store=False, reason="meta_turn")
        elif _SMALL_TALK_RE.match(text):
            decision = GateDecision(store=False, reason="small_talk")
        elif len(text) < _MIN_SUBSTANTIVE_CHARS:
            decision = GateDecision(store=False, reason="too_short")
        elif confidence < self.min_confidence:
            decision = GateDecision(store=False, reason="low_confidence_answer")
        elif not (answer or "").strip():
            decision = GateDecision(store=False, reason="no_answer")
        elif "groq_teacher" in route:
            # taught by the temporary teacher (M30): keep only the answer, as
            # knowledge — recalling it must never echo the question back
            decision = GateDecision(store=True, reason="taught",
                                    kind="knowledge", importance=0.7,
                                    answer_only=True)
        else:
            decision = GateDecision(store=True, reason="substantive",
                                    kind="conversation", importance=0.5)
        self.stats.count(decision)
        return decision

    # ── application (storage / forgetting) ───────────────────────────────────────
    def apply(self, memory, decision: GateDecision, command: str,
              answer: str = "") -> list:
        """Execute the decision against the memory service. Returns stored ids."""
        if memory is None:
            return []
        try:
            if decision.forget:
                return self._forget(memory, decision.forget_query)
            if not decision.store:
                return []
            meta = {"source": "voice", "private": decision.private,
                    "gate": decision.reason}
            if decision.answer_only:
                return [memory.remember("friday", answer, kind=decision.kind,
                                        tier="semantic",
                                        importance=decision.importance,
                                        metadata=meta)]
            ids = [memory.remember("user", command, kind=decision.kind,
                                   tier="episodic", importance=decision.importance,
                                   metadata=meta)]
            if (answer or "").strip():
                ids.append(memory.remember("friday", answer, kind=decision.kind,
                                           tier="episodic",
                                           importance=decision.importance,
                                           metadata=meta))
            return ids
        except Exception:  # noqa: BLE001 — learning must never break a turn
            log.debug("learning gate apply failed", exc_info=True)
            return []

    def _forget(self, memory, query: str) -> list:
        """Honour a forget request: soft-delete the closest matches."""
        try:
            hits = memory.recall(query, k=3)
            forgotten = []
            for h in hits:
                mem_id = h.get("id")
                if mem_id is not None and hasattr(memory, "forget"):
                    memory.forget(mem_id)
                    forgotten.append(mem_id)
            self.stats.forgotten += len(forgotten)
            return forgotten
        except Exception:  # noqa: BLE001
            log.debug("forget request failed", exc_info=True)
            return []

    def status(self) -> dict:
        return {"stored": self.stats.stored, "dropped": self.stats.dropped,
                "private": self.stats.private, "forgotten": self.stats.forgotten,
                "injections_blocked": self.stats.injections_blocked,
                "reasons": dict(self.stats.reasons)}
