"""
core/executive — FRIDAY 4.0 (M5) Executive Brain.

FRIDAY's central cognition layer: build context, prioritize with attention, reason,
plan, and delegate execution through the M3 SkillExecutor — recording decisions,
storing learning, and emitting events. Import is side-effect free.

    from core.executive import ExecutiveBrain
    brain = ExecutiveBrain(memory_service=mem, goal_service=goals,
                           skill_executor=ex, decision_log=dl)
    reasoning = brain.think("what should I work on?")
    plan = brain.decide("build the dashboard")
    result = brain.execute_plan(plan)
"""

from .state import (
    AttentionTarget, ActiveContext, CognitiveState, CognitiveStateStore, FocusState,
)
from .reasoner import Reasoner, ReasoningResult
from .planner import (
    ExecutivePlanner, Plan, PlanDependency, PlanResult, PlanStep, PlanStepStatus,
)
from .orchestrator import Orchestrator
from .executive import ExecEvent, ExecutiveBrain, get_executive_brain

__all__ = [
    "AttentionTarget", "ActiveContext", "CognitiveState", "CognitiveStateStore", "FocusState",
    "Reasoner", "ReasoningResult",
    "ExecutivePlanner", "Plan", "PlanDependency", "PlanResult", "PlanStep", "PlanStepStatus",
    "Orchestrator",
    "ExecEvent", "ExecutiveBrain", "get_executive_brain",
]
