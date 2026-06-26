"""
core/society/ — FRIDAY 4.0 (M11) Distributed Agent Society.

A living hierarchy of agents:

    Executive Brain → Passive Brain Coordinator → Leader Agents → Worker Agents

The Executive decides; the Passive Brain Coordinator manages (spawn / schedule /
allocate / monitor / merge / destroy) and is the *only* communication relay; eight
permanent Leaders own domains and decompose tasks; disposable Workers do the heavy
lifting in separate processes (via the M10 process runtime) and are destroyed when
done. Workers never spawn workers; agents never talk to each other directly.

Side-effect-free to import (the SQLite store opens only when constructed).
"""

from __future__ import annotations

from .coordinator import PassiveBrainCoordinator
from .leaders import LEADER_REGISTRY, LeaderAgent, LeaderRole, select_leader
from .models import (AgentKind, AgentRecord, AgentStatus, Message, SubTask, Task,
                     TaskResult, WorkerResult)
from .reputation import ReputationSystem
from .society import AgentSociety, get_society
from .workers import WORKER_TEMPLATES, WorkerTemplate

__all__ = [
    "AgentSociety", "get_society", "PassiveBrainCoordinator", "LeaderAgent",
    "LeaderRole", "LEADER_REGISTRY", "select_leader", "WorkerTemplate",
    "WORKER_TEMPLATES", "ReputationSystem", "AgentKind", "AgentStatus",
    "AgentRecord", "Task", "SubTask", "TaskResult", "WorkerResult", "Message",
]
