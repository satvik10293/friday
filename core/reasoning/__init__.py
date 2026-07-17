"""
core/reasoning/ — FRIDAY's own deliberate reasoning brain (M54).

A cognitive controller we author (System 2): decompose → work steps with
exact-truth grounding → synthesize → verify. Substrate-agnostic — it reasons
today over the builtin model team and sharpens when the local model is pulled.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.reasoning.engine import DeliberateReasoner, Deliberation, Step
from core.reasoning.substrate import (LocalSubstrate, ModelTeamSubstrate,
                                      Substrate, best_substrate)

log = logging.getLogger("friday.reasoning")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "friday_config.json"

__all__ = ["DeliberateReasoner", "Deliberation", "Step", "Substrate",
           "LocalSubstrate", "ModelTeamSubstrate", "best_substrate",
           "build_reasoner"]


def _reasoning_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg.get("reasoning") or {}
    except (OSError, ValueError):
        return {}


def build_reasoner(*, local_reasoner=None, ios=None) -> Optional[DeliberateReasoner]:
    """Assemble the deliberate brain over the sharpest available substrate (the
    pulled local model if ready, else the builtin team). Returns None only when
    there is no faculty at all. Never raises."""
    try:
        substrate = best_substrate(local_reasoner=local_reasoner, ios=ios)
        if substrate is None:
            return None
        cfg = _reasoning_config()
        return DeliberateReasoner(
            substrate,
            self_consistency=int(cfg.get("self_consistency", 1)),
            max_steps=int(cfg.get("max_steps", 4)),
            decompose=cfg.get("decompose", True))
    except Exception as e:  # noqa: BLE001 — the brain is optional, boot never breaks
        log.debug("reasoner build failed: %s", e)
        return None
