"""
core/simulation/visual/ — FRIDAY's Simulation AI with visual output (M64).

She turns a free-form request ("simulate a projectile at 30 m/s and 40 degrees",
"show me a logistic growth curve", "simulate Conway's game of life") into an
actual simulation she runs on-device and renders to an image she can show you.

  · sims.py — an extensible library of parameterized simulations + a registry.
              Each one runs the model and renders a PNG (or an animated GIF).
  · ai.py   — the Simulation AI: it reads the request, picks the simulation and
              its parameters (rule-based first, with an optional reasoner to map
              anything unusual), runs it, renders it, and explains the result.

Rendering uses a headless matplotlib backend, so it works with no display.
"""

from .ai import SimulationAI, simulate
from .sims import REGISTRY, SimResult, run_sim, list_sims

__all__ = [
    "SimulationAI", "simulate",
    "REGISTRY", "SimResult", "run_sim", "list_sims",
]
