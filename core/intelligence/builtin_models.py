"""
core/intelligence/builtin_models.py — FRIDAY 4.0 (M12)
The always-available, dependency-free local models. They guarantee the Intelligence
OS works with zero external dependencies (and serve as the CPU-only fallback). Each
specialises by task and produces deterministic, structured output — so model
collaboration is real even before heavier models (flan-t5, cloud plugins) register.

Models are pure: they read only `request.prompt` + `request.context` (a plain dict)
and call pure helpers. They never touch FRIDAY's stores or services.
"""

from __future__ import annotations

import re
from typing import Optional

from core.society import worker_tasks as wt
from .base import BaseModel, InferenceRequest, ModelInfo, TaskType

_WORD = re.compile(r"[a-z0-9']+")
_MATH = re.compile(r"[-+*/()\d\s.%]+")


def _keywords(text: str, k: int = 6) -> list[str]:
    stop = {"the", "a", "an", "to", "of", "and", "or", "is", "it", "how", "do",
            "i", "you", "what", "why", "this", "that", "with", "for", "in", "on"}
    counts: dict[str, int] = {}
    for w in _WORD.findall((text or "").lower()):
        if w in stop or len(w) < 3:
            continue
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


class ReasonerModel(BaseModel):
    """General chain-of-thought reasoner."""

    def __init__(self) -> None:
        super().__init__(ModelInfo(
            name="friday-reasoner", author="friday",
            capabilities={TaskType.GENERAL.value, TaskType.SCIENTIFIC.value,
                          TaskType.WRITING.value, TaskType.SIMULATION.value},
            ram_mb=8.0, avg_speed_ms=2.0, avg_accuracy=0.6, context_length=4096))

    def _run(self, request: InferenceRequest):
        kws = _keywords(request.prompt)
        ctx_bits = list(request.context.get("knowledge", []))[:3]
        steps = [f"Identify the core of: {request.prompt[:80]}",
                 f"Key concepts: {', '.join(kws) or 'n/a'}",
                 "Relate to known context" + (f" ({len(ctx_bits)} items)" if ctx_bits else " (none)"),
                 "Synthesise a conclusion"]
        conclusion = (f"Reasoned over {len(kws)} concepts"
                      + (f" using {len(ctx_bits)} context items" if ctx_bits else "")
                      + ".")
        confidence = 0.5 + 0.1 * min(3, len(ctx_bits))
        return (conclusion, {"steps": steps, "keywords": kws}, round(confidence, 3))


class ResearchModel(BaseModel):
    def __init__(self) -> None:
        super().__init__(ModelInfo(
            name="friday-research", capabilities={TaskType.RESEARCH.value, TaskType.WEB.value},
            ram_mb=6.0, avg_speed_ms=2.0, avg_accuracy=0.55))

    def _run(self, request: InferenceRequest):
        material = request.prompt + " " + " ".join(
            str(k.get("content", k)) for k in request.context.get("knowledge", []))
        summary = wt.research_summarize(material).get("summary", "")
        return (summary or "No material to research.",
                {"summary": summary}, 0.5 if summary else 0.2)


class PlanningModel(BaseModel):
    def __init__(self) -> None:
        super().__init__(ModelInfo(
            name="friday-planner",
            capabilities={TaskType.PLANNING.value, TaskType.AUTOMATION.value,
                          TaskType.AGENT_COORDINATION.value},
            ram_mb=6.0, avg_speed_ms=2.0, avg_accuracy=0.6))

    def _run(self, request: InferenceRequest):
        kws = _keywords(request.prompt, 5) or ["objective"]
        plan = [f"Step {i+1}: address '{kw}'" for i, kw in enumerate(kws)]
        return (f"Plan with {len(plan)} steps.",
                {"plan": plan, "estimated_steps": len(plan)}, 0.62)


class CodingModel(BaseModel):
    def __init__(self) -> None:
        super().__init__(ModelInfo(
            name="friday-coder", capabilities={TaskType.CODING.value},
            ram_mb=6.0, avg_speed_ms=3.0, avg_accuracy=0.65))

    def _run(self, request: InferenceRequest):
        ctx = request.context
        if ctx.get("code"):
            r = wt.debug_python(ctx["code"])
            return (f"{len(r['issues'])} issue(s) found.", r, 0.7 if r["valid"] else 0.4)
        if ctx.get("architecture"):
            r = wt.review_architecture(ctx["architecture"])
            return (f"{len(r['findings'])} finding(s).", r, r["score"])
        return ("Provide code or architecture for analysis.",
                {"hint": "pass context['code'] or context['architecture']"}, 0.3)


class MathModel(BaseModel):
    def __init__(self) -> None:
        super().__init__(ModelInfo(
            name="friday-math", capabilities={TaskType.MATH.value},
            ram_mb=2.0, avg_speed_ms=1.0, avg_accuracy=0.99))

    def _run(self, request: InferenceRequest):
        expr = request.context.get("expression")
        if not expr:
            candidates = [m.strip() for m in _MATH.findall(request.prompt)
                          if any(c.isdigit() for c in m) and any(op in m for op in "+-*/")]
            expr = max(candidates, key=len).strip() if candidates else ""
        if not expr:
            return ("No arithmetic expression found.", {}, 0.1)
        r = wt.math_solve(expr)
        return (f"{expr} = {r['value']}", r, 0.99)


class MemoryModel(BaseModel):
    def __init__(self) -> None:
        super().__init__(ModelInfo(
            name="friday-memory", capabilities={TaskType.MEMORY_RETRIEVAL.value},
            ram_mb=2.0, avg_speed_ms=1.0, avg_accuracy=0.7))

    def _run(self, request: InferenceRequest):
        mems = request.context.get("memories", [])
        know = request.context.get("knowledge", [])
        items = (mems + know)[:5]
        if not items:
            return ("No relevant memories or knowledge in context.", {"items": []}, 0.2)
        return (f"Recalled {len(items)} relevant item(s).",
                {"items": items}, round(min(0.9, 0.4 + 0.1 * len(items)), 3))


def builtin_models() -> list[BaseModel]:
    """The default local model team (always available)."""
    return [ReasonerModel(), ResearchModel(), PlanningModel(),
            CodingModel(), MathModel(), MemoryModel()]
