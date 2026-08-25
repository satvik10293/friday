"""
core/simulation/visual/sims.py — the simulation library + renderer (M64)

Every simulation is a small, self-contained function that runs a model and
renders it to an image on disk, returning a SimResult (the image paths, a
plain-language description, and the key numbers). New simulation types plug in
by adding a SimSpec to REGISTRY — nothing else changes, which is how "any type
the user wants" stays true over time.

Rendering is headless (Agg backend), bounded, and never leaves a figure open.
"""

from __future__ import annotations

import ast
import logging
import math
import operator
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

import matplotlib
matplotlib.use("Agg")           # headless: render to files, never a window
import matplotlib.pyplot as plt  # noqa: E402

log = logging.getLogger("friday.simulation.visual")

_ROOT = Path(__file__).resolve().parents[3]
_OUT_DIR = _ROOT / "data" / "simulations"


@dataclass
class SimResult:
    sim_type: str
    title: str
    description: str
    images: list = field(default_factory=list)   # file paths (str)
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"sim_type": self.sim_type, "title": self.title,
                "description": self.description, "images": list(self.images),
                "data": dict(self.data)}


def _outfile(outdir: Path, sim_type: str, ext: str = "png") -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    # time_ns + a short random tail keeps names unique even for two runs of the
    # same simulation within the same second.
    import uuid
    return outdir / f"{sim_type}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)


