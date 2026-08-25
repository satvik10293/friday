"""
Simulation AI with visual output (M64).

Pins the honest behaviour: she maps a free-form request to the right simulation
and parameters, actually renders an image to disk (a real file with bytes), and
degrades gracefully when she can't tell what to simulate. Renders go to a tmp
dir so the tests leave nothing behind.
"""

from __future__ import annotations

import os

from core.simulation.visual.ai import SimulationAI, _extract_params
from core.simulation.visual.sims import run_sim, list_sims, REGISTRY


def test_registry_is_non_trivial():
    names = {s["name"] for s in list_sims()}
    assert {"projectile", "pendulum", "orbit", "sir", "function_plot",
            "game_of_life"} <= names


def test_planner_classifies_and_extracts_params():
    ai = SimulationAI()
    st, p = ai.plan("simulate a projectile at 30 m/s and 40 degrees")
    assert st == "projectile"
    assert p["v0"] == 30.0 and p["angle"] == 40.0

    st, p = ai.plan("show me a logistic population growth with rate 0.4")
    assert st == "growth" and p["rate"] == 0.4

    st, p = ai.plan("plot y = sin(x) from -5 to 5")
    assert st == "function_plot"
    assert p["expr"].startswith("sin(x)") and p["xmin"] == -5.0 and p["xmax"] == 5.0


def test_projectile_physics_is_correct(tmp_path):
    r = run_sim("projectile", {"v0": 20, "angle": 45}, tmp_path)
    # range = v^2 sin(2θ)/g = 400*1/9.81 ≈ 40.8 m
    assert abs(r.data["range_m"] - 40.77) < 0.5
    assert r.images and os.path.getsize(r.images[0]) > 0


def test_simulate_renders_a_real_image(tmp_path):
    ai = SimulationAI(outdir=tmp_path)
    out = ai.simulate("simulate an SIR epidemic outbreak")
    assert out["ok"] and out["sim_type"] == "sir"
    assert out["images"] and os.path.getsize(out["images"][0]) > 100


def test_function_plot_rejects_unsafe_expressions(tmp_path):
    # the safe evaluator must refuse names outside the whitelist (no builtins)
    r = run_sim("function_plot", {"expr": "__import__('os').system('echo hi')"},
                tmp_path)
    assert not r.images                     # nothing rendered
    assert "error" in r.data


def test_unknown_request_is_handled_gracefully():
    ai = SimulationAI()
    out = ai.simulate("do the thing with the stuff")
    assert not out["ok"] and out["images"] == []
    assert "I can" in out["summary"]        # tells the owner what it CAN do


def test_route_regex_matches():
    from core.launcher.conversation import ConversationBridge as CB
    for phrase in ("simulate a projectile", "show me a simulation of an orbit",
                   "visualize game of life", "plot the function y = x^2",
                   "run a simulation of an epidemic"):
        assert CB._SIMULATE_RE.search(phrase), phrase


def test_bad_sim_type_never_raises(tmp_path):
    r = run_sim("does_not_exist", {}, tmp_path)
    assert r.images == [] and "error" in r.data
