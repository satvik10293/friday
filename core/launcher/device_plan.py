"""
core/launcher/device_plan.py — M35 Device Wizard.
Detect → measure → classify → write: the first-run wizard's hardware split
policy, for every user's machine (plan/MASTER_PLAN.md, platform horizon).

Rules:
  * MEASURE, DON'T GUESS. Spec sheets lie — an iGPU that benchmarks slower
    than the CPU is classified as no useful GPU. A detected backend that
    cannot be measured yet (e.g. OpenVINO GPU, no torch device) is recorded
    but NEVER selected: unmeasured means unproven.
  * Tiers → split policy:
      good_gpu     (≥2.0× measured speedup)  local models + perception on GPU
      average_gpu  (≥1.2×)                   perception on GPU, reasoning-path
                                             models stay on CPU
      cpu_only     (anything less)           today's behaviour
  * The plan is written to friday_config.json under "device_plan"; the model
    layer (core/intelligence/device.py) is the ONLY reader. Cognition code
    never references devices.
  * Side-effect-free to import; every probe is guarded and degrades to CPU.

There is no local big reasoner to layer-offload (Groq is the only big-model
tier — see plan M36 scope correction); "local_models" means her existing
models: flan-t5, embeddings, whisper STT.

CLI:  python -m core.launcher.device_plan            (measure + print)
      python -m core.launcher.device_plan --write    (also write the plan)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.launcher.device_plan")

PLAN_VERSION = 1
GOOD_SPEEDUP = 2.0
AVERAGE_SPEEDUP = 1.2

_PERCEPTION = ("embeddings", "stt", "vision")
_COMPONENTS = ("local_models",) + _PERCEPTION


@dataclass
class DevicePlan:
    tier: str                                   # good_gpu | average_gpu | cpu_only
    backend: str                                # cuda | mps | cpu
    placements: dict = field(default_factory=dict)   # component → device string
    measured: dict = field(default_factory=dict)     # backend → ms (None = unmeasured)
    detected: list = field(default_factory=list)     # raw detection results
    measured_at: float = field(default_factory=time.time)
    version: int = PLAN_VERSION

    def to_dict(self) -> dict:
        return {"tier": self.tier, "backend": self.backend,
                "placements": dict(self.placements), "measured": dict(self.measured),
                "detected": list(self.detected), "measured_at": self.measured_at,
                "version": self.version}


# ── detection (guarded, never raises) ─────────────────────────────────────────

def detect_backends() -> list[dict]:
    """Which GPU backends exist on this machine. `measurable` marks whether the
    micro-benchmark can run on it (torch device required)."""
    found: list[dict] = []
    try:
        import torch
        if torch.cuda.is_available():
            found.append({"backend": "cuda", "measurable": True,
                          "detail": torch.cuda.get_device_name(0)})
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            found.append({"backend": "mps", "measurable": True,
                          "detail": "Apple Metal (MPS)"})
    except Exception:  # noqa: BLE001
        log.debug("torch backend detection failed", exc_info=True)
    try:
        import importlib.util
        if importlib.util.find_spec("openvino") is not None:
            from openvino import Core
            gpus = [d for d in Core().available_devices if d.startswith("GPU")]
            if gpus:
                found.append({"backend": "openvino-gpu", "measurable": False,
                              "detail": ", ".join(gpus)})
    except Exception:  # noqa: BLE001
        log.debug("openvino detection failed", exc_info=True)
    return found


# ── the micro-benchmark (an embedding-shaped workload) ────────────────────────

def _sync(device: str) -> None:
    import torch
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def benchmark_device(device: str, *, iters: int = 12, quick: bool = False) -> Optional[float]:
    """Milliseconds for a MiniLM-shaped matmul workload on `device`, or None if
    the device can't run it. Small on purpose: the wizard budget is ~10 s total."""
    try:
        import torch
    except ImportError:
        return None
    try:
        batch, seq, dim = (8, 32, 384) if quick else (32, 128, 384)
        x = torch.randn(batch, seq, dim, device=device)
        w = torch.randn(dim, dim, device=device)
        for _ in range(2):                          # warm-up (JIT, transfer, clocks)
            _ = torch.relu(x @ w)
        _sync(device)
        t0 = time.perf_counter()
        for _ in range(iters):
            y = torch.relu(x @ w)
            x = torch.nn.functional.layer_norm(y, (dim,))
        _sync(device)
        return round((time.perf_counter() - t0) * 1000.0, 2)
    except Exception:  # noqa: BLE001
        log.debug("benchmark on %s failed", device, exc_info=True)
        return None


