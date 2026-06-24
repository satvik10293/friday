"""
core/sensors/builtin — FRIDAY 4.0 (M6) reference sensors.

Four local, dependency-light sensors: time (stdlib), system + process (psutil
optional, degrade gracefully), filesystem (stdlib). Import is side-effect free.

    from core.sensors import SensorManager
    from core.sensors.builtin import register_builtin_sensors
    mgr = SensorManager(perception_manager=pm)
    register_builtin_sensors(mgr, watch_dirs=["C:/VAULT/satvik"])
"""

from typing import Iterable, Optional

from .time_sensor import TimeSensor
from .system_sensor import SystemSensor
from .process_sensor import ProcessSensor
from .filesystem_sensor import FilesystemSensor

ALL_BUILTIN = (TimeSensor, SystemSensor, ProcessSensor, FilesystemSensor)

__all__ = [
    "TimeSensor", "SystemSensor", "ProcessSensor", "FilesystemSensor",
    "ALL_BUILTIN", "register_builtin_sensors",
]


def register_builtin_sensors(manager, watch_dirs: Optional[Iterable[str]] = None) -> list:
    """Register the four built-in sensors on a SensorManager. Returns the sensors."""
    sensors = [TimeSensor(), SystemSensor(), ProcessSensor(),
               FilesystemSensor(watch_dirs=watch_dirs)]
    for s in sensors:
        manager.register(s)
    return sensors
