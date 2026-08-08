"""
tests/test_code_run_route.py — the owner-confirmed code-execution route.

Unit-covers the two riskiest, instance-free pieces: pulling a runnable snippet
ONLY from an explicit run request (so "what does this print" still goes to
code-reasoning), and composing a concise, honest result line.
"""

from __future__ import annotations

import types

from core.launcher.conversation import ConversationBridge as CB
from core.security.workspace import ExecutionRecord


def _clarify_stub():
    # the destructive-clarify route reads only these three class-level patterns
    return types.SimpleNamespace(
        _DESTRUCTIVE_RE=CB._DESTRUCTIVE_RE,
        _VAGUE_SCOPE_RE=CB._VAGUE_SCOPE_RE,
        _SPECIFIC_PATH_RE=CB._SPECIFIC_PATH_RE,
    )


def test_extract_runnable_requires_explicit_run_intent():
    assert CB._extract_runnable("run this code: print(2 + 2)") == "print(2 + 2)"
    assert CB._extract_runnable("execute: y = 5\nprint(y)").startswith("y = 5")
    assert "print(1)" in CB._extract_runnable("run ```python\nprint(1)\n```")


def test_extract_runnable_ignores_analysis_questions():
    # no run/execute verb -> not captured (code-reasoning handles these)
    assert CB._extract_runnable("what does this print: print(2 + 2)") == ""
    assert CB._extract_runnable("is this valid python: def f(): pass") == ""
    assert CB._extract_runnable("how are you today") == ""


def test_describe_run_reports_output_concisely():
    rec = ExecutionRecord(task="t", code="print(1)", ok=True, output="55\n")
    line = CB._describe_run(rec)
    assert "printed" in line and "55" in line


def test_describe_run_is_honest_about_failure():
    rec = ExecutionRecord(task="t", code="boom", ok=False, error="ValueError: x")
    assert "didn't run cleanly" in CB._describe_run(rec)
    assert "ValueError" in CB._describe_run(rec)


def test_vague_destructive_request_is_clarified():
    r = CB._clarify_destructive(_clarify_stub(), "delete the old files")
    assert r is not None and r[0] == "clarify:destructive"
    assert CB._clarify_destructive(_clarify_stub(), "delete everything") is not None


def test_specific_deletion_is_not_intercepted():
    # a concrete file/path is unambiguous -> let the normal flow handle it
    assert CB._clarify_destructive(_clarify_stub(), "delete report.docx") is None
    assert CB._clarify_destructive(_clarify_stub(), r"remove C:\temp\log.txt") is None


def test_nondestructive_requests_are_ignored():
    assert CB._clarify_destructive(_clarify_stub(), "what's the weather") is None
    assert CB._clarify_destructive(_clarify_stub(), "remove the background noise") is None
