"""
The owner-identity route: "what is my name / who am I" answered directly from
the name FRIDAY holds — never left to the general reasoner (which used to say "I
don't know your name" with the fact sitting in core memory, or parrot the
question back).
"""

from __future__ import annotations

from core.launcher.conversation import ConversationBridge


def test_my_name_regex_matches_the_askings_and_nothing_else():
    rx = ConversationBridge._MY_NAME_RE
    for yes in ("what is my name?", "what's my name", "who am I?",
                "do you know my name", "tell me my name", "my name?"):
        assert rx.search(yes), yes
    for no in ("what is the capital of France", "what is your name",
               "name three colours", "who are you"):
        assert not rx.search(no), no


def test_name_fact_parsing():
    rx = ConversationBridge._NAME_FACT_RE
    assert rx.search("my name is Satvik").group(1) == "Satvik"
    assert rx.search("please, my name is Bob now").group(1) == "Bob"
    assert rx.search("what is my name") is None       # a question isn't a fact


def test_identity_answers_from_the_stored_name():
    b = ConversationBridge(ios=None)

    class _FakeCore:                                   # deterministic, no repo data
        def all(self):
            return [{"body": "my name is Satvik", "description": ""}]

    b.core = _FakeCore()
    key, ans = b._owner_identity("what is my name?")
    assert key == "self_model" and ans == "Your name is Satvik."
    assert b._owner_identity("who am I?")[1] == "Your name is Satvik."
    assert b._owner_identity("what's the weather") is None


def test_identity_admits_when_unknown():
    b = ConversationBridge(ios=None)

    class _EmptyCore:
        def all(self):
            return []

    b.core = _EmptyCore()
    b._owner_name = ""                                 # no config seed either
    key, ans = b._owner_identity("what is my name?")
    assert key == "self_model" and "don't know your name" in ans.lower()
