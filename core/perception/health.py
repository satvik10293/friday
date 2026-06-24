"""
core/perception/health.py — FRIDAY 4.0 (M6)
Health helpers for the perception layer: a small status vocabulary and an
aggregator that rolls perception-manager stats + sensor health into one dict for
Runtime.health().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class PerceptionHealth:
    status: str = HealthStatus.OK.value
    observations: int = 0
    promoted: int = 0
    archived: int = 0
    sensors_total: int = 0
    sensors_healthy: int = 0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def derive_status(sensors_total: int, sensors_healthy: int) -> HealthStatus:
    if sensors_total == 0:
        return HealthStatus.OK            # nothing registered yet is not a failure
    if sensors_healthy == 0:
        return HealthStatus.DOWN
    if sensors_healthy < sensors_total:
        return HealthStatus.DEGRADED
    return HealthStatus.OK


def aggregate(manager_stats: dict, sensor_health: dict) -> dict:
    sensors = sensor_health.get("sensors", {}) if sensor_health else {}
    total = len(sensors)
    healthy = sum(1 for h in sensors.values() if (h or {}).get("healthy", True))
    status = derive_status(total, healthy)
    return PerceptionHealth(
        status=status.value,
        observations=manager_stats.get("ingested", 0),
        promoted=manager_stats.get("promoted", 0),
        archived=manager_stats.get("archived", 0),
        sensors_total=total, sensors_healthy=healthy,
        detail={"manager": manager_stats, "sensors": sensor_health or {}},
    ).to_dict()
