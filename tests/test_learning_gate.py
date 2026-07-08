"""
M27 — selective learning: FRIDAY does not store everything. Explicit requests
and personal info are kept (marked private, local-only); chit-chat,
clarifications and low-confidence guesses are dropped; forget requests are
honoured via soft-delete.
"""

from __future__ import annotations

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.memory import HashingEmbedder, MemoryService, MemoryStore
from core.memory.learning_gate import LearningGate


def _gate():
    return LearningGate()


# ── decisions ─────────────────────────────────────────────────────────────────

def test_explicit_remember_requests_are_always_stored_and_private():
    d = _gate().decide("remember that my project deadline is Friday", "noted", 0.4)
    assert d.store and d.private and d.importance >= 0.9
    assert d.reason == "explicit_request"


def test_personal_info_is_stored_and_private():
    d = _gate().decide("I prefer dark mode in every editor", "got it", 0.9)
    assert d.store and d.private and d.kind == "personal"


def test_small_talk_is_dropped():
    for text in ("hi", "thanks!", "okay", "good morning"):
        assert not _gate().decide(text, "hello!", 0.9).store


def test_low_confidence_answers_are_not_learned():
    d = _gate().decide("explain quantum error correction", "maybe...", 0.2)
    assert not d.store and d.reason == "low_confidence_answer"


def test_meta_turns_are_not_learned():
    assert not _gate().decide("what can you do", "…", 0.9,
                              route=("self_model",)).store
    assert not _gate().decide("mumble mumble words", "…", 0.9,
                              route=("clarify",)).store


def test_substantive_exchanges_are_learned_at_modest_importance():
    d = _gate().decide("how do faiss hnsw indexes work?", "they build graphs…", 0.8)
    assert d.store and not d.private and d.importance == 0.5


def test_forget_requests_are_detected():
    d = _gate().decide("forget what I said about my address", "", 0.9)
    assert d.forget and not d.store


# ── application against real memory ───────────────────────────────────────────

def _memory(tmp_path):
    return MemoryService(store=MemoryStore(tmp_path / "m.db"),
                         embedder=HashingEmbedder())


def test_apply_stores_both_sides_with_private_metadata(tmp_path):
    mem, gate = _memory(tmp_path), _gate()
    d = gate.decide("remember that my sister's birthday is in June", "noted", 0.9)
    ids = gate.apply(mem, d, "remember that my sister's birthday is in June", "noted")
    assert len(ids) == 2
    hit = mem.recall("sister birthday")[0]
    assert hit["metadata"]["private"] is True


def test_forget_soft_deletes_the_matching_memory(tmp_path):
    mem, gate = _memory(tmp_path), _gate()
    mid = mem.remember("user", "my address is 42 Test Lane", kind="personal")
    d = gate.decide("forget what I said about my address", "", 0.9)
    forgotten = gate.apply(mem, d, "forget what I said about my address")
    assert mid in forgotten
    assert all(h["id"] != mid for h in mem.recall("address 42 Test Lane"))
    assert gate.stats.forgotten >= 1


# ── bridge integration ────────────────────────────────────────────────────────

class _Resp:
    task, strategy, ok = "general", "direct", True
    answer, confidence = "a solid answer", 0.9
    models_used, structured, trace_id = ["friday-reasoner"], {}, "t"


class _IOS:
    def think(self, *a, **kw):
        return _Resp()


class _Log:
    def log(self, **row):
        return 0


def test_bridge_drops_chitchat_but_keeps_personal(tmp_path):
    mem = _memory(tmp_path)
    bridge = ConversationBridge(_IOS(), decision_log=_Log(), memory=mem,
                                speech=_SpeechOutput(synthesizer=lambda t: None))
    bridge.think("thanks!")
    bridge.think("my favourite language is python these days")
    learning = bridge.status()["learning"]
    assert learning["dropped"] >= 1 and learning["stored"] == 1
    assert learning["private"] == 1
