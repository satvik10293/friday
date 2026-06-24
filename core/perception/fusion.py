"""
core/perception/fusion.py — FRIDAY 4.0 (M6)
Sensor Fusion: combine observations from multiple sensors that refer to the same
real-world thing into a single, higher-confidence observation.

Example: the screen sensor reports "Chrome window visible" and the process sensor
reports "chrome.exe running" — fusion emits one APPLICATION observation "Chrome"
with confidence boosted above either source alone.

Rules are pluggable; confidence is combined with a noisy-or so corroboration
always *increases* certainty. Pure logic, no I/O.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import (
    Observation, ObservationConfidence, ObservationSource, ObservationType,
    new_observation,
)

log = logging.getLogger("friday.perception.fusion")


def noisy_or(confidences: list[float]) -> float:
    """Combined confidence of independent corroborating sources: 1 - Π(1 - c)."""
    prod = 1.0
    for c in confidences:
        prod *= (1.0 - ObservationConfidence.clamp(c))
    return ObservationConfidence.clamp(1.0 - prod)


@dataclass
class FusionRule:
    """Groups observations by a key derived from each, then emits one fused
    observation per group of size >= min_sources."""
    name: str
    key_fn: Callable[[Observation], Optional[str]]
    out_type: ObservationType = ObservationType.APPLICATION
    min_sources: int = 2

    def group(self, observations: list[Observation]) -> dict[str, list[Observation]]:
        groups: dict[str, list[Observation]] = {}
        for obs in observations:
            key = self.key_fn(obs)
            if key:
                groups.setdefault(key, []).append(obs)
        return {k: v for k, v in groups.items() if len(v) >= self.min_sources}


def _app_key(obs: Observation) -> Optional[str]:
    """Identify the application an observation is about, normalized for matching."""
    candidates = [
        obs.payload.get("app"), obs.payload.get("application"),
        obs.payload.get("window"), obs.payload.get("process"),
        obs.payload.get("name"),
    ]
    for c in candidates:
        if c:
            return _normalize_app(str(c))
    return None


def _normalize_app(value: str) -> str:
    v = value.lower().strip()
    for suffix in (".exe", ".app", ".bin"):
        if v.endswith(suffix):
            v = v[: -len(suffix)]
    return v.split()[0] if v else v


class SensorFusion:
    def __init__(self, rules: Optional[list[FusionRule]] = None) -> None:
        self._rules = rules if rules is not None else self._default_rules()
        self._fused = 0

    def register_rule(self, rule: FusionRule) -> None:
        self._rules.append(rule)

    def fuse(self, observations: list[Observation]) -> list[Observation]:
        """Return fused observations (does not include the raw inputs). Each fused
        observation records its source observations + a boosted confidence."""
        out: list[Observation] = []
        for rule in self._rules:
            for key, group in rule.group(observations).items():
                out.append(self._fuse_group(rule, key, group))
        self._fused += len(out)
        return out

    def fuse_and_merge(self, observations: list[Observation]) -> list[Observation]:
        """Convenience: raw observations + any fused ones."""
        return list(observations) + self.fuse(observations)

    def metrics(self) -> dict:
        return {"fused": self._fused, "rules": len(self._rules)}

    # ── internals ──────────────────────────────────────────────────────────────
    @staticmethod
    def _fuse_group(rule: FusionRule, key: str, group: list[Observation]) -> Observation:
        confidence = noisy_or([o.confidence for o in group])
        sources = sorted({o.source.name for o in group})
        merged_payload: dict = {"name": key.capitalize(), "corroborated_by": sources}
        for o in group:
            merged_payload.update({k: v for k, v in o.payload.items()
                                   if k not in ("app", "application", "process", "window")})
        fused = new_observation(
            rule.out_type, ObservationSource(name="fusion", kind="fusion"),
            payload=merged_payload, confidence=confidence,
            metadata={"subject": f"{rule.out_type.value}:{key}", "fused": True,
                      "rule": rule.name, "sources": sources, "entity_name": key.capitalize(),
                      "entity_kind": rule.out_type.value,
                      "impact": min(1.0, 0.4 + 0.2 * len(group))},
        )
        return fused

    @staticmethod
    def _default_rules() -> list[FusionRule]:
        return [
            FusionRule(name="application_detection", key_fn=_app_key,
                       out_type=ObservationType.APPLICATION, min_sources=2),
        ]
