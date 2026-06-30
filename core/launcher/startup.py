"""
core/launcher/startup.py — FRIDAY V3 (M20)
The ordered startup sequence. Brings FRIDAY up stage by stage, in the documented order:

    Configuration → Kernel → Runtime → Memory → Knowledge → Perception →
    Simulation → Coordinator → Executive → Plugins → Voice → UI → Ready

Each stage is isolated: a failure is recorded and the sequence continues with graceful
degradation (optional subsystems may be skipped), so FRIDAY still reaches a usable state.
The sequence wires existing subsystems via services + the report bus — it contains NO
cognitive logic of its own. Returns a structured `StartupReport`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("friday.launcher.startup")

STARTUP_STAGES = ("configuration", "kernel", "runtime", "memory", "knowledge",
                  "perception", "simulation", "coordinator", "executive", "plugins",
                  "voice", "ui", "ready")


@dataclass
class StageResult:
    stage: str
    status: str                      # ok | skipped | failed
    detail: str = ""
    ms: float = 0.0

    def to_dict(self) -> dict:
        return {"stage": self.stage, "status": self.status, "detail": self.detail,
                "ms": round(self.ms, 2)}


@dataclass
class StartupReport:
    stages: list = field(default_factory=list)
    ready: bool = False
    components: dict = field(default_factory=dict)
    total_ms: float = 0.0

    def ok(self) -> bool:
        return self.ready and not any(s.status == "failed" for s in self.stages)

    def to_dict(self) -> dict:
        return {"ready": self.ready, "ok": self.ok(), "total_ms": round(self.total_ms, 2),
                "stages": [s.to_dict() for s in self.stages]}


class StartupSequence:
    """Runs the staged boot. `headless` skips UI/voice (servers/devices); `start_runtime`
    controls whether the async runtime loop is actually started."""

    def __init__(self, *, config: Optional[dict] = None, headless: bool = True,
                 start_runtime: bool = False) -> None:
        self.config = dict(config or {})
        self.headless = headless
        self.start_runtime = start_runtime
        self.components: dict = {}

    def run(self) -> StartupReport:
        report = StartupReport()
        t0 = time.perf_counter()
        for stage in STARTUP_STAGES:
            result = self._run_stage(stage)
            report.stages.append(result)
        report.components = self.components
        report.ready = self.components.get("coordinator") is not None and \
            self.components.get("executive") is not None
        report.total_ms = (time.perf_counter() - t0) * 1000.0
        log.info("[Startup] FRIDAY %s in %.0f ms", "ready" if report.ready else "degraded",
                 report.total_ms)
        return report

    def _run_stage(self, stage: str) -> StageResult:
        t0 = time.perf_counter()
        try:
            status, detail = getattr(self, f"_stage_{stage}")()
        except Exception as e:  # noqa: BLE001 — a stage failure never aborts the boot
            log.debug("startup stage %s failed", stage, exc_info=True)
            status, detail = "failed", f"{type(e).__name__}: {e}"
        return StageResult(stage, status, detail, (time.perf_counter() - t0) * 1000.0)

    # ── stages ───────────────────────────────────────────────────────────────────
    def _stage_configuration(self):
        from core.services.configuration_service import ConfigurationService
        self.components["configuration"] = ConfigurationService(self.config)
        return "ok", "configuration loaded"

    def _stage_kernel(self):
        from core.services import build_default_container
        runtime = self.components.get("runtime")
        self.components["kernel"] = build_default_container(runtime=runtime, config=self.config)
        return "ok", "service kernel (DI container) built"

    def _stage_runtime(self):
        from core.runtime import get_runtime
        rt = get_runtime()
        if self.start_runtime:
            rt.start(timeout=10)
        self.components["runtime"] = rt
        # re-wire the kernel's runtime service now that the runtime exists
        kernel = self.components.get("kernel")
        if kernel is not None:
            from core.services.runtime_service import RuntimeService
            kernel.register("runtime", RuntimeService(rt))
        return "ok", "runtime " + ("started" if self.start_runtime else "constructed")

    def _stage_memory(self):
        from core.brains import SituationReportBus, build_brains
        bus = SituationReportBus()
        self.components["report_bus"] = bus
        brains = build_brains(services=self.components.get("kernel"), report_bus=bus)
        self.components["brains"] = brains
        self.components["memory"] = brains.get("memory_brain")
        return "ok", f"{len(brains)} brains; memory brain online"

    def _stage_knowledge(self):
        memory = self.components.get("memory")
        if memory is None:
            return "skipped", "no memory brain"
        self.components["knowledge"] = memory.knowledge_graph()
        return "ok", "knowledge graph online"

    def _stage_perception(self):
        brains = self.components.get("brains", {})
        present = [n for n in ("vision_brain", "audio_brain", "spatial_brain") if n in brains]
        return "ok", "perception brains: " + ", ".join(present)

    def _stage_simulation(self):
        from core.brains.simulation import SimulationService
        self.components["simulation"] = SimulationService(
            container=self.components.get("kernel"), report_bus=self.components.get("report_bus"))
        return "ok", "simulation brain online"

    def _stage_coordinator(self):
        from core.brains.executive.brain import ExecutiveBrain
        from core.coordinator import CognitiveCoordinator
        kernel = self.components.get("kernel")
        executive = ExecutiveBrain(services=kernel)
        if kernel is not None:
            kernel.register("executive_brain", executive)
        self.components["executive"] = executive
        self.components["coordinator"] = CognitiveCoordinator(
            services=kernel, report_bus=self.components.get("report_bus"), executive=executive)
        return "ok", "coordinator + executive wired"

    def _stage_executive(self):
        return ("ok", "executive ready") if self.components.get("executive") is not None \
            else ("failed", "executive missing")

    def _stage_plugins(self):
        kernel = self.components.get("kernel")
        plugin = kernel.try_get("plugin") if kernel is not None else None
        if plugin is None:
            return "skipped", "no plugin service"
        return "ok", f"plugin registry ready ({len(plugin.kinds())} kinds)"

    def _stage_voice(self):
        if self.headless:
            return "skipped", "headless"
        import importlib.util
        if importlib.util.find_spec("sounddevice") is None:
            return "skipped", "no audio device backend"
        return "ok", "voice available"

    def _stage_ui(self):
        if self.headless:
            return "skipped", "headless"
        return "ok", "ui available"

    def _stage_ready(self):
        return ("ok", "FRIDAY ready") if self.components.get("coordinator") is not None \
            else ("failed", "core not initialized")
