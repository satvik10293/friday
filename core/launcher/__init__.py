"""
core/launcher/ — FRIDAY V3 (M20) Production Launcher.

Brings FRIDAY up for production: OS detection, configuration loading, dependency
validation, an ordered + graceful startup sequence, structured rotating logging, and
health diagnostics. The launcher contains no cognitive logic — it initializes and observes
the cognitive machinery built in M1–M19. Side-effect-free to import.
"""

from __future__ import annotations

from .diagnostics import Diagnostics
from .first_run import FirstRunReport, FirstRunWizard
from .health import HealthMonitor
from .launcher import Launcher, main
from .logging_config import configure_logging
from .platform_adapter import PlatformAdapter, detect_os
from .startup import STARTUP_STAGES, StartupReport, StartupSequence

__all__ = ["Launcher", "main", "StartupSequence", "StartupReport", "STARTUP_STAGES",
           "HealthMonitor", "PlatformAdapter", "detect_os", "configure_logging",
           "FirstRunWizard", "FirstRunReport", "Diagnostics"]
