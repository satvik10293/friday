"""
core/simulation/service.py — FRIDAY 4.0 (M11)
The simulation service facade. Creates, runs, replays, forks, and compares
simulations; persists lightweight metadata to `data/simulation.db` (the virtual
worlds themselves stay in memory, sandboxed). The public entry point for Mission
Control and the cognitive space.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .controls import SimulationControls
from .director import SimulationDirector
from .engine import SimulationEngine
from .models import Scenario, Simulation, SimulationType
from .scenario import ScenarioBuilder
from .timeline import Timeline

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "simulation.db"


class _SimStore:
    def __init__(self, path) -> None:
        self._path = str(path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        c = self._conn()
        c.executescript(
            """CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at REAL);
               CREATE TABLE IF NOT EXISTS simulations (
                 id TEXT PRIMARY KEY, name TEXT, sim_type TEXT, status TEXT,
                 parent_id TEXT, steps INTEGER, ok INTEGER, recommendation TEXT,
                 created_at REAL);""")
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version VALUES (1, ?)", (time.time(),))
        c.commit()

    def _conn(self):
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            self._local.c = c
        return c

    def save(self, sim: Simulation) -> None:
        rec = sim.result
        c = self._conn()
        c.execute("""INSERT OR REPLACE INTO simulations
                     (id,name,sim_type,status,parent_id,steps,ok,recommendation,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
                  (sim.id, sim.name, sim.sim_type, sim.status, sim.parent_id,
                   len(sim.steps), int(bool(rec and rec.ok)),
                   json.dumps(rec.recommendation.to_dict() if rec and rec.recommendation else {}),
                   sim.created_at))
        c.commit()

    def list(self, limit: int = 100) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM simulations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM simulations").fetchone()[0]


    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close(); self._local.c = None


class SimulationService:
    def __init__(self, store_path: Optional[str | Path] = None) -> None:
        self._store = _SimStore(store_path or _DEFAULT_PATH)
        self._engine = SimulationEngine()
        self._director = SimulationDirector(self._engine)
        self._sims: dict[str, Simulation] = {}      # in-memory live sims

    # ── create / run ────────────────────────────────────────────────────────────
    def create(self, name: str, sim_type, params: Optional[dict] = None) -> Simulation:
        scenario = ScenarioBuilder.build(sim_type, name=name, params=params)
        sim = Simulation(name=name, sim_type=scenario.sim_type, scenario=scenario)
        self._sims[sim.id] = sim
        self._store.save(sim)
        return sim

    def run(self, sim: Simulation, *, steps: Optional[int] = None) -> Simulation:
        self._director.run(sim, steps=steps)
        self._store.save(sim)
        return sim

    def simulate(self, problem: str, *, params: Optional[dict] = None,
                 steps: Optional[int] = None) -> Simulation:
        """One-shot: problem → recommendation (observe→simulate→evaluate→present)."""
        sim = self._director.direct(problem, params=params, steps=steps)
        self._sims[sim.id] = sim
        self._store.save(sim)
        return sim

    # ── interactivity ───────────────────────────────────────────────────────────
    def get(self, sim_id: str) -> Optional[Simulation]:
        return self._sims.get(sim_id)

    def controls(self, sim: Simulation) -> SimulationControls:
        return SimulationControls(sim)

    def timeline(self, sim: Simulation) -> Timeline:
        return Timeline(sim)

    def replay(self, sim: Simulation) -> SimulationControls:
        c = SimulationControls(sim)
        c.replay()
        return c

    def fork(self, sim: Simulation, at_step: Optional[int] = None) -> Simulation:
        """Branch a new simulation from an existing one at `at_step` (default: end).
        The fork copies history up to that point; it is independent thereafter."""
        cut = len(sim.steps) if at_step is None else max(0, min(at_step, len(sim.steps)))
        fork = Simulation(name=f"{sim.name} (fork)", sim_type=sim.sim_type,
                          scenario=sim.scenario, parent_id=sim.id,
                          steps=list(sim.steps[:cut]))
        self._sims[fork.id] = fork
        self._store.save(fork)
        return fork

    def compare(self, a: Simulation, b: Simulation) -> dict:
        """Diff two simulations' final metrics + recommendations."""
        ma = a.result.final_metrics if a.result else {}
        mb = b.result.final_metrics if b.result else {}
        keys = set(ma) | set(mb)
        diff = {k: {"a": ma.get(k), "b": mb.get(k)} for k in sorted(keys)}
        return {
            "a": {"id": a.id, "name": a.name,
                  "rec": a.result.recommendation.text if a.result and a.result.recommendation else ""},
            "b": {"id": b.id, "name": b.name,
                  "rec": b.result.recommendation.text if b.result and b.result.recommendation else ""},
            "metric_diff": diff,
        }

    # ── diagnostics ─────────────────────────────────────────────────────────────
    def list(self, limit: int = 100) -> list[dict]:
        return self._store.list(limit)

    def types(self) -> list[str]:
        return [t.value for t in SimulationType]

    def health(self) -> dict:
        return {"status": "ok", "live": len(self._sims), "persisted": self._store.count()}

    def close(self) -> None:
        self._store.close()


_service: Optional[SimulationService] = None
_lock = threading.Lock()


def get_simulation_service() -> SimulationService:
    global _service
    with _lock:
        if _service is None:
            _service = SimulationService()
    return _service
