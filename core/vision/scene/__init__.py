"""
core/vision/scene/ — FRIDAY 6.1 (M14) Scene Graph.

A live per-camera model of persistent objects + their spatial relationships, with
camera-relative and (hooked) world-relative positions and room-mapping hooks. Geometry
and state only — no reasoning, no World Model writes.
"""

from __future__ import annotations

from .scene_graph import SceneGraph, SceneObject

__all__ = ["SceneGraph", "SceneObject"]
