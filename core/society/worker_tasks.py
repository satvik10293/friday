"""
core/society/worker_tasks.py — FRIDAY 4.0 (M11)
The actual work disposable workers perform. Each function is module-level and
picklable so it can run in a separate process (M10 ProcessAgentRuntime) on Windows
`spawn`. Pure, deterministic, side-effect-free — workers never touch production
state; they receive primitives and return a result dict.

Workers do NOT spawn other workers (these are plain functions); only Leaders create
workers, through the Coordinator.
"""

from __future__ import annotations

import ast
import re
from typing import Any


def math_solve(expression: str) -> dict:
    """Safely evaluate an arithmetic expression (no names/calls)."""
    node = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
               ast.USub, ast.UAdd, ast.FloorDiv)
    for n in ast.walk(node):
        if not isinstance(n, allowed):
            raise ValueError(f"disallowed expression element: {type(n).__name__}")
    return {"expression": expression, "value": eval(compile(node, "<math>", "eval"))}


def analyze_dependencies(edges: list) -> dict:
    """edges: list of [a, b] meaning a depends on b. Reports counts + cycles."""
    graph: dict = {}
    for a, b in edges:
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set())
    cycles = _has_cycle(graph)
    return {"nodes": len(graph), "edges": len(edges), "has_cycle": cycles}


def _has_cycle(graph: dict) -> bool:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    def dfs(u):
        color[u] = GREY
        for v in graph.get(u, ()):
            if color.get(v, WHITE) == GREY:
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False
    return any(color[n] == WHITE and dfs(n) for n in graph)


def review_architecture(spec: dict) -> dict:
    """Heuristic architecture review → findings list."""
    findings = []
    components = spec.get("components", [])
    if len(components) > 12:
        findings.append("high component count — consider modularising")
    if spec.get("shared_database"):
        findings.append("shared database — risks coupling/contention")
    if not spec.get("auth"):
        findings.append("no authentication layer declared")
    if spec.get("single_process") and spec.get("cpu_bound"):
        findings.append("CPU-bound work in one process — GIL bottleneck")
    return {"components": len(components), "findings": findings,
            "score": max(0.0, 1.0 - 0.2 * len(findings))}


def debug_python(code: str) -> dict:
    """Lightweight static lints (no execution)."""
    issues = []
    try:
        ast.parse(code)
    except SyntaxError as e:
        issues.append(f"syntax error: {e.msg} (line {e.lineno})")
        return {"valid": False, "issues": issues}
    if re.search(r"\bexcept\s*:", code):
        issues.append("bare except — catch specific exceptions")
    if "eval(" in code:
        issues.append("use of eval() — injection risk")
    if re.search(r"==\s*None", code):
        issues.append("use 'is None' instead of '== None'")
    return {"valid": True, "issues": issues}


def research_summarize(text: str, max_sentences: int = 3) -> dict:
    """Distil text to its most informative sentences (local, deterministic)."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if len(s.strip()) > 15]
    ranked = sorted(enumerate(sentences), key=lambda it: (-len(it[1]), it[0]))
    keep = sorted(i for i, _ in ranked[:max_sentences])
    return {"summary": " ".join(sentences[i] for i in keep), "sentences": len(sentences)}


def api_research(name: str) -> dict:
    """Produce a structured (offline) research stub about a topic/API."""
    return {"topic": name, "sections": ["overview", "endpoints", "auth", "limits"],
            "confidence": 0.4, "source": "local-stub"}


def write_documentation(topic: str, points: list) -> dict:
    """Render points into a Markdown doc."""
    body = f"# {topic}\n\n" + "\n".join(f"- {p}" for p in (points or []))
    return {"topic": topic, "markdown": body, "words": len(body.split())}


def evaluate_simulation(metrics: dict) -> dict:
    """Score a simulation outcome from its metrics (0..1)."""
    failure = float(metrics.get("failure_rate", 0.0))
    latency = float(metrics.get("avg_latency_ms", 0.0))
    score = max(0.0, 1.0 - failure - min(0.5, latency / 1000.0))
    verdict = "scales" if score >= 0.6 else ("marginal" if score >= 0.4 else "fails")
    return {"score": round(score, 3), "verdict": verdict}
