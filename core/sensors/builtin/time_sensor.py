"""Built-in sensor: wall-clock / calendar time (local, deterministic)."""

from __future__ import annotations

import time
from datetime import datetime

from core.perception.models import ObservationType
from core.sensors.base import Sensor


class TimeSensor(Sensor):
    name = "time"
    version = "1.0.0"
    type = ObservationType.TIME
    interval_s = 60.0

    def observe(self):
        now = datetime.now()
        iso_year, iso_week, iso_weekday = now.isocalendar()
        payload = {
            "hour": now.hour,
            "minute": now.minute,
            "day": now.strftime("%A"),
            "date": now.strftime("%Y-%m-%d"),
            "week": iso_week,
            "month": now.strftime("%B"),
            "month_num": now.month,
            "year": now.year,
            "timezone": time.tzname[time.daylight] if time.daylight else time.tzname[0],
            "epoch": time.time(),
            "part_of_day": _part_of_day(now.hour),
        }
        return [self._obs(payload, confidence=1.0,
                          metadata={"subject": "time:clock", "impact": 0.2})]


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"
