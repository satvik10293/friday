"""
core/verify/gate.py — the Verify gate, extracted from friday-v0.

friday-v0's OPVER loop earns trust in a result by VERIFYING it — the strongest
check available — before it counts a step as done, rather than letting the
producer mark its own homework. That verify step is the reusable part: given a
produced result (an "artifact") and, optionally, machine-checkable success
criteria, it rules ONE verdict — a single result contract — on whether the
result stands.

Three tiers, strongest first (verbatim to friday-v0's design):

    1 objective     file exists / file contains / a command's exit code —
                    a fact about the world, not an opinion.
    2 differential  a SECOND, independent checker (fresh context) sees ONLY the
                    criteria + the artifact, never how it was produced, and
                    rules PASS or FAIL. Injected as `checker`; no checker → skip.
    3 self-report   nothing objective to check and no second opinion available —
                    trust the producer's own confidence, logged as the low tier.

The gate is pure-stdlib and NEVER raises: a verification fault is data (a
`VerifyResult`), never an exception that breaks the caller. Objective file
checks are read-only; a "command" criterion runs ONLY through an injected
`runner` — there is no built-in command execution here, so importing and using
this gate has no hidden side effects. Mirrors friday-v0/core.py `_verify`,
`_check_objective`, and `_differential`, and its workspace path-safety
(`tools.py` `_resolve`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("friday.verify")


# ── the one result contract every verify call returns ───────────────────────────────
@dataclass
class VerifyResult:
    """The single result contract: did the artifact pass, by what tier, and why.

    `success` is the verdict as a boolean (the thing a gate acts on); `verdict`
    is the same as a word ("pass" | "fail" | "unknown"); `tier` records HOW it
    was decided (1 objective · 2 differential · 3 self-report · 0 no verdict)."""

    success: bool
    verdict: str = "unknown"
    tier: int = 0
    detail: str = ""

    def to_dict(self) -> dict:
        return {"success": self.success, "verdict": self.verdict,
                "tier": self.tier, "detail": self.detail}


_OBJECTIVE_TYPES = {"file_exists", "file_contains", "command"}


class Verifier:
    """The verify gate. One public method — `verify()` — returns one
    `VerifyResult`. Faithful to friday-v0: an objective criterion beats a second
    opinion, which beats self-report. Everything beyond the artifact is optional
    and injected, so the gate has no hidden side effects and never raises."""

    def __init__(self, *, self_report_threshold: float = 0.5) -> None:
        self.self_report_threshold = self_report_threshold

    def verify(self, *, artifact: str = "", criteria: Optional[dict] = None,
               checker: Optional[Callable[[str, str], str]] = None,
               self_confidence: Optional[float] = None,
               workspace: Optional[str] = None,
               runner: Optional[Callable[[str], dict]] = None) -> VerifyResult:
        """Return the strongest verdict available for `artifact`.

            criteria         machine-checkable success spec (Tier 1) — one of
                             {"type": "file_exists", "path": ...},
                             {"type": "file_contains", "path": ..., "substring": ...},
                             {"type": "command", "cmd": ..., "expect_exit": 0}
            checker          a second, independent judge (Tier 2):
                             checker(criteria_text, artifact) -> a line whose
                             first word is PASS or FAIL. None → tier skipped.
            self_confidence  the producer's own confidence (Tier 3 fallback).
            workspace        root that file paths resolve under (read-only); a
                             path that escapes it is refused. None → cwd.
            runner           how a "command" criterion runs: runner(cmd) ->
                             {"exit_code": int, "output"/"error": str}. None →
                             a command criterion is left unchecked (fails safe).
        """
        try:
            return self._verify(artifact, criteria, checker, self_confidence,
                                workspace, runner)
        except Exception:  # noqa: BLE001 — a verify fault is data, never a crash
            log.debug("verify failed", exc_info=True)
            return VerifyResult(success=False, verdict="unknown", tier=0,
                                detail="verifier error")

    # ── tiered decision (friday-v0/core.py _verify) ──────────────────────────────
    def _verify(self, artifact, criteria, checker, self_confidence, workspace,
                runner) -> VerifyResult:
        crit = criteria or {}
        if crit.get("type") in _OBJECTIVE_TYPES:
            ok, detail = self._check_objective(crit, workspace, runner)
            return VerifyResult(ok, "pass" if ok else "fail", 1, detail)
        if checker is not None:
            verdict, detail = self._differential(crit, artifact, checker)
            if verdict in ("pass", "fail"):
                return VerifyResult(verdict == "pass", verdict, 2, detail)
        return self._self_report(self_confidence)

    # ── Tier 1: objective (friday-v0/core.py _check_objective) ───────────────────
    def _check_objective(self, crit, workspace, runner) -> tuple[bool, str]:
        ctype = crit["type"]
        if ctype == "file_exists":
            p = self._path(crit.get("path", ""), workspace)
            ok = p is not None and p.is_file()
            return ok, f"file_exists {crit.get('path')}: {'found' if ok else 'missing'}"
        if ctype == "file_contains":
            p = self._path(crit.get("path", ""), workspace)
            if p is None or not p.is_file():
                return False, f"file_contains: {crit.get('path')} missing"
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return False, f"file_contains: unreadable ({type(e).__name__})"
            hit = crit.get("substring", "") in text
            return hit, f"file_contains '{crit.get('substring')}': {'yes' if hit else 'no'}"
        # command — runs ONLY through an injected runner; none → cannot check
        if runner is None:
            return False, f"command '{crit.get('cmd')}' not checked (no runner)"
        r = runner(crit.get("cmd", "")) or {}
        expect = crit.get("expect_exit", 0)
        ok = r.get("exit_code") == expect
        tail = (r.get("output") or r.get("error") or "")[-200:]
        return ok, f"`{crit.get('cmd')}` exit={r.get('exit_code')} (want {expect}) {tail}"

    # ── Tier 2: differential — a second, blind judge (friday-v0 _differential) ────
    @staticmethod
    def _differential(crit, artifact, checker) -> tuple[str, str]:
        criteria_text = ", ".join(f"{k}={v}" for k, v in (crit or {}).items()) \
            or "the answer is correct, relevant, and complete"
        try:
            raw = checker(criteria_text, artifact or "") or ""
        except Exception:  # noqa: BLE001 — a broken judge abstains, never crashes
            return "unknown", "checker error"
        text = str(raw).strip()
        verdict = "pass" if re.match(r"\s*pass", text, re.I) else \
                  "fail" if re.match(r"\s*fail", text, re.I) else "unknown"
        return verdict, text[:200]

    # ── Tier 3: self-report (friday-v0: pass, low confidence) ────────────────────
    def _self_report(self, self_confidence) -> VerifyResult:
        if self_confidence is None:
            return VerifyResult(True, "pass", 3, "self-reported, low confidence")
        conf = float(self_confidence)
        ok = conf >= self.self_report_threshold
        return VerifyResult(
            ok, "pass" if ok else "fail", 3,
            f"self-reported confidence {conf:.2f} "
            f"{'>=' if ok else '<'} {self.self_report_threshold:.2f}")

    # ── path safety (friday-v0/tools.py _resolve): read-only, no escapes ─────────
    @staticmethod
    def _path(path: str, workspace) -> Optional[Path]:
        if not path:
            return None
        try:
            if workspace:
                root = Path(workspace).resolve()
                p = Path(path).resolve() if Path(path).is_absolute() \
                    else (root / path).resolve()
                p.relative_to(root)           # ValueError if it escapes the root
                return p
            return Path(path).resolve()
        except (ValueError, OSError):
            return None
