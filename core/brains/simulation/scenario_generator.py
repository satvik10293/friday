"""
core/brains/simulation/scenario_generator.py — FRIDAY V3 (M19)
The Scenario Generator. From one intended action it produces several candidate futures —
e.g. delete-immediately (risky) vs back-up-then-delete (safe) vs ask-the-user (safest) —
so the Executive can choose. Rule-based and deterministic, but extensible: register a
custom generator `(request) -> list[Scenario]` (or inject one via the PluginService)
without changing the brain. Explicit `request.options` short-circuit to one scenario each.
"""

from __future__ import annotations

from typing import Callable

from .interfaces import Scenario, SimulationRequest
from .signals import signals_for


class ScenarioGenerator:
    def __init__(self) -> None:
        self._custom: list = []          # list[(predicate, generator)]

    def register(self, predicate: Callable[[SimulationRequest], bool],
                 generator: Callable[[SimulationRequest], list]) -> None:
        """Add a custom scenario generator for requests matching `predicate`."""
        self._custom.append((predicate, generator))

    def generate(self, request: SimulationRequest, *, max_scenarios: int = 5) -> list:
        scenarios = self._generate(request)
        return scenarios[: max(1, max_scenarios)]

    def _generate(self, request: SimulationRequest) -> list:
        # custom plugins win
        for predicate, gen in self._custom:
            try:
                if predicate(request):
                    out = gen(request)
                    if out:
                        return out
            except Exception:  # noqa: BLE001
                continue
        # explicit options → one scenario each
        if request.options:
            return [Scenario(name=str(o), steps=[str(o)], description=f"Option: {o}",
                             tags=["explicit"]) for o in request.options]
        action = (request.action or "action").strip()
        sig = signals_for(request)
        # destructive by any signal (title, args, or a declared CRITICAL tier),
        # or declared HIGH: the candidate set must include real safeguards
        if sig.destructive or sig.high_stakes:
            return [
                Scenario("immediate", [action], f"{action} immediately.", ["destructive"]),
                Scenario("backup_then", ["back up", action],
                         f"Create a backup, then {action}.", ["destructive", "backup"]),
                Scenario("ask_user", ["ask user for confirmation", action],
                         f"Ask the user, then {action}.", ["destructive", "ask_user"]),
                Scenario("dry_run", [f"simulate {action}", "report"],
                         f"Dry-run {action} without committing.", ["dry_run"]),
            ]
        if sig.external:
            return [
                Scenario("direct", [action], f"{action} directly.", ["external"]),
                Scenario("redact_then", ["redact sensitive data", action],
                         f"Redact, then {action}.", ["external", "redact"]),
                Scenario("ask_user", ["ask user for confirmation", action],
                         f"Confirm with the user, then {action}.", ["external", "ask_user"]),
            ]
        return [
            Scenario("direct", [action], f"{action} directly.", ["direct"]),
            Scenario("cautious", ["pre-check", action, "verify"],
                     f"{action} with pre-checks and verification.", ["cautious"]),
            Scenario("deferred", ["schedule", action],
                     f"Schedule {action} for later.", ["deferred"]),
        ]
