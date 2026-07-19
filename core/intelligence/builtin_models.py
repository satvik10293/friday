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


def _strip_question_prefix(text: str) -> str:
    """Stored conversation turns can begin with the user's question ("what is
    X? X is …"). Spoken answers must never echo the question back."""
    text = (text or "").strip()
    q = text.find("?")
    if 0 <= q < len(text) - 1:
        first = text[:q]
        if _keywords(first, k=3) and not text[:1].isdigit():
            rest = text[q + 1:].strip()
            if len(rest) >= 12:
                return rest
    return text


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

    @staticmethod
    def _best_snippets(request: InferenceRequest, k: int = 2) -> list[str]:
        """The most relevant content the context builder retrieved (memories +
        knowledge), reduced to DECLARATIVE, on-topic sentences and ranked by
        keyword overlap. Stored questions and reminders are dropped so she
        never parrots a stored 'what is the capital of Japan?' back as an
        answer (the retrieval-recite bug)."""
        from core.intelligence.mini_brains import clean_snippet, is_answer_sentence
        kws = set(_keywords(request.context.get("query") or request.prompt, k=8))
        candidates: list[str] = []
        for m in request.context.get("memories", []) or []:
            text = m.get("content") if isinstance(m, dict) else str(m)
            if text:
                candidates.append(text)
        for e in request.context.get("knowledge", []) or []:
            text = e.get("content") if isinstance(e, dict) else str(e)
            if text:
                candidates.append(text)
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for raw in candidates:
            cleaned = clean_snippet(raw)   # strip frontmatter/metadata lines
            if not cleaned:
                continue
            for s in re.split(r"(?<=[.!?])\s+", cleaned):
                s = s.strip()
                low = s.lower()
                if low in seen or not is_answer_sentence(s):
                    continue               # skip questions / reminders / dupes
                hit = kws & set(_keywords(s, k=12))
                # a DISTINCTIVE overlap only — a shared short common word
                # ("all") is not topical relevance, and reciting on it parrots
                if hit and any(len(w) >= 4 for w in hit):
                    seen.add(low)
                    scored.append((len(hit), s))
        scored.sort(key=lambda t: -t[0])
        return [s[:300] for _, s in scored[:k]]

    def _run(self, request: InferenceRequest):
        kws = _keywords(request.prompt)
        snippets = self._best_snippets(request)
        steps = [f"Identify the core of: {request.prompt[:80]}",
                 f"Key concepts: {', '.join(kws) or 'n/a'}",
                 f"Recall relevant knowledge ({len(snippets)} matches)",
                 "Answer from what I actually know"]
        if snippets:
            # speak the recalled content itself — never narrate the reasoning,
            # never echo a stored question back at the user
            answer = " ".join(_strip_question_prefix(s) for s in snippets)
            confidence = 0.7
        else:
            # honesty over theater: admit the gap at low confidence so the
            # deeper pass / learning loop kicks in instead of a fake answer
            topic = ", ".join(kws[:3]) or "that"
            answer = (f"I don't know enough about {topic} yet — "
                      "it isn't in my knowledge or memories so far.")
            confidence = 0.3
        return (answer, {"steps": steps, "keywords": kws,
                         "snippets_used": len(snippets)}, confidence)


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
        spoken = "; then ".join(f"address {kw}" for kw in kws)
        return (f"Here's my plan: first {spoken}.",
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
            return ("I don't have any memories about that yet.", {"items": []}, 0.2)
        # speak the most relevant recalled content — never narrate the count
        kws = set(_keywords(request.prompt, k=8))
        texts = [(m.get("content") if isinstance(m, dict) else str(m)) or ""
                 for m in items]
        best = max(texts, key=lambda t: len(kws & set(_keywords(t, k=12))))
        answer = _strip_question_prefix(best).strip()[:300] or \
            "I don't have any memories about that yet."
        return (answer, {"items": items},
                round(min(0.9, 0.4 + 0.1 * len(items)), 3))


def builtin_models() -> list[BaseModel]:
    """The default local model team (always available)."""
    return [ReasonerModel(), ResearchModel(), PlanningModel(),
            CodingModel(), MathModel(), MemoryModel()]
