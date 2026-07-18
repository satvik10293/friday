"""
She thinks in tokens (M57).

The user speaks natural language; her INTERNAL cognition flows as sequences
over her OWN learned vocabulary (BPE trained on her corpus) with cognitive-op
special tokens. Natural language exists only at the boundary. These tests pin:
the tokenizer (learned merges, lossless printable round-trip, persistence),
the engine's token-space flow (trace = <q> … <exact>/<step>/<answer>), and
that exactness survives token space (a digit is never lost in thought).
"""

from __future__ import annotations

from core.reasoning.engine import DeliberateReasoner
from core.reasoning.tokens import SPECIALS, FridayTokenizer

_CORPUS = [
    "photosynthesis converts sunlight into sugar inside the plant",
    "the plant uses chlorophyll to capture sunlight for photosynthesis",
    "photosynthesis releases oxygen while the plant makes sugar",
]


def _tok():
    return FridayTokenizer.train(_CORPUS, vocab_size=300)


# ── her own vocabulary ────────────────────────────────────────────────────────

def test_round_trip_is_lossless_for_printable_text():
    tok = _tok()
    for text in ["the plant makes sugar", "48 * 12 + 5 = 581",
                 "what is 15% of 240?"]:
        assert tok.decode(tok.encode(text)) == text.lower()


def test_learned_merges_compress_her_own_words():
    tok = _tok()
    ids = tok.encode("photosynthesis")
    # a word from her corpus tokenizes far tighter than character-by-character
    assert 0 < len(ids) < len("photosynthesis")


def test_cognitive_ops_are_thought_not_speech():
    tok = _tok()
    ids = tok.encode("sunlight", marker="<q>")
    assert tok.explain(ids)[0] == "<q>"            # visible in the trace
    assert tok.decode(ids) == "sunlight"           # silent at the boundary
    assert set(SPECIALS) <= set(tok.vocab)


def test_tokenizer_persists_and_reloads(tmp_path):
    tok = _tok()
    path = tok.save(tmp_path / "tokenizer.json")
    loaded = FridayTokenizer.load(path)
    text = "chlorophyll captures sunlight"
    assert loaded.encode(text) == tok.encode(text)
    assert loaded.size == tok.size


# ── the engine thinks in token space ─────────────────────────────────────────

class _Sub:
    base_confidence = 0.6

    def available(self):
        return True

    def generate(self, prompt, *, context=None, temperature=0.3):
        return "the plant uses chlorophyll."


def test_exact_answers_flow_through_token_space_unbroken():
    brain = DeliberateReasoner(_Sub(), tokenizer=_tok(), think_in_tokens=True)
    ans = brain.reason("what is 48 * 12 + 5?")
    assert ans.answer == "48 * 12 + 5 = 581"       # no digit lost in thought
    assert brain.tokens_thought > 0
    trace = brain.thought_trace()
    assert "<q>" in trace["trace"] and "<exact>" in trace["trace"]
    assert "581" in trace["text"]


def test_prose_answers_record_answer_tokens():
    brain = DeliberateReasoner(_Sub(), tokenizer=_tok(), think_in_tokens=True)
    ans = brain.reason("what does the plant use?")
    assert ans.ok
    trace = brain.thought_trace()
    assert "<answer>" in trace["trace"]
    assert "chlorophyll" in trace["text"]


def test_trace_resets_per_turn():
    brain = DeliberateReasoner(_Sub(), tokenizer=_tok(), think_in_tokens=True)
    brain.reason("what is 2 + 2?")
    first = brain.thought_trace()["tokens"]
    brain.reason("what is 3 + 3?")
    assert brain.thought_trace()["tokens"] <= first + 20   # not accumulating


def test_tokens_off_means_no_trace_and_no_tokenizer_load():
    brain = DeliberateReasoner(_Sub(), think_in_tokens=False)
    ans = brain.reason("what is 2 + 2?")
    assert ans.answer == "2 + 2 = 4"
    assert brain.tokens_thought == 0
    assert brain.thought_trace()["tokens"] == 0


def test_status_reports_her_token_mind():
    brain = DeliberateReasoner(_Sub(), tokenizer=_tok(), think_in_tokens=True)
    brain.reason("what is 2 + 2?")
    s = brain.status()
    assert s["thinks_in_tokens"] is True
    assert s["tokens_thought"] > 0 and s["vocab"] > len(SPECIALS)