def measure(backends: Optional[list[dict]] = None, *, quick: bool = False) -> dict:
    """CPU baseline + every measurable detected backend. Unmeasurable backends
    are recorded as None."""
    backends = detect_backends() if backends is None else backends
    results: dict = {"cpu": benchmark_device("cpu", quick=quick)}
    for b in backends:
        name = b["backend"]
        results[name] = benchmark_device(name, quick=quick) if b.get("measurable") else None
    return results


# ── classification ─────────────────────────────────────────────────────────────

def classify(measured: dict, detected: Optional[list] = None) -> DevicePlan:
    """Turn measurements into the split policy. Only MEASURED backends can win."""
    detected = detected or []
    cpu_ms = measured.get("cpu")
    best_backend: Optional[str] = None
    best_ms: Optional[float] = None
    for name, ms in measured.items():
        if name == "cpu" or ms is None:
            continue
        if best_ms is None or ms < best_ms:
            best_backend, best_ms = name, ms

    speedup = 0.0
    if cpu_ms and best_ms:
        speedup = round(cpu_ms / best_ms, 2)

    if best_backend and speedup >= GOOD_SPEEDUP:
        tier, backend = "good_gpu", best_backend
        placements = {c: backend for c in _COMPONENTS}
    elif best_backend and speedup >= AVERAGE_SPEEDUP:
        tier, backend = "average_gpu", best_backend
        placements = {"local_models": "cpu", **{c: backend for c in _PERCEPTION}}
    else:
        tier, backend = "cpu_only", "cpu"
        placements = {c: "cpu" for c in _COMPONENTS}

    measured_out = dict(measured)
    measured_out["speedup"] = speedup
    return DevicePlan(tier=tier, backend=backend, placements=placements,
                      measured=measured_out, detected=detected)


def build_device_plan(*, quick: bool = False) -> DevicePlan:
    """Detect → measure → classify. Never raises; worst case is cpu_only."""
    try:
        detected = detect_backends()
        measured = measure(detected, quick=quick)
        plan = classify(measured, detected)
        log.info("device plan: tier=%s backend=%s speedup=%sx",
                 plan.tier, plan.backend, plan.measured.get("speedup"))
        return plan
    except Exception:  # noqa: BLE001
        log.warning("device planning failed — falling back to cpu_only", exc_info=True)
        return classify({"cpu": None})


# ── persistence (friday_config.json is the single home) ───────────────────────

def write_device_plan(plan: DevicePlan, config_path: Path | str) -> bool:
    """Merge the plan into friday_config.json, preserving every other key."""
    path = Path(config_path)
    try:
        cfg = {}
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("existing config unreadable — not overwriting it")
                return False
        cfg["device_plan"] = plan.to_dict()
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except OSError as e:
        log.warning("could not write device plan: %s", e)
        return False


def read_device_plan(config_path: Path | str) -> Optional[dict]:
    path = Path(config_path)
    try:
        if not path.exists():
            return None
        cfg = json.loads(path.read_text(encoding="utf-8"))
        return cfg.get("device_plan")
    except (OSError, ValueError):
        return None


# ── CLI (also the diagnostics re-run hook) ─────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="friday-device-plan",
                                description="Measure CPU vs GPU and print the split policy")
    p.add_argument("--write", action="store_true",
                   help="write the plan into friday_config.json")
    p.add_argument("--quick", action="store_true", help="smaller benchmark workload")
    args = p.parse_args(argv)

    plan = build_device_plan(quick=args.quick)
    print(json.dumps(plan.to_dict(), indent=2))
    if args.write:
        root = Path(__file__).resolve().parents[2]
        ok = write_device_plan(plan, root / "friday_config.json")
        print(f"device_plan {'written to' if ok else 'NOT written to'} friday_config.json")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
