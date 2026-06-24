"""Built-in sensor: watch directories for new / modified / deleted files (local,
stdlib-only). Diffs the top-level contents of each watched directory across polls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from core.perception.models import ObservationType
from core.sensors.base import Sensor


class FilesystemSensor(Sensor):
    name = "filesystem"
    version = "1.0.0"
    type = ObservationType.FILESYSTEM
    interval_s = 15.0

    def __init__(self, watch_dirs: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self._dirs: list[Path] = [Path(d) for d in (watch_dirs or [])]
        self._state: dict[str, float] = {}      # path -> mtime

    def add_watch(self, directory: str) -> None:
        self._dirs.append(Path(directory))

    @property
    def watched(self) -> list[str]:
        return [str(d) for d in self._dirs]

    def observe(self):
        current: dict[str, float] = {}
        for d in self._dirs:
            if not d.exists() or not d.is_dir():
                continue
            for entry in d.iterdir():
                if not entry.is_file():
                    continue
                try:
                    current[str(entry)] = entry.stat().st_mtime
                except OSError:
                    continue

        prev = self._state
        new = [p for p in current if p not in prev]
        modified = [p for p in current if p in prev and current[p] != prev[p]]
        deleted = [p for p in prev if p not in current]
        self._state = current

        changed = bool(new or modified or deleted)
        payload = {
            "watched": self.watched,
            "file_count": len(current),
            "new": new[:50],
            "modified": modified[:50],
            "deleted": deleted[:50],
        }
        return [self._obs(payload, confidence=1.0,
                          metadata={"subject": "filesystem:watch",
                                    "impact": 0.7 if changed else 0.2})]
