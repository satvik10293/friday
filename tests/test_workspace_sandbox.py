"""
tests/test_workspace_sandbox.py — the execution sandbox (FRIDAY's "hands").

Proves both halves of the contract: it actually RUNS real work (compute, stdlib,
files, artifacts) AND it refuses everything outside the safety envelope
(imports off the whitelist, reflection, OS/eval, and any file access that
escapes the workspace).
"""

from __future__ import annotations

from core.security.workspace import (
    WorkspaceSandbox, get_execution_ledger, run_task, SAFE_MODULES,
)


# ── it does real work ─────────────────────────────────────────────────────────

def test_computes_and_captures_stdout():
    rec = run_task("print(48 * 12 + 5)")
    assert rec.ok, rec.error
    assert rec.output.strip() == "581"


def test_trailing_expression_value_is_captured():
    rec = run_task("2 ** 10")
    assert rec.ok
    assert rec.value == "1024"


def test_whitelisted_import_runs():
    rec = run_task("import math\nprint(round(math.sqrt(144)))")
    assert rec.ok, rec.error
    assert rec.output.strip() == "12"


def test_file_write_stays_in_workspace_and_is_an_artifact():
    box = WorkspaceSandbox()
    try:
        rec = box.run("with open('out.txt', 'w') as f:\n    f.write('hello')\n"
                      "print('done')", task="write")
        assert rec.ok, rec.error
        assert rec.output.strip() == "done"
        assert any(a["name"] == "out.txt" for a in rec.artifacts)
    finally:
        box.wipe()


def test_stage_and_analyse_a_csv(tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    box = WorkspaceSandbox()
    try:
        assert box.stage_file(csv) == "data.csv"
        rec = box.run("import csv\n"
                      "rows = list(csv.reader(open('data.csv')))\n"
                      "print(len(rows))", task="csv")
        assert rec.ok, rec.error
        assert rec.output.strip() == "3"        # header + 2 rows
    finally:
        box.wipe()


# ── it refuses everything outside the envelope ────────────────────────────────

def test_os_import_is_refused():
    rec = run_task("import os\nos.listdir('.')")
    assert not rec.ok
    assert "os" in rec.error and "isn't allowed" in rec.error


def test_dunder_reflection_is_refused():
    rec = run_task("().__class__.__bases__")
    assert not rec.ok
    assert "underscore" in rec.error


def test_module_traversal_to_sys_is_refused():
    # the classic in-process escape: collections._sys.modules['os']
    rec = run_task("import collections\ncollections._sys")
    assert not rec.ok
    assert "underscore" in rec.error


def test_getattr_is_refused():
    rec = run_task("getattr(1, 'real')")
    assert not rec.ok
    assert "getattr" in rec.error


def test_eval_is_refused():
    rec = run_task("eval('1+1')")
    assert not rec.ok
    assert "eval" in rec.error


def test_file_access_outside_workspace_is_refused():
    rec = run_task(r"open('C:/Windows/win.ini')")
    assert not rec.ok
    assert "outside the workspace" in rec.error


def test_timeout_is_reported():
    rec = run_task("while True:\n    pass", timeout=0.5)
    assert not rec.ok
    assert "timed out" in rec.error


# ── the ledger feeds "show me" ────────────────────────────────────────────────

def test_ledger_keeps_the_last_run():
    run_task("print('hi there')", task="greet")
    last = get_execution_ledger().last()
    assert last is not None
    assert last.task == "greet"
    assert "hi there" in last.output


def test_safe_modules_excludes_the_os_and_reflection_surface():
    # os/network AND the string-driven reflection primitives the review flagged
    for banned in ("os", "sys", "subprocess", "socket", "shutil", "pathlib",
                   "operator", "functools", "random", "string", "array",
                   "importlib", "ctypes"):
        assert banned not in SAFE_MODULES


# ── red team: the exact escapes the 2026-08-08 security review demonstrated ────

def test_attrgetter_reflection_escape_is_refused():
    # operator.attrgetter('__class__') -> __subclasses__ -> BuiltinImporter -> os
    rec = run_task("import operator\n"
                   "operator.attrgetter('__class__')([])")
    assert not rec.ok
    assert "operator" in rec.error and "isn't allowed" in rec.error


def test_str_format_reflection_escape_is_refused():
    # '{0.__class__}'.format([]) traverses attributes from a STRING literal —
    # the underscore AST ban can't see it, so .format itself is blocked
    rec = run_task("'{0.__class__}'.format([])")
    assert not rec.ok
    assert "format" in rec.error


def test_format_map_is_refused():
    rec = run_task("'{0}'.format_map({})")
    assert not rec.ok
    assert "format" in rec.error


def test_star_import_is_refused():
    rec = run_task("from math import *\nprint(pi)")
    assert not rec.ok
    assert "star" in rec.error


def test_functools_reduce_import_is_refused():
    rec = run_task("import functools")
    assert not rec.ok
    assert "functools" in rec.error
