"""
core/reasoning/code.py — FRIDAY 5.x (M60)
Her coding-reasoning faculty: she PROVES code behaviour instead of guessing it.

A frontier model reads code and predicts what it does; she can *run* it in a
restricted sandbox and report the real output, or analyse it with the AST and
state a checkable fact. This is the coding equivalent of the exact-math
toolbox — deterministic answers where a language model only approximates:

    · run / output   — execute a snippet safely, report exactly what it prints
                       or the value of its last expression
    · validity       — parse it; say whether it's valid Python (and the error)
    · complexity     — worst-case Big-O from loop nesting / recursion
    · explain        — a factual structural summary from the AST
    · bugs           — static lints (bare except, mutable default, '== None' …)

Safety (this executes code, so the bar is high): the snippet is AST-validated
before running — NO imports, NO dunder access, NO filesystem/eval/exec/network
names — then executed with a restricted __builtins__ (pure computation only)
under a hard wall-clock timeout. Anything outside that envelope is refused, not
run. She reasons about code; she does not become a shell.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import io
import re
from typing import Optional

from core.security.sandbox import ThreadSandbox
from core.skills.exceptions import SandboxTimeout

_SANDBOX = ThreadSandbox()
_TIMEOUT_S = 2.0
_MAX_OUTPUT = 2000

# names that must never appear — import machinery, filesystem, eval, reflection
_FORBIDDEN = {
    "exec", "eval", "compile", "open", "__import__", "input", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "breakpoint", "exit",
    "quit", "help", "memoryview", "classmethod", "staticmethod", "property",
    "object", "super", "type", "format_map",
}
# the only builtins the sandbox may use — pure computation, no I/O or reflection
_SAFE_BUILTINS = {
    n: getattr(_builtins, n) for n in (
        "print", "range", "len", "abs", "min", "max", "sum", "sorted",
        "enumerate", "zip", "map", "filter", "int", "float", "str", "bool",
        "list", "dict", "set", "tuple", "round", "reversed", "any", "all",
        "divmod", "pow", "chr", "ord", "isinstance", "bin", "hex", "oct",
        "repr", "frozenset", "complex", "bytes", "slice", "hash", "iter",
        "next", "True", "False", "None",
    ) if hasattr(_builtins, n)
}


# ── the restricted executor ──────────────────────────────────────────────────
def _reject(tree: ast.AST) -> Optional[str]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "imports aren't allowed in the sandbox"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return "double-underscore attribute access isn't allowed"
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                return "double-underscore names aren't allowed"
            if node.id in _FORBIDDEN:
                return f"'{node.id}' isn't allowed in the sandbox"
    return None


def run_code(code: str, *, timeout: float = _TIMEOUT_S) -> dict:
    """Execute a snippet in the restricted sandbox. Returns
    {ok, output, value, error}. `value` is the repr of the last bare
    expression (like a REPL). Never raises."""
    code = _dedent(code or "")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"ok": False, "output": "", "value": None,
                "error": f"syntax error: {e.msg} (line {e.lineno})"}
    bad = _reject(tree)
    if bad:
        return {"ok": False, "output": "", "value": None, "error": bad}

    # REPL-style: if the last statement is a bare expression, capture its value
    value_holder: dict = {}
    body = tree.body
    if body and isinstance(body[-1], ast.Expr):
        last = body.pop()
        assign = ast.Assign(
            targets=[ast.Name(id="__friday_value__", ctx=ast.Store())],
            value=last.value)
        ast.copy_location(assign, last)
        body.append(assign)
        ast.fix_missing_locations(tree)

    # capture output by injecting a buffer-backed print — NOT redirect_stdout,
    # which is process-global and would be left dangling by a timed-out thread
    # (a real hazard: a `while True` snippet would corrupt the app's stdout)
    buf = io.StringIO()

    def _print(*args, sep=" ", end="\n", **_kw):
        buf.write(sep.join(str(a) for a in args) + end)

    safe = dict(_SAFE_BUILTINS)
    safe["print"] = _print
    ns: dict = {"__builtins__": safe}

    def _exec() -> None:
        exec(compile(tree, "<friday-code>", "exec"), ns)  # noqa: S102 — sandboxed

    try:
        _SANDBOX.run_sync(_exec, timeout)
    except SandboxTimeout:
        return {"ok": False, "output": buf.getvalue()[:_MAX_OUTPUT],
                "value": None,
                "error": f"timed out after {timeout}s (possible infinite loop)"}
    except Exception as e:  # noqa: BLE001 — a runtime error is a valid result
        return {"ok": False, "output": buf.getvalue()[:_MAX_OUTPUT],
                "value": None, "error": f"{type(e).__name__}: {e}"}
    v = ns.get("__friday_value__", value_holder.get("v"))
    return {"ok": True, "output": buf.getvalue()[:_MAX_OUTPUT],
            "value": (repr(v) if v is not None else None), "error": ""}


# ── static analysis ──────────────────────────────────────────────────────────
def valid_python(code: str) -> dict:
    try:
        ast.parse(_dedent(code or ""))
        return {"valid": True, "error": ""}
    except SyntaxError as e:
        return {"valid": False, "error": f"{e.msg} (line {e.lineno})"}


def complexity(code: str) -> Optional[str]:
    """Worst-case Big-O from maximum loop-nesting depth; flags recursion."""
    try:
        tree = ast.parse(_dedent(code or ""))
    except SyntaxError:
        return None
    funcs = {n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)}
    recursive = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in funcs for n in ast.walk(tree))

    def depth(node: ast.AST) -> int:
        best = 0
        for child in ast.iter_child_nodes(node):
            d = depth(child)
            if isinstance(child, (ast.For, ast.While)):
                d += 1
            best = max(best, d)
        return best

    n = depth(tree)
    if recursive and n == 0:
        return "O(2^n) or O(n) — it's recursive (depends on the recurrence)."
    return {0: "O(1) — constant time, no loops.",
            1: "O(n) — a single loop over the input.",
            2: "O(n^2) — two nested loops.",
            3: "O(n^3) — three nested loops."}.get(n, f"O(n^{n}) — {n} nested loops.")


def explain(code: str) -> Optional[str]:
    """A factual structural summary from the AST — no generation."""
    try:
        tree = ast.parse(_dedent(code or ""))
    except SyntaxError:
        return None
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    loops = sum(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree))
    conds = sum(isinstance(n, ast.If) for n in ast.walk(tree))
    returns = sum(isinstance(n, ast.Return) for n in ast.walk(tree))
    parts = []
    if classes:
        parts.append(f"defines the class{'es' if len(classes) > 1 else ''} "
                     + ", ".join(classes))
    if funcs:
        parts.append(f"defines {len(funcs)} function"
                     f"{'s' if len(funcs) != 1 else ''} ("
                     + ", ".join(funcs) + ")")
    if loops:
        parts.append(f"{loops} loop{'s' if loops != 1 else ''}")
    if conds:
        parts.append(f"{conds} conditional{'s' if conds != 1 else ''}")
    if returns:
        parts.append(f"{returns} return{'s' if returns != 1 else ''}")
    if not parts:
        return "It's a short script with no functions, loops, or branches."
    return "This code " + "; ".join(parts) + "."


def bugs(code: str) -> Optional[str]:
    """Static lints via the shared worker (bare except, '== None', eval …)."""
    try:
        from core.society.worker_tasks import debug_python
        result = debug_python(_dedent(code or ""))
    except Exception:  # noqa: BLE001
        return None
    issues = result.get("issues") or []
    if not result.get("valid", True):
        return f"It won't run: {issues[0] if issues else 'a syntax error'}."
    if not issues:
        return "It parses cleanly and I see no obvious issues."
    return "A few things stand out: " + "; ".join(issues[:4]) + "."


# ── the natural-language front door ──────────────────────────────────────────
_FENCE_RE = re.compile(r"```(?:python|py)?\s*(.+?)```", re.S | re.I)
_LEADIN_RE = re.compile(
    r"\b(?:this code|the code|this snippet|following code|this)\s*:?\s*", re.I)
_OUTPUT_RE = re.compile(
    r"\bwhat (?:does|would|will).{0,30}\b(?:print|output|return|do|produce)\b|"
    r"\b(?:run|execute|evaluate) (?:this|the|it)\b|\bwhat'?s the (?:output|result)\b",
    re.I)
_VALID_RE = re.compile(
    r"\bis (?:this|the|it|that).{0,20}\bvalid\b|\bdoes (?:this|it) (?:compile|"
    r"parse|run)\b|\bany syntax errors?\b|\bwill (?:this|it) run\b", re.I)
_COMPLEX_RE = re.compile(
    r"\b(?:time )?complexity\b|\bbig[- ]?o\b|\bhow (?:fast|efficient)\b", re.I)
_EXPLAIN_RE = re.compile(
    r"\bexplain (?:this|the) code\b|\bwhat does (?:this|the) code do\b|"
    r"\bwalk me through (?:this|the) code\b", re.I)
_BUGS_RE = re.compile(
    r"\b(?:any )?bugs?\b|\bwhat'?s wrong\b|\bdebug (?:this|it)\b|"
    r"\breview (?:this|the|my) code\b|\bproblems? with (?:this|the) code\b", re.I)
# code smell: a line that looks like real Python (assignment, def, print, call)
_CODE_SMELL = re.compile(
    r"^\s*(?:def |class |for |while |if |return |print\(|import |[A-Za-z_]\w*\s*=)",
    re.M)


def _dedent(code: str) -> str:
    import textwrap
    return textwrap.dedent((code or "").strip("\n"))


def _looks_like_code(s: str) -> bool:
    """True if the text parses as Python, or clearly contains code tokens."""
    s = _dedent(s)
    if not s.strip():
        return False
    try:
        ast.parse(s)
        return True
    except SyntaxError:
        return bool(re.search(
            r"\b(?:def|for|while|return|import|lambda|class|elif)\b|"
            r"\bprint\s*\(|\brange\s*\(|[A-Za-z_]\w*\s*=[^=]", s))


def _extract_code(question: str) -> str:
    q = question or ""
    m = _FENCE_RE.search(q)
    if m:
        return m.group(1).strip()
    # code after a lead-in colon, same line or below: "what does this print: X"
    if ":" in q:
        cand = q.split(":", 1)[1].strip()
        if _looks_like_code(cand):
            return cand
    # otherwise from the first code-looking line to the end
    sm = _CODE_SMELL.search(q)
    if sm:
        return _LEADIN_RE.sub("", q[sm.start():]).strip()
    return ""


def answer(question: str) -> Optional[str]:
    """Deterministic answer ABOUT a code snippet in the question, or None if
    there's no analysable code / no code-analysis intent. Never raises."""
    q = question or ""
    code = _extract_code(q)
    if not code or not _looks_like_code(code):
        return None
    try:
        if _VALID_RE.search(q):
            v = valid_python(code)
            return ("Yes, that's valid Python." if v["valid"]
                    else f"No — {v['error']}.")
        if _COMPLEX_RE.search(q):
            return complexity(code)
        if _BUGS_RE.search(q):
            return bugs(code)
        if _EXPLAIN_RE.search(q):
            return explain(code)
        if _OUTPUT_RE.search(q):
            r = run_code(code)
            if not r["ok"]:
                return f"It raises an error: {r['error']}."
            out = r["output"].strip()
            if out:
                return f"It prints:\n{out}"
            if r["value"] is not None:
                return f"It evaluates to {r['value']}."
            return "It runs without printing anything."
    except Exception:  # noqa: BLE001 — a code faculty never breaks a turn
        return None
    return None