# ── a safe evaluator for owner-typed math (no builtins, whitelisted names) ────
_ALLOWED_FUNCS = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "exp": np.exp,
    "log": np.log, "log10": np.log10, "sqrt": np.sqrt, "abs": np.abs,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh, "arctan": np.arctan,
    "floor": np.floor, "ceil": np.ceil, "sign": np.sign,
}
_ALLOWED_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(expr: str, x):
    """Evaluate a math expression of x over a numpy array, with no access to
    builtins — only whitelisted functions/constants. Raises ValueError on
    anything outside the whitelist."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == "x":
                return x
            if node.id in _ALLOWED_CONSTS:
                return _ALLOWED_CONSTS[node.id]
            raise ValueError(f"unknown name: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = _ALLOWED_FUNCS.get(node.func.id)
            if fn is None:
                raise ValueError(f"unknown function: {node.func.id}")
            return fn(*[ev(a) for a in node.args])
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr, mode="eval"))


# ── physics ───────────────────────────────────────────────────────────────────
def sim_projectile(p: dict, outdir: Path) -> SimResult:
    v0 = float(p.get("v0", 20.0)); ang = float(p.get("angle", 45.0))
    g = float(p.get("g", 9.81))
    th = math.radians(ang)
    tf = max(1e-3, 2 * v0 * math.sin(th) / g)
    t = np.linspace(0, tf, 200)
    x = v0 * math.cos(th) * t
    y = v0 * math.sin(th) * t - 0.5 * g * t ** 2
    rng = v0 ** 2 * math.sin(2 * th) / g
    hmax = (v0 * math.sin(th)) ** 2 / (2 * g)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, y, "b-"); ax.fill_between(x, 0, y, alpha=0.1)
    ax.plot([rng], [0], "ro")
    _style(ax, f"Projectile — {v0} m/s at {ang}°", "distance (m)", "height (m)")
    path = _outfile(outdir, "projectile"); fig.savefig(path, dpi=110); plt.close(fig)
    desc = (f"A projectile launched at {v0} m/s and {ang}° travels {rng:.1f} m, "
            f"peaks at {hmax:.1f} m, and lands after {tf:.1f} s.")
    return SimResult("projectile", f"Projectile at {v0} m/s, {ang}°", desc,
                     [str(path)], {"range_m": rng, "max_height_m": hmax,
                                   "flight_time_s": tf})


def sim_pendulum(p: dict, outdir: Path) -> SimResult:
    L = float(p.get("length", 1.0)); th0 = math.radians(float(p.get("angle", 30.0)))
    g = float(p.get("g", 9.81)); T = float(p.get("time", 10.0))
    dt = 0.005; steps = int(T / dt)
    th, w = th0, 0.0
    ts, ths = [], []
    for i in range(steps):
        w += -(g / L) * math.sin(th) * dt
        th += w * dt
        ts.append(i * dt); ths.append(math.degrees(th))
    period = 2 * math.pi * math.sqrt(L / g)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ts, ths, "g-")
    _style(ax, f"Pendulum — L={L} m, θ₀={math.degrees(th0):.0f}°",
           "time (s)", "angle (°)")
    path = _outfile(outdir, "pendulum"); fig.savefig(path, dpi=110); plt.close(fig)
    desc = (f"A {L} m pendulum released at {math.degrees(th0):.0f}° swings with a "
            f"period of about {period:.2f} s.")
    return SimResult("pendulum", "Pendulum", desc, [str(path)],
                     {"period_s": period})


def sim_spring(p: dict, outdir: Path) -> SimResult:
    k = float(p.get("k", 1.0)); m = float(p.get("mass", 1.0))
    x0 = float(p.get("x0", 1.0)); T = float(p.get("time", 20.0))
    w = math.sqrt(k / m)
    t = np.linspace(0, T, 400)
    x = x0 * np.cos(w * t)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(t, x, "m-")
    _style(ax, f"Simple harmonic motion — k={k}, m={m}", "time (s)", "position")
    path = _outfile(outdir, "spring"); fig.savefig(path, dpi=110); plt.close(fig)
    desc = (f"A mass {m} on a spring (k={k}) oscillates at ω={w:.2f} rad/s, "
            f"period {2 * math.pi / w:.2f} s.")
    return SimResult("spring", "Spring / SHM", desc, [str(path)],
                     {"omega": w, "period_s": 2 * math.pi / w})


def sim_orbit(p: dict, outdir: Path) -> SimResult:
    # two-body: a light body orbiting a heavy central mass (velocity Verlet)
    GM = float(p.get("gm", 1.0))
    r0 = float(p.get("radius", 1.0)); ecc = float(p.get("eccentricity", 0.3))
    pos = np.array([r0, 0.0]); vy = math.sqrt(GM / r0) * (1 - ecc)
    vel = np.array([0.0, vy]); dt = 0.01; steps = 3000
    xs, ys = [], []
    for _ in range(steps):
        r = np.linalg.norm(pos)
        acc = -GM * pos / r ** 3
        vel = vel + acc * dt
        pos = pos + vel * dt
        xs.append(pos[0]); ys.append(pos[1])
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.plot(xs, ys, "b-", lw=0.8); ax.plot([0], [0], "yo", ms=12)
    ax.set_aspect("equal"); _style(ax, "Orbit (two-body)", "x", "y")
    path = _outfile(outdir, "orbit"); fig.savefig(path, dpi=110); plt.close(fig)
    return SimResult("orbit", "Orbital motion",
                     "A body orbiting a central mass, traced over one path.",
                     [str(path)], {"steps": steps})


def sim_bouncing_ball(p: dict, outdir: Path) -> SimResult:
    h0 = float(p.get("height", 10.0)); e = float(p.get("restitution", 0.8))
    g = float(p.get("g", 9.81)); T = float(p.get("time", 12.0))
    dt = 0.002; t = 0.0; y = h0; v = 0.0
    ts, ys = [], []
    while t < T:
        v -= g * dt; y += v * dt
        if y <= 0:
            y = 0.0; v = -v * e
            if abs(v) < 0.1:
                break
        ts.append(t); ys.append(y); t += dt
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ts, ys, "r-")
    _style(ax, f"Bouncing ball — h₀={h0} m, e={e}", "time (s)", "height (m)")
    path = _outfile(outdir, "bounce"); fig.savefig(path, dpi=110); plt.close(fig)
    return SimResult("bouncing_ball", "Bouncing ball",
                     f"A ball dropped from {h0} m losing {(1 - e) * 100:.0f}% of "
                     f"its speed each bounce.", [str(path)], {})


# ── growth / systems ────────────────────────────────────────────────────────────
def sim_growth(p: dict, outdir: Path) -> SimResult:
    P0 = float(p.get("P0", 10.0)); r = float(p.get("rate", 0.5))
    K = float(p.get("K", 1000.0)); T = float(p.get("time", 50.0))
    logistic = p.get("kind", "logistic") != "exponential"
    t = np.linspace(0, T, 300)
    if logistic:
        P = K / (1 + (K - P0) / P0 * np.exp(-r * t))
        title = f"Logistic growth — r={r}, K={K:.0f}"
    else:
        P = P0 * np.exp(r * t)
        title = f"Exponential growth — r={r}"
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(t, P, "b-")
    _style(ax, title, "time", "population")
    path = _outfile(outdir, "growth"); fig.savefig(path, dpi=110); plt.close(fig)
    kind = "logistic" if logistic else "exponential"
    return SimResult("growth", title,
                     f"{kind.title()} growth from {P0:.0f} at rate {r}.",
                     [str(path)], {"final": float(P[-1])})


def sim_compound_interest(p: dict, outdir: Path) -> SimResult:
    P = float(p.get("principal", 1000.0)); rate = float(p.get("rate", 0.05))
    years = float(p.get("years", 30.0)); n = int(p.get("n", 12))
    t = np.linspace(0, years, int(years) * 12 + 1)
    bal = P * (1 + rate / n) ** (n * t)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(t, bal, "g-")
    _style(ax, f"Compound interest — {rate * 100:.1f}%/yr", "years", "balance")
    path = _outfile(outdir, "interest"); fig.savefig(path, dpi=110); plt.close(fig)
    final = P * (1 + rate / n) ** (n * years)
    return SimResult("compound_interest", "Compound interest",
                     f"{P:.0f} at {rate * 100:.1f}% compounded {n}×/yr grows to "
                     f"{final:,.0f} in {years:.0f} years.", [str(path)],
                     {"final": final})


def sim_sir(p: dict, outdir: Path) -> SimResult:
    N = float(p.get("N", 1000.0)); I0 = float(p.get("I0", 1.0))
    beta = float(p.get("beta", 0.3)); gamma = float(p.get("gamma", 0.1))
    days = int(p.get("days", 160))
    S, I, R = N - I0, I0, 0.0; dt = 0.5
    Ss, Is, Rs, ts = [], [], [], []
    t = 0.0
    while t < days:
        dS = -beta * S * I / N
        dI = beta * S * I / N - gamma * I
        dR = gamma * I
        S += dS * dt; I += dI * dt; R += dR * dt
        Ss.append(S); Is.append(I); Rs.append(R); ts.append(t); t += dt
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ts, Ss, "b-", label="susceptible")
    ax.plot(ts, Is, "r-", label="infected")
    ax.plot(ts, Rs, "g-", label="recovered")
    ax.legend(); _style(ax, f"SIR epidemic — R₀={beta / gamma:.1f}", "days", "people")
    path = _outfile(outdir, "sir"); fig.savefig(path, dpi=110); plt.close(fig)
    return SimResult("sir", "SIR epidemic",
                     f"An outbreak with R₀={beta / gamma:.1f}; peak infected "
                     f"{max(Is):.0f}.", [str(path)], {"peak_infected": max(Is)})


def sim_predator_prey(p: dict, outdir: Path) -> SimResult:
    a = float(p.get("a", 0.1)); b = float(p.get("b", 0.02))
    c = float(p.get("c", 0.3)); d = float(p.get("d", 0.01))
    prey = float(p.get("prey", 40.0)); pred = float(p.get("pred", 9.0))
    T = float(p.get("time", 200.0)); dt = 0.05
    xs, ys, ts = [], [], []; t = 0.0
    while t < T:
        dx = a * prey - b * prey * pred
        dy = -c * pred + d * prey * pred
        prey += dx * dt; pred += dy * dt
        xs.append(prey); ys.append(pred); ts.append(t); t += dt
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ts, xs, "g-", label="prey")
    ax.plot(ts, ys, "r-", label="predators")
    ax.legend(); _style(ax, "Lotka–Volterra predator–prey", "time", "population")
    path = _outfile(outdir, "predprey"); fig.savefig(path, dpi=110); plt.close(fig)
    return SimResult("predator_prey", "Predator–prey",
                     "Classic predator–prey cycles (Lotka–Volterra).",
                     [str(path)], {})


# ── data / abstract ─────────────────────────────────────────────────────────────
def sim_random_walk(p: dict, outdir: Path) -> SimResult:
    steps = int(p.get("steps", 2000)); seed = p.get("seed")
    rng = np.random.default_rng(seed)
    d = rng.choice([-1, 1], size=(steps, 2))
    path_xy = np.cumsum(d, axis=0)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(path_xy[:, 0], path_xy[:, 1], lw=0.6)
    ax.plot([0], [0], "go"); ax.plot([path_xy[-1, 0]], [path_xy[-1, 1]], "ro")
    ax.set_aspect("equal"); _style(ax, f"Random walk — {steps} steps", "x", "y")
    path = _outfile(outdir, "walk"); fig.savefig(path, dpi=110); plt.close(fig)
    dist = float(np.linalg.norm(path_xy[-1]))
    return SimResult("random_walk", "Random walk",
                     f"A {steps}-step 2-D random walk; final distance "
                     f"{dist:.1f} from the origin.", [str(path)], {"distance": dist})


def sim_function_plot(p: dict, outdir: Path) -> SimResult:
    expr = str(p.get("expr", "sin(x)"))
    xmin = float(p.get("xmin", -10.0)); xmax = float(p.get("xmax", 10.0))
    x = np.linspace(xmin, xmax, 800)
    try:
        y = _safe_eval(expr, x)
        y = np.broadcast_to(np.asarray(y, float), x.shape)
    except (ValueError, SyntaxError, TypeError) as e:
        return SimResult("function_plot", "Function plot",
                         f"I couldn't plot '{expr}' — {e}.", [], {"error": str(e)})
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, y, "b-"); ax.axhline(0, color="k", lw=0.5); ax.axvline(0, color="k", lw=0.5)
    _style(ax, f"y = {expr}", "x", "y")
    path = _outfile(outdir, "function"); fig.savefig(path, dpi=110); plt.close(fig)
    return SimResult("function_plot", f"y = {expr}",
                     f"The graph of y = {expr} over [{xmin:.0f}, {xmax:.0f}].",
                     [str(path)], {})


def sim_game_of_life(p: dict, outdir: Path) -> SimResult:
    size = int(p.get("size", 40)); gens = int(p.get("steps", 60))
    seed = p.get("seed")
    rng = np.random.default_rng(seed)
    grid = (rng.random((size, size)) < 0.25).astype(np.uint8)

    def step(g):
        nb = sum(np.roll(np.roll(g, dy, 0), dx, 1)
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                 if (dy, dx) != (0, 0))
        return ((nb == 3) | ((g == 1) & (nb == 2))).astype(np.uint8)

    try:
        from matplotlib import animation
        fig, ax = plt.subplots(figsize=(5, 5)); ax.axis("off")
        im = ax.imshow(grid, cmap="binary", interpolation="nearest")
        state = {"g": grid}

        def update(_):
            state["g"] = step(state["g"]); im.set_data(state["g"]); return [im]

        anim = animation.FuncAnimation(fig, update, frames=gens, blit=True)
        path = _outfile(outdir, "life", ext="gif")
        anim.save(path, writer=animation.PillowWriter(fps=10))
        plt.close(fig)
        return SimResult("game_of_life", "Conway's Game of Life",
                         f"Conway's Game of Life on a {size}×{size} grid over "
                         f"{gens} generations.", [str(path)], {})
    except Exception as e:  # noqa: BLE001 — fall back to a still of the final state
        log.debug("life animation failed, rendering a still", exc_info=True)
        g = grid
        for _ in range(gens):
            g = step(g)
        fig, ax = plt.subplots(figsize=(5, 5)); ax.axis("off")
        ax.imshow(g, cmap="binary")
        path = _outfile(outdir, "life"); fig.savefig(path, dpi=110); plt.close(fig)
        return SimResult("game_of_life", "Conway's Game of Life",
                         f"Final state after {gens} generations.", [str(path)],
                         {"note": f"animation unavailable: {e}"})


# ── the registry: name → (runner, keywords) ───────────────────────────────────
@dataclass
class SimSpec:
    name: str
    runner: Callable[[dict, Path], SimResult]
    keywords: tuple
    help: str = ""


REGISTRY: dict = {}


def _register(spec: SimSpec) -> None:
    REGISTRY[spec.name] = spec


for _spec in [
    SimSpec("projectile", sim_projectile,
            ("projectile", "cannon", "throw", "launch", "trajectory", "ballistic"),
            "a projectile's flight (v0, angle)"),
    SimSpec("pendulum", sim_pendulum, ("pendulum", "swing"),
            "a swinging pendulum (length, angle)"),
    SimSpec("spring", sim_spring,
            ("spring", "harmonic", "shm", "oscillat", "hooke"),
            "simple harmonic motion (k, mass)"),
    SimSpec("orbit", sim_orbit,
            ("orbit", "planet", "gravity", "satellite", "two-body", "two body"),
            "orbital motion around a mass"),
    SimSpec("bouncing_ball", sim_bouncing_ball,
            ("bounce", "bouncing", "ball drop", "dropping"),
            "a bouncing ball (height, restitution)"),
    SimSpec("growth", sim_growth,
            ("growth", "population", "logistic", "exponential", "spread"),
            "population growth (logistic/exponential)"),
    SimSpec("compound_interest", sim_compound_interest,
            ("interest", "compound", "investment", "savings", "money grow"),
            "compound interest (principal, rate, years)"),
    SimSpec("sir", sim_sir,
            ("epidemic", "sir", "infection", "outbreak", "disease", "virus", "pandemic"),
            "an SIR epidemic (beta, gamma)"),
    SimSpec("predator_prey", sim_predator_prey,
            ("predator", "prey", "lotka", "volterra", "wolves", "rabbits"),
            "predator-prey population cycles"),
    SimSpec("random_walk", sim_random_walk,
            ("random walk", "brownian", "drunkard"),
            "a 2-D random walk (steps)"),
    SimSpec("function_plot", sim_function_plot,
            ("plot", "graph", "function", "y =", "y=", "curve of"),
            "the graph of y = f(x)"),
    SimSpec("game_of_life", sim_game_of_life,
            ("game of life", "conway", "cellular", "automaton", "automata"),
            "Conway's Game of Life (animated)"),
]:
    _register(_spec)


def list_sims() -> list:
    return [{"name": s.name, "help": s.help} for s in REGISTRY.values()]


def run_sim(sim_type: str, params: Optional[dict] = None,
            outdir: Optional[Path] = None) -> SimResult:
    """Run one simulation by name. Never raises — an unknown type or a render
    failure comes back as a SimResult with an error note (no images)."""
    spec = REGISTRY.get(sim_type)
    outdir = Path(outdir) if outdir else _OUT_DIR
    if spec is None:
        return SimResult(sim_type, sim_type, f"I don't have a '{sim_type}' "
                         "simulation.", [], {"error": "unknown sim_type"})
    try:
        return spec.runner(dict(params or {}), outdir)
    except Exception as e:  # noqa: BLE001 — a bad render must not crash the turn
        log.debug("simulation %s failed", sim_type, exc_info=True)
        return SimResult(sim_type, sim_type, f"That simulation hit a snag: {e}.",
                         [], {"error": str(e)})
