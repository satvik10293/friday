"""
core/society/workers.py — FRIDAY 4.0 (M11)
The catalogue of disposable worker templates. A `WorkerTemplate` binds a name to a
picklable worker function (in society.worker_tasks) and the leader domain it serves.
Workers are created only by Leaders (via the Coordinator) and destroyed when their
task completes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import worker_tasks as wt


@dataclass(frozen=True)
class WorkerTemplate:
    name: str
    target: Callable        # picklable function from worker_tasks
    domain: str             # leader role it belongs to
    description: str = ""

    @property
    def target_name(self) -> str:
        return self.target.__name__


# name -> WorkerTemplate. The disposable specialists from the M11 brief.
WORKER_TEMPLATES: dict[str, WorkerTemplate] = {
    t.name: t for t in [
        WorkerTemplate("Python Debugger", wt.debug_python, "coding",
                       "static lint of Python source"),
        WorkerTemplate("Architecture Reviewer", wt.review_architecture, "coding",
                       "heuristic architecture review"),
        WorkerTemplate("API Researcher", wt.api_research, "research",
                       "structured API/topic research"),
        WorkerTemplate("Scientific Researcher", wt.research_summarize, "research",
                       "distil findings from text"),
        WorkerTemplate("Documentation Writer", wt.write_documentation, "knowledge",
                       "render documentation"),
        WorkerTemplate("Dependency Analyzer", wt.analyze_dependencies, "planning",
                       "dependency graph + cycle detection"),
        WorkerTemplate("Math Solver", wt.math_solve, "planning",
                       "evaluate arithmetic safely"),
        WorkerTemplate("Simulation Evaluator", wt.evaluate_simulation, "simulation",
                       "score a simulation outcome"),
    ]
}


def get_template(name: str) -> WorkerTemplate:
    return WORKER_TEMPLATES[name]


def templates_for(domain: str) -> list[WorkerTemplate]:
    return [t for t in WORKER_TEMPLATES.values() if t.domain == domain]
