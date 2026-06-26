"""
core/intelligence/learning_engine.py — FRIDAY 4.0 (M12)
The learning engine (Part 10). Converts experience — projects, failures,
simulations, vision discoveries, conversations, research, coding, benchmarks, user
feedback — into permanent knowledge, automatically, through the secure knowledge
API (M7). The IOS learns from what it does without ever writing to the store
directly.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ExperienceKind(str, Enum):
    PROJECT = "project"
    FAILURE = "failure"
    SIMULATION = "simulation"
    VISION = "vision"
    CONVERSATION = "conversation"
    RESEARCH = "research"
    CODING = "coding"
    BENCHMARK = "benchmark"
    FEEDBACK = "feedback"


class IntelligenceLearningEngine:
    def __init__(self, knowledge_service=None) -> None:
        self._knowledge = knowledge_service

    def learn(self, kind: str, title: str, content: str, *,
              confidence: float = 0.55) -> Optional[object]:
        """Distil one experience into knowledge (secure API). Returns the stored
        entry, or None if no knowledge service is wired or content is empty."""
        if self._knowledge is None or not (content or "").strip():
            return None
        try:
            category = self._category(kind)
            return self._knowledge.learn(content, title=title, category=category,
                                         confidence=confidence, source=f"ios:{kind}")
        except Exception:  # noqa: BLE001
            return None

    def learn_from_reasoning(self, trace: dict) -> Optional[object]:
        """Promote a high-confidence reasoning outcome into knowledge."""
        if trace.get("confidence", 0.0) < 0.6:
            return None
        return self.learn(ExperienceKind.CONVERSATION.value,
                          title=(trace.get("goal") or "Reasoning")[:80],
                          content=trace.get("outcome", ""),
                          confidence=min(0.8, trace.get("confidence", 0.6)))

    def learn_from_benchmark(self, model: str, suite: str, score: float) -> Optional[object]:
        return self.learn(ExperienceKind.BENCHMARK.value,
                          title=f"{model} on {suite}",
                          content=f"Model {model} scored {score:.2f} on the {suite} benchmark.",
                          confidence=0.7)

    def learn_from_feedback(self, feedback: str, *, positive: bool = True) -> Optional[object]:
        return self.learn(ExperienceKind.FEEDBACK.value,
                          title="User feedback",
                          content=feedback, confidence=0.75 if positive else 0.5)

    @staticmethod
    def _category(kind: str) -> str:
        from core.knowledge.knowledge_models import KnowledgeCategory
        return {
            "coding": KnowledgeCategory.PYTHON,
            "project": KnowledgeCategory.PROJECT,
            "simulation": KnowledgeCategory.SUMMARY,
            "research": KnowledgeCategory.GENERAL,
        }.get(kind, KnowledgeCategory.LESSON)
