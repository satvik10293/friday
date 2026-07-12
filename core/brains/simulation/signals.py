"""
core/brains/simulation/signals.py — FRIDAY V3 (M41)
The single source of truth for action semantics. Every pipeline stage
(scenarios, prediction, risk) used to keep its own keyword tuples and judge
an action ONLY by the English words in its title — so a CRITICAL skill named
`shell.run` with args `{"command": "rm -rf ..."}` scored as a harmless
generic action and sailed through deliberation.

Signals now combine three sources:
  · the action title (keyword scan, as before)
  · the Executive's DECLARED risk tier (`context["risk_level"]` — HIGH or
    CRITICAL straight from the skills registry; the registry outranks
    keyword guessing)
  · the skill ARGS (`context["args"]` values — where the actual command,
    path, or recipient usually lives)
"""

from __future__ import annotations

from dataclasses import dataclass

_DESTRUCTIVE = ("delete", "remove", "format", "overwrite", "drop", "wipe",
                "erase", "rm -", "rmdir", "del ", "shutdown", "kill",
                "terminate", "uninstall")
_EXTERNAL = ("send", "share", "post", "upload", "email", "publish")
_SENSITIVE = _EXTERNAL + ("credential", "password", "key", "token",
                          "personal", "secret")

# tags that mark a scenario as having a safeguard step
MITIGATION_TAGS = frozenset({"backup", "ask_user", "dry_run", "cautious", "redact"})


@dataclass(frozen=True)
class ActionSignals:
    destructive: bool
    external: bool
    sensitive: bool
    declared: str            # "", "LOW", "MEDIUM", "HIGH", "CRITICAL"

    @property
    def high_stakes(self) -> bool:
        return self.declared in ("HIGH", "CRITICAL")


def signals_for(request) -> ActionSignals:
    """Extract the risk-relevant signals for a simulation request."""
    ctx = getattr(request, "context", None) or {}
    declared = str(ctx.get("risk_level", "") or "").upper()
    args = ctx.get("args") or {}
    args_text = " ".join(f"{k} {v}" for k, v in args.items()).lower() \
        if isinstance(args, dict) else str(args).lower()
    text = f"{(getattr(request, 'action', '') or '').lower()} {args_text}"
    return ActionSignals(
        destructive=any(k in text for k in _DESTRUCTIVE) or declared == "CRITICAL",
        external=any(k in text for k in _EXTERNAL),
        sensitive=any(k in text for k in _SENSITIVE),
        declared=declared,
    )


def is_mitigated(tags) -> bool:
    return bool(set(tags or ()) & MITIGATION_TAGS)
