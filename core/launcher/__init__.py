"""
core/launcher/ — FRIDAY V3 (M20) Production Launcher.

Brings FRIDAY up for production: OS detection, configuration loading, dependency
validation, an ordered + graceful startup sequence, structured rotating logging, and
health diagnostics. The launcher contains no cognitive logic — it initializes and observes
the cognitive machinery built in M1–M19. Side-effect-free to import.

Exports are lazy (PEP 562): the package imports no submodule eagerly, so
`python -m core.launcher.<module>` never re-executes an already-imported module
(the runpy RuntimeWarning every user saw when re-running the wizard).
"""

from __future__ import annotations

import importlib

_EXPORTS = {
    "Launcher": ".launcher",
    "main": ".launcher",
    "StartupSequence": ".startup",
    "StartupReport": ".startup",
    "STARTUP_STAGES": ".startup",
    "HealthMonitor": ".health",
    "PlatformAdapter": ".platform_adapter",
    "detect_os": ".platform_adapter",
    "configure_logging": ".logging_config",
    "FirstRunWizard": ".first_run",
    "FirstRunReport": ".first_run",
    "Diagnostics": ".diagnostics",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path, __name__), name)


def __dir__() -> list:
    return sorted(set(globals()) | set(_EXPORTS))
