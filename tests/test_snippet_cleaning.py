"""
Real-world fix: she must speak prose, not vault-note metadata.

Knowledge lives in the Obsidian vault as `---frontmatter---` + body notes.
When she recalled one and spoke it, the frontmatter (url/relevance/fetched_at/
embed_idx/fact_id/source) leaked into the answer:
  "url: relevance: 0.7 fetched_at: ... I'm Friday v3.0, Satvik's AI partner."
clean_snippet() strips frontmatter + metadata lines everywhere retrieved
content becomes a spoken answer.
"""

from __future__ import annotations

from core.intelligence.mini_brains import RecallBrain, clean_snippet

_VAULT_NOTE = """---
url:
relevance: 0.7
fetched_at: 2026-06-22T14:04:26.040200
expires_at:
embed_idx: 43
---

I'm Friday v3.0, Satvik's AI partner, built from Python."""


def test_frontmatter_is_stripped_to_prose():
    assert clean_snippet(_VAULT_NOTE) == \
        "I'm Friday v3.0, Satvik's AI partner, built from Python."


def test_metadata_only_note_collapses_to_empty():
    assert clean_snippet("fact_id: 030f14\nsource: chronicle.sovereign\n"
                         "category: fact\ntitle: Friday") == ""


def test_plain_prose_is_untouched():
    prose = "Satvik prefers metric units for measurements."
    assert clean_snippet(prose) == prose


def test_inline_metadata_lines_removed_keeps_body():
    note = ("title: who are you\nrelevance: 0.7\n\n"
            "Friday is a local AI assistant that runs on this machine.")
    assert clean_snippet(note) == \
        "Friday is a local AI assistant that runs on this machine."


class _Mem:
    def __init__(self, rows):
        self._rows = rows

    def recall(self, query, k=3):
        return self._rows


def test_recall_brain_never_speaks_metadata():
    brain = RecallBrain(memory=_Mem([
        {"content": _VAULT_NOTE, "score": 0.9},
        {"content": "fact_id: abc\nsource: x", "score": 0.9},   # metadata-only
    ]))
    answer = brain.answer("what do you know about Friday")
    assert answer is not None
    for leak in ("url:", "relevance:", "fetched_at:", "embed_idx:", "fact_id:",
                 "source:", "---"):
        assert leak not in answer, f"metadata leaked: {leak!r} in {answer!r}"
    assert "Satvik's AI partner" in answer
