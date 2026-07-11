"""
The optional flan-t5 plugin must behave like the 3.0 local READER: it answers
by reading the retrieved evidence, not by free-generating from its own small
weights — and its confidence must be honest about which of the two it did.

(Before this was fixed, flan-t5 outranked the builtin reasoner for GENERAL
tasks on real boots, ignored the context entirely, and stamped a flat 0.7 —
above the escalation threshold — so neither taught memories nor the teacher
could ever overrule a base-model hallucination.)

All tests use a fake pipeline: no transformers import, no model download.
"""

from __future__ import annotations

from core.intelligence.base import InferenceRequest
from core.intelligence.plugins.flan_t5 import FlanT5Model


class _FakePipe:
    def __init__(self, reply="About 384,400 km."):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt, max_new_tokens=256):
        self.prompts.append(prompt)
        return [{"generated_text": self.reply}]


def _model(reply="About 384,400 km."):
    m = FlanT5Model()
    m._loaded = True              # skip load() → no warm thread, no transformers
    m._pipe = _FakePipe(reply)
    return m


def test_evidence_is_stitched_into_the_prompt():
    m = _model()
    res = m.infer(InferenceRequest(
        prompt="how far away is the moon?",
        context={"memories": [{"content": "The Moon is 384,400 km from Earth.",
                               "score": 0.9}],
                 "knowledge": [{"title": "t", "content": "Orbits are elliptical."}]}))
    assert res.ok
    prompt = m._pipe.prompts[0]
    assert "context:" in prompt and "384,400 km from Earth" in prompt
    assert "Orbits are elliptical" in prompt
    assert prompt.strip().endswith("how far away is the moon?")


def test_grounded_answers_are_confident():
    m = _model()
    res = m.infer(InferenceRequest(
        prompt="how far away is the moon?",
        context={"memories": [{"content": "The Moon is 384,400 km from Earth."}]}))
    assert res.confidence >= 0.7
    assert res.structured["grounded"] is True


def test_ungrounded_generation_stays_below_the_escalation_threshold():
    """No evidence → whatever a base-size model generates is a guess. Its
    confidence must stay below the bridge's escalate threshold (0.55) so the
    deep pass / teacher can overrule it."""
    m = _model(reply="The moon is made of cheese.")
    res = m.infer(InferenceRequest(prompt="how far away is the moon?", context={}))
    assert res.ok
    assert res.confidence < 0.55
    assert res.structured["grounded"] is False
    assert m._pipe.prompts[0] == "how far away is the moon?"   # raw, no context block


def test_empty_generation_is_low_confidence():
    m = _model(reply="")
    res = m.infer(InferenceRequest(prompt="anything", context={}))
    assert res.confidence <= 0.2


def test_load_marks_loaded_without_blocking(monkeypatch):
    """load() must return immediately (registry visibility) — the heavy
    pipeline warms on a background thread, never on the caller."""
    import threading

    m = FlanT5Model()
    started = threading.Event()
    monkeypatch.setattr(m, "_warm", started.set)
    m.load()
    assert m.loaded
    assert started.wait(2.0)      # warm-up was kicked off, off-thread
