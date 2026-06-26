"""
core/simulation/engine.py — FRIDAY 4.0 (M11)
Executes a scenario stepwise inside an isolated sandbox, recording a snapshot +
metrics per step (so it can be paused, replayed, scrubbed, forked, compared), and
analyses the run into a Recommendation.

The agent-society type is the marquee case — the "will this scale to N agents?"
stress test: ramp virtual agents toward a target, discover the failure point, then
optimise. Agent counts are modelled analytically so the engine can reason about
100k agents while only materialising a bounded representative sample in the sandbox
(LOD by design — no redesign needed to scale the numbers).
"""

from __future__ import annotations

from typing import Optional

from .models import (Recommendation, Scenario, Simulation, SimResult, SimStatus,
                     SimStep, SimulationType, VirtualGoal, VirtualTask)
from .sandbox import SimulationSandbox

_SAMPLE_CAP = 2000          # max virtual agents actually materialised (LOD)


class SimulationEngine:
    def run(self, simulation: Simulation, *, sandbox: Optional[SimulationSandbox] = None,
            steps: Optional[int] = None) -> SimResult:
        sandbox = sandbox or SimulationSandbox(name=simulation.name)
        sandbox.assert_isolated()
        scenario = simulation.scenario or Scenario(sim_type=simulation.sim_type)
        simulation.status = SimStatus.RUNNING.value

        if scenario.sim_type == SimulationType.AGENT_SOCIETY.value:
            result = self._run_agent_society(simulation, scenario, sandbox, steps)
        else:
            result = self._run_generic(simulation, scenario, sandbox, steps)

        simulation.result = result
        simulation.status = (SimStatus.COMPLETED.value if result.ok
                             else SimStatus.FAILED.value)
        return result

    # ── agent society stress test ───────────────────────────────────────────────
    def _run_agent_society(self, sim, scenario, sandbox, steps) -> SimResult:
        p = scenario.params
        target = int(p.get("target_agents", 10000))
        capacity = int(p.get("capacity", 5000))
        ramp = steps or int(p.get("steps", 10))
        optimize = bool(p.get("optimize", True))

        findings, break_step = [], None
        for i in range(ramp):
            agents = int(target * (i + 1) / ramp)
            # analytic failure model: load beyond capacity fails proportionally
            failure_rate = max(0.0, (agents - capacity) / agents) if agents else 0.0
            avg_latency = 50.0 + max(0, agents - capacity) * 0.05
            if failure_rate > 0.1 and break_step is None:
                break_step = i
                findings.append(f"failure threshold crossed at ~{agents} agents "
                                f"(capacity {capacity})")
            sim.steps.append(SimStep(index=len(sim.steps),
                                     metrics={"agents": agents, "capacity": capacity,
                                              "failure_rate": round(failure_rate, 4),
                                              "avg_latency_ms": round(avg_latency, 2)},
                                     snapshot={"phase": "ramp"},
                                     events=([f"break@{agents}"] if i == break_step else [])))

        final_failure = sim.steps[-1].metrics["failure_rate"] if sim.steps else 0.0
        if optimize and final_failure > 0.1:
            new_capacity = max(capacity, int(target * 1.1))   # scale out / shard
            optimized_failure = max(0.0, (target - new_capacity) / target)
            findings.append(f"optimisation: raise capacity to {new_capacity} "
                            f"→ failure {optimized_failure:.2%}")
            sim.steps.append(SimStep(index=len(sim.steps),
                                     metrics={"agents": target, "capacity": new_capacity,
                                              "failure_rate": round(optimized_failure, 4),
                                              "avg_latency_ms": 60.0},
                                     snapshot={"phase": "optimized"}, events=["optimized"]))
            final_failure = optimized_failure

        # materialise a bounded representative sample for visualization
        sample = min(target, _SAMPLE_CAP)
        sandbox.spawn_agents(sample)
        for a in sandbox.agents[: int(sample * final_failure)]:
            a.healthy = False

        from core.society.worker_tasks import evaluate_simulation
        verdict = evaluate_simulation({"failure_rate": final_failure,
                                       "avg_latency_ms": sim.steps[-1].metrics["avg_latency_ms"]})
        rec = Recommendation(
            text=(f"Architecture {verdict['verdict']} at {target} agents "
                  f"(final failure {final_failure:.1%})."),
            confidence=verdict["score"],
            evidence=findings)
        return SimResult(sim_id=sim.id, ok=verdict["verdict"] != "fails",
                         final_metrics=sim.steps[-1].metrics if sim.steps else {},
                         recommendation=rec, findings=findings, steps=len(sim.steps))

    # ── generic improvement-curve sim ───────────────────────────────────────────
    def _run_generic(self, sim, scenario, sandbox, steps) -> SimResult:
        p = scenario.params
        n = steps or int(p.get("steps", 8))
        risk0 = float(p.get("risk", 0.6))
        sandbox.add_goal(VirtualGoal(name=scenario.name or "objective"))
        for i in range(n):
            progress = round((i + 1) / n, 4)
            risk = round(max(0.0, risk0 * (1 - progress)), 4)
            sandbox.add_task(VirtualTask(name=f"step-{i}", done=True))
            for g in sandbox.goals:
                g.progress = progress
            sim.steps.append(SimStep(index=len(sim.steps),
                                     metrics={"progress": progress, "risk": risk},
                                     snapshot=sandbox.snapshot()))
        final_risk = sim.steps[-1].metrics["risk"] if sim.steps else 1.0
        ok = final_risk < 0.3
        rec = Recommendation(
            text=("Feasible — risk converges." if ok
                  else "Risky — residual risk remains high."),
            confidence=round(1.0 - final_risk, 3),
            evidence=[f"final risk {final_risk:.2f}", f"{n} steps simulated"])
        return SimResult(sim_id=sim.id, ok=ok,
                         final_metrics=sim.steps[-1].metrics if sim.steps else {},
                         recommendation=rec, steps=len(sim.steps))
