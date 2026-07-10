"""
core/intelligence/device.py — M35 Device Wizard (the reader side).
The ONLY consumer of the wizard's `device_plan` in friday_config.json.
Model-loading code asks `preferred_device("<component>")` and gets a device
string ("cpu" | "cuda" | "mps"); cognition code never references devices.

Components: local_models (flan-t5 & friends), embeddings, stt, vision.
Missing plan, unreadable config, unknown component → "cpu". Always safe.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.intelligence.device")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "friday_config.json"

# Placements a torch-based loader can actually use today. Anything else
# (e.g. "openvino-gpu", written only if a future wizard version measures it)
# degrades to CPU here until a matching runtime integration exists.
_TORCH_DEVICES = {"cpu", "cuda", "mps"}

_cache_lock = threading.Lock()
_cached_plan: Optional[dict] = None
_cache_loaded = False


def _load_plan(config_path: Optional[Path] = None) -> Optional[dict]:
    global _cached_plan, _cache_loaded
    if config_path is not None:                      # explicit path: no cache
        return _read(config_path)
    with _cache_lock:
        if not _cache_loaded:
            _cached_plan = _read(_CONFIG_PATH)
            _cache_loaded = True
        return _cached_plan


def _read(path: Path) -> Optional[dict]:
    try:
        if not Path(path).exists():
            return None
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        plan = cfg.get("device_plan")
        return plan if isinstance(plan, dict) else None
    except (OSError, ValueError):
        log.debug("device plan unreadable at %s", path, exc_info=True)
        return None


def refresh() -> None:
    """Drop the cached plan (e.g. after the diagnostics screen re-runs the wizard)."""
    global _cache_loaded, _cached_plan
    with _cache_lock:
        _cache_loaded = False
        _cached_plan = None


def device_tier(config_path: Optional[Path] = None) -> str:
    plan = _load_plan(config_path)
    return (plan or {}).get("tier", "cpu_only")


def preferred_device(component: str, config_path: Optional[Path] = None) -> str:
    """The device string a loader should place `component` on. Always safe:
    no plan / unknown component / non-torch placement → "cpu"."""
    plan = _load_plan(config_path)
    if not plan:
        return "cpu"
    device = str(plan.get("placements", {}).get(component, "cpu"))
    if device not in _TORCH_DEVICES:
        log.debug("placement %r for %s has no torch runtime yet — using cpu",
                  device, component)
        return "cpu"
    return device
