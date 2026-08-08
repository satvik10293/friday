"""
core/security/workspace.py — FRIDAY 5.x

Her hands: a first-class, isolated place to actually RUN work — compute, write
and test code, analyse data, produce artifacts — and report exactly what
happened. This is the execution counterpart to core/reasoning/code.py (which
only reasons ABOUT a given snippet); here she executes a real task with a
curated standard library and her OWN filesystem, then keeps a structured record
so "show me" is real.

  · isolated workdir   — a fresh temp dir under FRIDAY's data dir, NEVER the
                         user's workspace; removed on wipe()
  · curated stdlib     — a whitelist of safe modules (math, statistics, json,
                         csv, re, datetime, itertools, collections, decimal,
                         fractions, random, string, textwrap); everything else
                         is refused
  · no escape hatch    — os / sys / subprocess / socket / eval / exec /
                         compile / getattr are AST-refused before the code runs;
                         a guarded __import__ re-checks the whitelist at runtime;
                         and EVERY underscore-prefixed name or attribute access
                         is rejected, closing the classic in-process escape
                         (`collections._sys.modules['os']`, `x.__class__` …)
  · workdir-only files — open() is replaced with one that resolves inside the
                         workdir and refuses any path that escapes it
  · limits + capture   — hard wall-clock timeout (ThreadSandbox), captured
                         stdout, captured error, output size cap
  · execution record   — a structured, inspectable ExecutionRecord per run
                         (task, code, ok, stdout, value, error, artifacts,
                         timing) kept in a process-wide ExecutionLedger so the
                         "show me" route and DecisionLog provenance can read it

SECURITY (reviewed 2026-08-08): in-process Python CANNOT fully contain
untrusted code — string-driven reflection (`str.format`, `operator.attrgetter`)
can traverse to `object.__subclasses__()` and load `os`. The whitelist + AST
guard here are DEFENCE-IN-DEPTH that raise the bar; they are NOT a trust
boundary. Therefore this box is used two ways only:
  1. code FRIDAY authored deterministically from a trusted template (safe by
     construction — the code isn't attacker-influenced); or
  2. generated/model-authored code that the OWNER has explicitly approved for
     this run (the M47/M59.2 confirmation gate) — never cloud/council code
     unattended.
Real process isolation (a locked-down subprocess + OS memory/CPU cap / Job
Object, no network) is the ThreadSandbox seam's next step and is required before
running untrusted code without a human in the loop. Also note: ThreadSandbox
cannot kill a runaway thread, so an allocation bomb can exhaust RAM before the
wall-clock timeout fires — another reason untrusted, unattended use is unsafe.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import importlib
import io
import logging
import shutil
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Optional

from core.security.sandbox import ThreadSandbox
from core.skills.exceptions import SandboxTimeout

log = logging.getLogger("friday.security.workspace")

# where run workdirs live — under FRIDAY's data dir, never the user's cwd
_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_ROOT = _ROOT / "data" / "sandbox"

_TIMEOUT_S = 5.0
_MAX_OUTPUT = 4000
_MAX_ARTIFACT_BYTES = 2_000_000        # a single artifact we'll surface

# the only stdlib the sandbox may import — pure computation, data shaping, and
# text. DELIBERATELY EXCLUDED (security review 2026-08-08): operator/functools
# (attrgetter/reduce are string→attribute reflection primitives), random (reaches
# os.urandom), string/array (Formatter / byte surface). Even so, the AST guard is
# defence-in-depth, NOT a boundary against untrusted code — see the module note.
SAFE_MODULES = frozenset({
    "math", "statistics", "json", "csv", "re", "datetime", "itertools",
    "collections", "decimal", "fractions", "textwrap", "heapq", "bisect",
})

# attribute names that are string-driven reflection escapes even without a
# leading underscore: "{0.__class__}".format(x) traverses attributes from a
# STRING LITERAL, which the underscore ban (AST-only) can't see. Block the
# method itself.
_FORBIDDEN_ATTRS = frozenset({"format", "format_map"})

# builtins the sandbox may use — pure computation + common exceptions so real
# scripts can raise/catch; no I/O, reflection, or class machinery
_SAFE_BUILTINS = {
    n: getattr(_builtins, n) for n in (
        "print", "range", "len", "abs", "min", "max", "sum", "sorted",
        "enumerate", "zip", "map", "filter", "int", "float", "str", "bool",
        "list", "dict", "set", "tuple", "round", "reversed", "any", "all",
        "divmod", "pow", "chr", "ord", "isinstance", "issubclass", "bin", "hex",
        "oct", "repr", "frozenset", "complex", "bytes", "bytearray", "slice",
        "hash", "iter", "next", "format", "ascii", "True", "False", "None",
        "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
        "ZeroDivisionError", "StopIteration", "RuntimeError", "ArithmeticError",
        "OverflowError", "ArithmeticError", "AssertionError", "NotImplementedError",
    ) if hasattr(_builtins, n)
}

# names the code may never bind or call — the reflection / execution / OS surface
_FORBIDDEN_NAMES = {
    "exec", "eval", "compile", "__import__", "input", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "hasattr", "breakpoint", "exit",
    "quit", "help", "memoryview", "object", "super", "type", "classmethod",
    "staticmethod", "property", "format_map", "dir", "id",
}


@dataclass
class ExecutionRecord:
    """A structured, inspectable record of one sandbox run — the substance of
    the 'show me' route and the provenance the DecisionLog points at."""
    task: str
    code: str
    ok: bool
    output: str = ""
    value: Optional[str] = None
    error: str = ""
    artifacts: list = field(default_factory=list)   # [{"name", "bytes"}]
    workdir: str = ""
    elapsed_ms: float = 0.0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"task": self.task, "code": self.code, "ok": self.ok,
                "output": self.output, "value": self.value, "error": self.error,
                "artifacts": list(self.artifacts), "workdir": self.workdir,
                "elapsed_ms": round(self.elapsed_ms, 1), "ts": round(self.ts, 3)}

    def summary(self) -> str:
        """One honest line for a concise reply / DecisionLog rationale."""
        if not self.ok:
            return f"ran code — failed: {self.error}"
        bits = []
        if self.output.strip():
            bits.append(f"{len(self.output.splitlines())} line(s) of output")
        if self.value is not None:
            bits.append(f"value {self.value}")
        if self.artifacts:
            bits.append(f"{len(self.artifacts)} artifact(s)")
        return "ran code — " + (", ".join(bits) if bits else "no output")


# ── the AST safety gate ───────────────────────────────────────────────────────
def _validate(tree: ast.AST) -> Optional[str]:
    """Reject anything outside the envelope BEFORE it runs. Returns a refusal
    reason, or None if the code is allowed."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            level = getattr(node, "level", 0) or 0
            if level:
                return "relative imports aren't allowed in the sandbox"
            if isinstance(node, ast.ImportFrom) and any(
                    a.name == "*" for a in node.names):
                return "star imports aren't allowed in the sandbox"
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                     else [a.name for a in node.names])
            for mod in names:
                top = (mod or "").split(".")[0]
                if top not in SAFE_MODULES:
                    return f"import of '{mod}' isn't allowed in the sandbox"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return "underscore attribute access isn't allowed"
            if node.attr in _FORBIDDEN_ATTRS:
                return f"'.{node.attr}()' isn't allowed in the sandbox"
        elif isinstance(node, ast.Name):
            if node.id.startswith("_"):
                return "underscore names aren't allowed"
            if node.id in _FORBIDDEN_NAMES:
                return f"'{node.id}' isn't allowed in the sandbox"
    return None


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    top = (name or "").split(".")[0]
    if level or top not in SAFE_MODULES:
        raise ImportError(f"import of '{name}' isn't allowed in the sandbox")
    return importlib.__import__(name, globals, locals, fromlist, level)


