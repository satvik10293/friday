"""
core/skills/verified_run.py — run ONE governed skill, then let the Verify gate
rule whether it actually worked.

The seam this closes: a skill's own return value is a SELF-REPORT. Even a failed
browser navigation comes back from the executor as a SuccessResult (the skill ran
without raising) carrying `{"ok": False, ...}`. Treating "the skill ran" or "the
skill says ok" as success is letting the producer mark its own homework.

Here we run the skill through the EXISTING SkillExecutor (the one governed path —
policy → role → approval → audit → DecisionLog), then hand an INDEPENDENT,
machine-checkable criterion to core.verify.Verifier and take the gate's verdict as
the truth. One skill at a time. No planner (the Executive stays the only planner);
nothing here is wired into the conversation/voice path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple


@dataclass
class SkillOutcome:
    """The result contract for a verified skill run.

    attempted  we invoked the skill through the executor.
    happened   the skill ran and SELF-REPORTS it acted (executed without error and
               its own payload says ok). The producer's word — not success on its own.
    success    the VERIFY GATE's verdict, decided by an objective check of the world,
               independent of the skill's return value. Never copied from `happened`.
    tier       how success was decided: 1 objective · 2 differential · 3 self-report.
    """

    skill: str
    args: dict
    attempted: bool = False
    happened: bool = False
    success: bool = False
    tier: int = 0
    verdict: str = "unknown"
    detail: str = ""
    observed: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"skill": self.skill, "args": self.args,
                "attempted": self.attempted, "happened": self.happened,
                "success": self.success, "tier": self.tier,
                "verdict": self.verdict, "detail": self.detail,
                "observed": self.observed}


# builder(args) -> (criteria, runner) for core.verify.Verifier. The runner reads
# the real world, NEVER the skill's return value.
ObjectiveBuilder = Callable[[dict], Tuple[dict, Optional[Callable[[str], dict]]]]


def run_verified(skill_name: str, args: dict, *, objective: ObjectiveBuilder,
                 executor=None, verifier=None) -> SkillOutcome:
    """Execute one governed skill, then rule on it with the Verify gate.

    `objective` supplies the independent, machine-checkable success criterion for
    THIS skill (see `browser_open_objective`). `success` is the gate's verdict —
    not the skill's `ok`, and not merely "the skill ran"."""
    from core.skills.executor import SkillExecutor
    from core.verify import Verifier

    executor = executor if executor is not None else SkillExecutor()
    verifier = verifier if verifier is not None else Verifier()

    out = SkillOutcome(skill=skill_name, args=dict(args or {}), attempted=True)
    result = executor.execute(skill_name, out.args)
    data = result.data if isinstance(result.data, dict) else {}
    out.observed = {"executor_success": result.success,
                    "skill_report": data or result.error}
    # self-report layer: the skill ran AND its own payload claims it acted.
    out.happened = bool(result.success and data.get("ok"))

    # objective layer: an independent check of the world decides success.
    criteria, runner = objective(out.args)
    verdict = verifier.verify(criteria=criteria, runner=runner,
                              self_confidence=1.0 if out.happened else 0.0)
    out.success = verdict.success
    out.tier = verdict.tier
    out.verdict = verdict.verdict
    out.detail = verdict.detail
    return out


# ── objective check for browser.open ────────────────────────────────────────────
def browser_open_objective(args: dict):
    """Tier-1 objective check for `browser.open`: independently re-read the LIVE
    browser and confirm it is actually on the requested host. The runner never
    looks at the skill's return value — it asks the browser what page it is on, so
    a rosy `{"ok": True}` cannot buy a pass the real page doesn't earn."""
    from urllib.parse import urlparse
    from core.web.browser import get_browser, _normalize_url

    want = urlparse(_normalize_url(str(args.get("url", ""))) or "").hostname

    def runner(_cmd: str) -> dict:
        cur = get_browser().current()          # fresh, independent read of the page
        live_url = cur.get("url", "") if isinstance(cur, dict) else ""
        host = urlparse(live_url).hostname or ""
        ok = bool(want) and host == want
        return {"exit_code": 0 if ok else 1,
                "output": f"live_url={live_url!r} host={host!r} want={want!r}"}

    criteria = {"type": "command", "cmd": f"live browser host == {want}",
                "expect_exit": 0}
    return criteria, runner
