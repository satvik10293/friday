"""Built-in sensor: host system metrics — cpu/ram/disk/battery/uptime (local).

psutil is optional; if it's unavailable the sensor degrades to a low-confidence
"unavailable" observation rather than failing.
"""

from __future__ import annotations

import os
import time

from core.perception.models import ObservationType
from core.sensors.base import Sensor


class SystemSensor(Sensor):
    name = "system"
    version = "1.0.0"
    type = ObservationType.SYSTEM
    interval_s = 5.0

    def observe(self):
        try:
            import psutil
        except Exception as e:
            return [self._obs({"available": False, "reason": str(e)}, confidence=0.3,
                              metadata={"subject": "system:host", "impact": 0.2})]

        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.0)
        disk_pct = _disk_pct(psutil)
        battery_pct, on_battery = _battery(psutil)
        try:
            uptime = round(time.time() - psutil.boot_time(), 1)
        except Exception:
            uptime = None

        payload = {
            "available": True,
            "cpu_pct": cpu,
            "ram_pct": vm.percent,
            "ram_used_gb": round(vm.used / 1e9, 2),
            "disk_pct": disk_pct,
            "battery_pct": battery_pct,
            "on_battery": on_battery,
            "uptime_s": uptime,
        }
        pressure = max(cpu, vm.percent, disk_pct or 0)
        impact = 0.85 if pressure >= 85 else 0.5 if pressure >= 60 else 0.3
        return [self._obs(payload, confidence=0.95,
                          metadata={"subject": "system:host", "impact": impact})]


def _disk_pct(psutil):
    try:
        drive = os.path.splitdrive(os.getcwd())[0] or os.sep
        path = drive + os.sep if not drive.endswith(os.sep) else drive
        return psutil.disk_usage(path).percent
    except Exception:
        try:
            return psutil.disk_usage(os.sep).percent
        except Exception:
            return None


def _battery(psutil):
    try:
        b = psutil.sensors_battery()
    except Exception:
        b = None
    if b is None:
        return None, None
    return round(b.percent, 1), (not b.power_plugged)
