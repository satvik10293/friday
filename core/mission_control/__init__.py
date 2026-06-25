"""
core/mission_control/ — FRIDAY 4.0 (M10)
Mission Control: the operational cockpit / central nervous system of FRIDAY. A
hybrid HUD — 3D (Three.js/WebGL) for cognitive structures (knowledge galaxy, goal
network, agent teams, cognitive state, world model) and 2D overlays for alerts,
resources, security, approvals, and failures — on a single screen, no tabs.

Resilient by construction: every subsystem is read through a guarded call, so any
individual system (memory, knowledge, portal, agent runtime, executive brain,
embeddings) may degrade without collapsing the cockpit.

Side-effect-free to import (no server starts, no DB opens at import).
"""

from __future__ import annotations

from .aggregator import MissionControlAggregator
from .events import EventStream
from .resilience import Degraded, safe_call
from .resources import ResourceMonitor
from .service import MissionControl, get_mission_control

__all__ = ["MissionControl", "get_mission_control", "MissionControlAggregator",
           "ResourceMonitor", "EventStream", "safe_call", "Degraded"]
