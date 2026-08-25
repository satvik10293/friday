"""
core/simulation/visual/ai.py — the Simulation AI (M64)

The brain in front of the simulation library. It reads a free-form request,
decides WHICH simulation to run and with WHAT parameters, runs it, renders the
image, and explains the result — then can open the image so you actually see it.

Planning is layered so it always does something sensible:
  1. rule-based — match keywords in the request to a registered simulation and
     pull numbers out of the text (works offline, deterministic, tested);
  2. reasoner-assisted (optional) — if nothing matches and a reasoner is wired,
     ask it to map the request onto a registered sim type as JSON;
  3. graceful miss — if it still can't tell, it says what it CAN simulate.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from .sims import REGISTRY, run_sim, list_sims, _OUT_DIR

log = logging.getLogger("friday.simulation.ai")


# ── number extraction helpers ─────────────────────────────────────────────────
def _num_after(req: str, words) -> Optional[float]:
    for w in words:
        m = re.search(rf"{w}\s*(?:=|:|of|is|at|to|=)?\s*(-?\d+(?:\.\d+)?)", req)
        if m:
            return float(m.group(1))
    return None


def _num_before_unit(req: str, units) -> Optional[float]:
    for u in units:
        m = re.search(rf"(-?\d+(?:\.\d+)?)\s*{u}\b", req)
        if m:
            return float(m.group(1))
    return None


def _first_num(req: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", req)
    return float(m.group(0)) if m else None


def _set(params: dict, key: str, val) -> None:
    if val is not None:
        params[key] = val


# ── per-simulation parameter extraction ───────────────────────────────────────
def _extract_params(sim_type: str, request: str) -> dict:
    req = request.lower()
    p: dict = {}
    if sim_type == "projectile":
        ang = _num_before_unit(req, ["degrees", "degree", "deg", "°"]) \
            or _num_after(req, ["angle"])
        v0 = _num_before_unit(req, ["m/s", "meters per second", "mps"]) \
            or _num_after(req, ["speed", "velocity"])
        _set(p, "angle", ang)
        _set(p, "v0", v0)
    elif sim_type == "pendulum":
        _set(p, "length", _num_after(req, ["length"])
             or _num_before_unit(req, ["m", "meter", "meters"]))
        _set(p, "angle", _num_before_unit(req, ["degrees", "degree", "deg", "°"]))
    elif sim_type == "spring":
        _set(p, "k", _num_after(req, ["k", "stiffness", "constant"]))
        _set(p, "mass", _num_after(req, ["mass", "m"]))
    elif sim_type == "orbit":
        _set(p, "eccentricity", _num_after(req, ["eccentricity", "ecc"]))
    elif sim_type == "bouncing_ball":
        _set(p, "height", _num_after(req, ["height", "from"])
             or _num_before_unit(req, ["m", "meters"]))
        _set(p, "restitution", _num_after(req, ["restitution", "bounciness", "e"]))
    elif sim_type == "growth":
        if "exponential" in req:
            p["kind"] = "exponential"
        _set(p, "rate", _num_after(req, ["rate", "r"]))
        _set(p, "K", _num_after(req, ["carrying capacity", "capacity", "k"]))
        _set(p, "P0", _num_after(req, ["start", "initial", "from"]))
    elif sim_type == "compound_interest":
        _set(p, "rate", (_num_before_unit(req, ["%", "percent"]) or 0) / 100 or None)
        _set(p, "years", _num_after(req, ["years", "year"])
             or _num_before_unit(req, ["years", "year"]))
        _set(p, "principal", _num_after(req, ["principal", "invest", "deposit"]))
    elif sim_type == "sir":
        _set(p, "N", _num_after(req, ["population", "people", "n"]))
        _set(p, "beta", _num_after(req, ["beta", "transmission"]))
        _set(p, "gamma", _num_after(req, ["gamma", "recovery"]))
    elif sim_type == "random_walk":
        _set(p, "steps", _num_after(req, ["steps", "step"]) or _first_num(req))
    elif sim_type == "game_of_life":
        _set(p, "size", _num_after(req, ["size", "grid"]))
        _set(p, "steps", _num_after(req, ["generations", "steps", "gens"]))
    elif sim_type == "function_plot":
        p.update(_extract_function(request))
    # normalise ints where the sim expects them
    for k in ("steps", "size", "years"):
        if k in p and p[k] is not None:
            p[k] = int(p[k])
    return p


def _extract_function(request: str) -> dict:
    """Pull an expression (and optional range) out of 'plot y = sin(x) from -5 to 5'."""
    p: dict = {}
    rng = re.search(r"from\s*(-?\d+(?:\.\d+)?)\s*to\s*(-?\d+(?:\.\d+)?)", request, re.I)
    if rng:
        p["xmin"], p["xmax"] = float(rng.group(1)), float(rng.group(2))
    body = re.sub(r"from\s*-?\d.*$", "", request, flags=re.I)
    m = re.search(r"y\s*=\s*(.+)$", body, re.I) \
        or re.search(r"(?:plot|graph)\s+(?:of\s+|the\s+|the graph of\s+)?(.+)$", body, re.I)
    if m:
        expr = m.group(1).strip().strip(".")
        expr = expr.replace("^", "**")
        # drop a trailing 'function'/'curve' word
        expr = re.sub(r"\b(function|curve|graph)\b", "", expr).strip()
        if expr:
            p["expr"] = expr
    return p


class SimulationAI:
    """Reads a request, runs the right simulation, renders it, explains it."""

    def __init__(self, reasoner=None, outdir: Optional[Path] = None) -> None:
        self.reasoner = reasoner
        self.outdir = Path(outdir) if outdir else _OUT_DIR

    # ── planning ────────────────────────────────────────────────────────────────
    def plan(self, request: str) -> tuple:
        """Return (sim_type, params) or (None, {}) if she can't tell."""
        req = (request or "").lower()
        for spec in REGISTRY.values():
            if any(kw in req for kw in spec.keywords):
                return spec.name, _extract_params(spec.name, request)
        # a bare 'y = ...' with no keyword still means a function plot
        if re.search(r"y\s*=", req):
            return "function_plot", _extract_params("function_plot", request)
        guess = self._ask_reasoner(request)
        if guess:
            return guess
        return None, {}

    def _ask_reasoner(self, request: str) -> Optional[tuple]:
        """Optional: let a wired reasoner map an unusual request onto a
        registered sim type. Defensive — any failure just returns None."""
        if self.reasoner is None or not getattr(self.reasoner, "available", lambda: False)():
            return None
        try:
            names = ", ".join(REGISTRY.keys())
            prompt = (
                "Map this simulation request to one of these types and its "
                f"parameters. Types: {names}.\n"
                f'Request: "{request}"\n'
                'Reply with ONLY compact JSON: {"sim_type": "<one of the types>", '
                '"params": {}}. If none fit, use "function_plot".')
            r = self.reasoner.reason(prompt)
            text = (getattr(r, "answer", "") or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                return None
            data = json.loads(m.group(0))
            st = data.get("sim_type")
            if st in REGISTRY:
                params = data.get("params") if isinstance(data.get("params"), dict) else {}
                return st, params
        except Exception:  # noqa: BLE001 — the reasoner path is best-effort
            log.debug("reasoner sim mapping failed", exc_info=True)
        return None

    # ── the public call ───────────────────────────────────────────────────────────
    def simulate(self, request: str) -> dict:
        """Plan → run → render → explain. Returns a dict with the image paths.
        Never raises."""
        try:
            sim_type, params = self.plan(request)
            if sim_type is None:
                opts = ", ".join(s["name"].replace("_", " ") for s in list_sims())
                return {"ok": False, "images": [],
                        "summary": ("I couldn't tell what to simulate. I can show "
                                    f"you: {opts}. Try 'simulate a projectile at "
                                    "30 m/s and 45 degrees'."),
                        "sim_type": None, "params": {}}
            result = run_sim(sim_type, params, self.outdir)
            return {"ok": bool(result.images), "images": result.images,
                    "summary": result.description, "title": result.title,
                    "sim_type": sim_type, "params": params, "data": result.data}
        except Exception:  # noqa: BLE001 — simulation must never break a turn
            log.debug("simulate failed", exc_info=True)
            return {"ok": False, "images": [],
                    "summary": "I hit a snag setting up that simulation.",
                    "sim_type": None, "params": {}}


# ── display: actually show the rendered image(s) ──────────────────────────────
def open_images(paths) -> int:
    """Open rendered images in the OS default viewer. Returns how many opened.
    Never raises (headless/test environments just get 0)."""
    opened = 0
    for pth in paths or []:
        try:
            import os
            import sys
            if sys.platform.startswith("win"):
                os.startfile(pth)          # noqa: S606 — local file, owner-initiated
            else:
                import webbrowser
                webbrowser.open(Path(pth).resolve().as_uri())
            opened += 1
        except Exception:  # noqa: BLE001
            log.debug("could not open image %s", pth, exc_info=True)
    return opened


def simulate(request: str, *, reasoner=None, show: bool = False) -> dict:
    """Convenience: build a SimulationAI, run the request, optionally show it."""
    out = SimulationAI(reasoner=reasoner).simulate(request)
    if show and out.get("images"):
        out["opened"] = open_images(out["images"])
    return out
