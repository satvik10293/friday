"""
friday_planner.py — Friday 3.0
Goal Decomposition Engine. Activated when intent is PLAN.
Breaks complex goals into structured, actionable phases.
Tracks plan state across sessions via Chronicle.
"""

import re
import time
import json
import logging
from typing import Optional
from dataclasses import dataclass, field, asdict

log = logging.getLogger("friday.planner")


# ── Plan structures ────────────────────────────────────────────────────────────

class StepStatus:
    PENDING    = "pending"
    IN_PROGRESS = "in_progress"
    DONE       = "done"
    BLOCKED    = "blocked"
    SKIPPED    = "skipped"


@dataclass
class Step:
    id:          str
    title:       str
    description: str
    status:      str   = StepStatus.PENDING
    phase:       int   = 1
    priority:    int   = 3          # 1=critical, 3=normal, 5=low
    depends_on:  list  = field(default_factory=list)
    notes:       str   = ""
    created_at:  float = field(default_factory=time.time)
    updated_at:  float = field(default_factory=time.time)


@dataclass
class Plan:
    id:          str
    goal:        str
    phases:      dict               # phase_num → phase_title
    steps:       list               # list of Step
    context:     str   = ""
    status:      str   = StepStatus.PENDING
    created_at:  float = field(default_factory=time.time)
    updated_at:  float = field(default_factory=time.time)

    def pending_steps(self) -> list:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def done_steps(self) -> list:
        return [s for s in self.steps if s.status == StepStatus.DONE]

    def progress(self) -> float:
        if not self.steps:
            return 0.0
        return len(self.done_steps()) / len(self.steps)

    def next_step(self) -> Optional[Step]:
        """Return the highest-priority unblocked pending step."""
        available = [
            s for s in self.steps
            if s.status == StepStatus.PENDING
            and all(
                any(d.id == dep and d.status == StepStatus.DONE for d in self.steps)
                or dep not in [st.id for st in self.steps]
                for dep in s.depends_on
            )
        ]
        if not available:
            return None
        return min(available, key=lambda s: (s.phase, s.priority))

    def summary(self) -> str:
        done  = len(self.done_steps())
        total = len(self.steps)
        pct   = int(self.progress() * 100)
        nxt   = self.next_step()
        next_title = nxt.title if nxt else "All steps complete"
        return (
            f"Plan: {self.goal[:60]}\n"
            f"Progress: {done}/{total} steps ({pct}%)\n"
            f"Next: {next_title}"
        )


# ── Plan parser ───────────────────────────────────────────────────────────────

_PHASE_RE  = re.compile(r"(?:phase|stage|step|part)\s*(\d+)[:\s]+(.+)", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[\s]*[-•*]\s+(.+)$", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^[\s]*(\d+)[.)]\s+(.+)$", re.MULTILINE)