def _make_open(workdir: Path):
    """A replacement open() that can only touch paths inside the workdir."""
    root = workdir.resolve()
    real_open = _builtins.open

    def _open(file, mode="r", *args, **kwargs):
        if not isinstance(file, (str, Path)):
            raise PermissionError("open() needs a path string inside the workspace")
        p = Path(file)
        p = (root / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            p.relative_to(root)
        except ValueError:
            raise PermissionError("file access outside the workspace isn't allowed")
        if any(m in mode for m in ("w", "a", "x", "+")):
            p.parent.mkdir(parents=True, exist_ok=True)
        return real_open(p, mode, *args, **kwargs)

    return _open


class WorkspaceSandbox:
    """An isolated, disposable workspace for one or more runs. Create it, run
    code (optionally after staging input files), read the ExecutionRecord, then
    wipe(). Never raises out of run()."""

    def __init__(self, *, timeout: float = _TIMEOUT_S) -> None:
        _SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        self.workdir = Path(tempfile.mkdtemp(prefix="run_", dir=str(_SANDBOX_ROOT)))
        self.timeout = timeout
        self._sandbox = ThreadSandbox()

    # stage a user-provided file READ-ONLY into the workspace (e.g. a CSV to
    # analyse) so the code can open it by name without touching the real FS
    def stage_file(self, src: str | Path, *, as_name: Optional[str] = None) -> Optional[str]:
        try:
            src = Path(src)
            if src.is_symlink() or not src.is_file():
                return None                         # don't follow symlinked inputs
            name = as_name or src.name
            dst = (self.workdir / name).resolve()
            dst.relative_to(self.workdir.resolve())     # no traversal via as_name
            shutil.copy2(src, dst)
            return name
        except Exception:  # noqa: BLE001 — staging is best-effort
            log.debug("stage_file failed", exc_info=True)
            return None

    def run(self, code: str, *, task: str = "") -> ExecutionRecord:
        """Execute a snippet in the workspace with the curated stdlib. Returns an
        ExecutionRecord; `value` is the repr of the last bare expression."""
        t0 = time.perf_counter()
        code = _dedent(code or "")
        rec = ExecutionRecord(task=task or "run", code=code, ok=False,
                              workdir=str(self.workdir))
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            rec.error = f"syntax error: {e.msg} (line {e.lineno})"
            rec.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return rec
        bad = _validate(tree)
        if bad:
            rec.error = bad
            rec.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return rec

        # REPL-style: capture the value of a trailing bare expression
        body = tree.body
        if body and isinstance(body[-1], ast.Expr):
            last = body.pop()
            assign = ast.Assign(
                targets=[ast.Name(id="friday_value", ctx=ast.Store())],
                value=last.value)
            ast.copy_location(assign, last)
            body.append(assign)
            ast.fix_missing_locations(tree)

        buf = io.StringIO()

        def _print(*args, sep=" ", end="\n", **_kw):
            buf.write(sep.join(str(a) for a in args) + end)

        safe = dict(_SAFE_BUILTINS)
        safe["print"] = _print
        safe["open"] = _make_open(self.workdir)
        safe["__import__"] = _guarded_import
        ns: dict = {"__builtins__": safe}

        before = self._snapshot()

        def _exec() -> None:
            exec(compile(tree, "<friday-workspace>", "exec"), ns)  # noqa: S102 — sandboxed

        try:
            self._sandbox.run_sync(_exec, self.timeout)
            rec.ok = True
        except SandboxTimeout:
            rec.error = f"timed out after {self.timeout}s (possible infinite loop)"
        except Exception as e:  # noqa: BLE001 — a runtime error is a valid result
            rec.error = f"{type(e).__name__}: {e}"
        rec.output = buf.getvalue()[:_MAX_OUTPUT]
        v = ns.get("friday_value")
        rec.value = repr(v) if v is not None else None
        rec.artifacts = self._new_artifacts(before)
        rec.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        get_execution_ledger().record(rec)
        return rec

    def _snapshot(self) -> set:
        try:
            return {p.name for p in self.workdir.iterdir() if p.is_file()}
        except Exception:  # noqa: BLE001
            return set()

    def _new_artifacts(self, before: set) -> list:
        out = []
        try:
            for p in sorted(self.workdir.iterdir()):
                if p.is_file() and p.name not in before:
                    out.append({"name": p.name,
                                "bytes": min(p.stat().st_size, _MAX_ARTIFACT_BYTES)})
        except Exception:  # noqa: BLE001
            pass
        return out

    def wipe(self) -> None:
        try:
            shutil.rmtree(self.workdir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


# ── process-wide ledger of recent runs (feeds "show me" + provenance) ─────────
class ExecutionLedger:
    def __init__(self, *, keep: int = 16) -> None:
        self._lock = threading.Lock()
        self._recent: Deque[ExecutionRecord] = deque(maxlen=keep)

    def record(self, rec: ExecutionRecord) -> None:
        with self._lock:
            self._recent.append(rec)

    def last(self) -> Optional[ExecutionRecord]:
        with self._lock:
            return self._recent[-1] if self._recent else None

    def recent(self, n: int = 5) -> list:
        with self._lock:
            return [r.to_dict() for r in list(self._recent)[-n:][::-1]]


_ledger: Optional[ExecutionLedger] = None
_ledger_lock = threading.Lock()


def get_execution_ledger() -> ExecutionLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = ExecutionLedger()
    return _ledger


def _dedent(code: str) -> str:
    import textwrap
    return textwrap.dedent((code or "").strip("\n"))


def run_task(code: str, *, task: str = "", timeout: float = _TIMEOUT_S,
             input_files: Optional[list] = None, keep_workdir: bool = False
             ) -> ExecutionRecord:
    """One-shot convenience: fresh workspace → (stage inputs) → run → wipe.
    The ExecutionRecord (and its artifacts, if keep_workdir) outlive the box."""
    box = WorkspaceSandbox(timeout=timeout)
    try:
        for f in (input_files or []):
            box.stage_file(f)
        return box.run(code, task=task)
    finally:
        if not keep_workdir:
            box.wipe()
