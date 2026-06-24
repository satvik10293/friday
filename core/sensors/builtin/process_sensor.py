"""Built-in sensor: running processes, active process, and process changes (local).

psutil is optional; without it the sensor reports nothing (returns []). Emits
per-process APPLICATION observations for notable apps so fusion can corroborate
them with screen observations.
"""

from __future__ import annotations

from core.perception.models import ObservationSource, ObservationType, new_observation
from core.sensors.base import Sensor

# apps worth surfacing individually (enables app-detection fusion)
_NOTABLE = {"chrome", "firefox", "msedge", "code", "pycharm64", "pycharm",
            "explorer", "spotify", "discord", "slack", "notepad", "python"}


class ProcessSensor(Sensor):
    name = "process"
    version = "1.0.0"
    type = ObservationType.APPLICATION
    interval_s = 10.0

    def __init__(self) -> None:
        super().__init__()
        self._prev: set[str] = set()

    def observe(self):
        try:
            import psutil
        except Exception:
            return []

        names: set[str] = set()
        active = None
        max_mem = -1
        for p in psutil.process_iter(["name", "memory_info"]):
            n = (p.info.get("name") or "").strip()
            if not n:
                continue
            names.add(n)
            try:
                rss = p.info["memory_info"].rss if p.info.get("memory_info") else 0
            except Exception:
                rss = 0
            if rss > max_mem:
                max_mem, active = rss, n

        started = sorted(names - self._prev)
        ended = sorted(self._prev - names)
        changed = bool(started or ended)
        self._prev = names

        out = [self._obs(
            {"running_count": len(names), "active": active,
             "started": started[:20], "ended": ended[:20]},
            confidence=0.85, type=ObservationType.APPLICATION,
            metadata={"subject": "process:list", "impact": 0.6 if changed else 0.3})]

        # individual observations for notable apps → fusion fodder
        for n in names:
            stem = n.lower().rsplit(".", 1)[0]
            if stem in _NOTABLE:
                out.append(new_observation(
                    ObservationType.APPLICATION,
                    ObservationSource(name=self.name, kind="sensor", version=self.version),
                    payload={"process": n}, confidence=0.8,
                    metadata={"subject": f"process:{stem}", "impact": 0.4}))
        return out
