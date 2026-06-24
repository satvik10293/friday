"""
core/sensors — FRIDAY 4.0 (M6) Sensor framework.

Sensors are the only producers of Observations. The registry holds them, the
manager polls them and feeds perception, heartbeats track liveness. All sensors
are local-only (no network/cloud). Import is side-effect free.

    from core.sensors import SensorManager, SensorRegistry
    from core.sensors.builtin import register_builtin_sensors
    mgr = SensorManager(perception_manager=pm)
    register_builtin_sensors(mgr)
    mgr.poll_once()
"""

from .base import Sensor
from .registry import SensorRegistry
from .heartbeat import Heartbeat, HeartbeatMonitor
from .manager import SensorManager

__all__ = [
    "Sensor", "SensorRegistry", "Heartbeat", "HeartbeatMonitor", "SensorManager",
]