def parse_plan_from_response(goal: str, response: str) -> Plan:
    """
    Parse a structured plan from Neural's response text.
    Handles: numbered lists, bullet lists, phase headers.
    """
    import uuid
    plan_id = str(uuid.uuid4())[:8]
    steps   = []
    phases  = {}
    current_phase = 1

    lines = response.split("\n")
    step_num = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Phase header detection
        phase_match = _PHASE_RE.search(line)
        if phase_match:
            current_phase = int(phase_match.group(1))
            phases[current_phase] = phase_match.group(2).strip(": —– -").strip()
            continue

        # Bold phase-like headers (## or **Phase**)
        if re.match(r"^#{1,3}\s+", line) or re.match(r"^\*\*[^*]+\*\*\s*$", line):
            clean = re.sub(r"[#*]", "", line).strip()
            if clean:
                phases[current_phase] = clean
            continue

        # Numbered step
        num_match = _NUMBERED_RE.match(line)
        if num_match:
            step_num += 1
            title = num_match.group(2).strip()
            steps.append(Step(
                id          = f"s{step_num:03d}",
                title       = title[:80],
                description = title,
                phase       = current_phase,
                priority    = 3,
            ))
            continue

        # Bullet step
        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            step_num += 1
            title = bullet_match.group(1).strip()
            steps.append(Step(
                id          = f"s{step_num:03d}",
                title       = title[:80],
                description = title,
                phase       = current_phase,
                priority    = 3,
            ))

    # If no phases were detected, create a single default phase
    if not phases:
        phases[1] = "Steps"

    # Assign sequential phases if only one phase detected
    if len(phases) == 1 and len(steps) > 5:
        chunk = max(1, len(steps) // 3)
        for i, s in enumerate(steps):
            s.phase = (i // chunk) + 1
        phases = {1: "Phase 1", 2: "Phase 2", 3: "Phase 3"}

    return Plan(
        id      = plan_id,
        goal    = goal,
        phases  = {str(k): v for k, v in phases.items()},
        steps   = steps,
        status  = StepStatus.PENDING,
    )


# ── Prompt builder ────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """You are Friday's planning specialist — structured, pragmatic, and concrete.

When creating a plan:
- Organize into clear phases (2-4 phases max)
- Each phase has 2-5 concrete steps
- Each step is a single actionable action (verb + object)
- Steps are ordered by dependency — nothing depends on something later
- Flag the 1 most critical risk or blocker
- End with: "First action: [exactly what to do right now]"

Format:
Phase 1 — [Phase Name]
1. [Step title]
2. [Step title]

Phase 2 — [Phase Name]
3. [Step title]
...

Keep each step title under 10 words. Be specific, not generic.
"""


def build_plan_prompt(goal: str, context: str = "") -> tuple[str, str]:
    """Returns (prompt, system) for the Neural call."""
    prompt = f"Create a structured execution plan for: {goal}"
    if context:
        prompt += f"\n\nContext:\n{context}"
    return prompt, _PLAN_SYSTEM


# ── Plan storage (via Chronicle) ──────────────────────────────────────────────

def save_plan(plan: Plan) -> None:
    """Persist plan to Chronicle as a structured fact."""
    try:
        from core.knowledge.friday_chronicle import save_fact
        save_fact(
            subject    = f"plan:{plan.id}",
            predicate  = "goal",
            object_    = plan.goal,
            source     = "planner",
            confidence = 1.0,
            metadata   = {
                "plan_id":    plan.id,
                "steps":      len(plan.steps),
                "phases":     plan.phases,
                "progress":   plan.progress(),
                "status":     plan.status,
                "created_at": plan.created_at,
            }
        )
        log.info("Plan saved: %s (%d steps)", plan.id, len(plan.steps))
    except Exception as e:
        log.warning("Plan save failed: %s", e)


def format_plan_for_display(plan: Plan) -> str:
    """Format a plan for voice/text output."""
    lines  = [f"Here's the plan for: {plan.goal}\n"]
    phases = sorted(plan.phases.items(), key=lambda x: int(x[0]))

    for phase_num, phase_title in phases:
        phase_steps = [s for s in plan.steps if str(s.phase) == str(phase_num)]
        if not phase_steps:
            continue
        lines.append(f"\nPhase {phase_num} — {phase_title}")
        for s in phase_steps:
            status_icon = {"done": "✓", "in_progress": "→", "blocked": "✗"}.get(s.status, "○")
            lines.append(f"  {status_icon} {s.title}")

    nxt = plan.next_step()
    if nxt:
        lines.append(f"\nFirst action: {nxt.title}")

    pct = int(plan.progress() * 100)
    if pct > 0:
        lines.append(f"\nProgress: {pct}% complete")

    return "\n".join(lines)


# ── Active plan tracker ───────────────────────────────────────────────────────

_active_plans: dict[str, Plan] = {}


def register_plan(plan: Plan) -> None:
    _active_plans[plan.id] = plan


def get_active_plans() -> list[Plan]:
    return list(_active_plans.values())


def mark_step_done(plan_id: str, step_id: str) -> bool:
    plan = _active_plans.get(plan_id)
    if not plan:
        return False
    for step in plan.steps:
        if step.id == step_id:
            step.status     = StepStatus.DONE
            step.updated_at = time.time()
            plan.updated_at = time.time()
            log.info("Step done: %s in plan %s", step.title, plan_id)
            save_plan(plan)
            return True
    return False


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_planner] Running self-test...\n")

    # Simulate a Neural response
    mock_response = """
Phase 1 — Foundation
1. Set up the project directory structure
2. Install core dependencies (groq, faiss-cpu, sentence-transformers)
3. Create friday_config.json with API keys

Phase 2 — Brain
4. Build friday_signal.py (event bus)
5. Build friday_chronicle.py (memory engine)
6. Build friday_neural.py (reasoning core)
7. Build friday_context.py (context builder)

Phase 3 — Integration
8. Build friday_spine.py (orchestrator)
9. Wire all modules through the event bus
10. End-to-end test with a real query

First action: Set up the project directory structure
"""

    goal = "Build Friday 3.0 AI system from scratch"
    plan = parse_plan_from_response(goal, mock_response)

    print(f"  ✓ Plan parsed: {plan.id}")
    print(f"  ✓ Steps:  {len(plan.steps)}")
    print(f"  ✓ Phases: {plan.phases}")
    print(f"  ✓ Next:   {plan.next_step().title if plan.next_step() else 'None'}")

    # Mark first 3 done
    for s in plan.steps[:3]:
        s.status = StepStatus.DONE
    print(f"  ✓ Progress: {int(plan.progress() * 100)}% after marking 3 done")
    print(f"  ✓ Next after progress: {plan.next_step().title}")

    # Display
    print("\n  Formatted plan:\n")
    print(format_plan_for_display(plan))

    # Register + retrieve
    register_plan(plan)
    assert len(get_active_plans()) == 1
    print(f"\n  ✓ Active plans: {len(get_active_plans())}")

    # Step done
    result = mark_step_done(plan.id, plan.steps[3].id)
    print(f"  ✓ mark_step_done: {result}")

    # Prompt builder
    prompt, system = build_plan_prompt("Build a REST API with auth")
    print(f"  ✓ Plan prompt built: {len(prompt)} chars")
    print(f"  ✓ Plan system: {len(system)} chars")

    print("\n[friday_planner] All tests passed ✓\n")
