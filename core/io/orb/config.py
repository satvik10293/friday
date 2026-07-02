"""
core/io/orb/config.py — FRIDAY V3 (M20 revision: Orb UI)

Reads the `ui` block from friday_config.json (non-secret settings) into a typed, tolerant
config object. All keys are optional and fall back to the directive's defaults, so an old
config without a `ui` block still works (backward compatible).

    ui:
      primary_interface:      orb
      voice_mode_default:     true
      speech_panel_enabled:   true
      speech_panel_auto_hide: true
      orb_always_on_top:      true
      remember_position:      true
      remember_size:          true
      animation_quality:      high
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.orb.config")

_ANIMATION_QUALITIES = ("low", "medium", "high")


@dataclass
class OrbConfig:
    primary_interface: str = "orb"          # orb | dashboard
    voice_mode_default: bool = True
    speech_panel_enabled: bool = True
    speech_panel_auto_hide: bool = True
    orb_always_on_top: bool = True
    remember_position: bool = True
    remember_size: bool = True
    animation_quality: str = "high"

    def sanitized(self) -> "OrbConfig":
        if self.animation_quality not in _ANIMATION_QUALITIES:
            self.animation_quality = "high"
        if self.primary_interface not in ("orb", "dashboard"):
            self.primary_interface = "orb"
        return self

    def to_dict(self) -> dict:
        return {
            "primary_interface": self.primary_interface,
            "voice_mode_default": self.voice_mode_default,
            "speech_panel_enabled": self.speech_panel_enabled,
            "speech_panel_auto_hide": self.speech_panel_auto_hide,
            "orb_always_on_top": self.orb_always_on_top,
            "remember_position": self.remember_position,
            "remember_size": self.remember_size,
            "animation_quality": self.animation_quality,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "OrbConfig":
        data = (data or {}).get("ui", data or {}) if data and "ui" in data else (data or {})
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}  # type: ignore[attr-defined]
        return cls(**known).sanitized()

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "OrbConfig":
        """Load the `ui` block from friday_config.json (or defaults). Never raises."""
        if config_path is None:
            config_path = Path(__file__).resolve().parents[3] / "friday_config.json"
        try:
            if config_path.exists():
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                return cls.from_dict({"ui": cfg.get("ui", {})})
        except (OSError, ValueError) as e:
            log.warning("[Orb] could not read ui config (%s); using defaults", e)
        return cls()
