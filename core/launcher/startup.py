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

STARTUP_STAGES = ("configuration", "kernel", "runtime", "brains", "memory", "knowledge",
                  "perception", "simulation", "coordinator", "executive", "plugins",
                  "voice", "wake_word", "orb", "ui", "ready")


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

    def _stage_brains(self):
        from core.brains import SituationReportBus, build_brains
        bus = SituationReportBus()
        self.components["report_bus"] = bus
        brains = build_brains(services=self.components.get("kernel"), report_bus=bus)
        self.components["brains"] = brains
        return "ok", f"{len(brains)} cognitive brains online"

    def _stage_memory(self):
        brains = self.components.get("brains", {})
        self.components["memory"] = brains.get("memory_brain")
        return "ok", "memory brain online" if self.components["memory"] is not None \
            else "skipped: no memory brain"

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
        from core.audio.listener.microphone import LiveMicrophone
        from core.audio.listener.service import get_listening_service
        service = get_listening_service(
            microphone=LiveMicrophone(), wake_required=True, store_audio=False)
        runtime = self.components.get("runtime")
        if runtime is not None:
            service.attach(runtime)
            self._wire_voice_controls(runtime, service)
        try:
            service.start()
        except Exception as e:  # noqa: BLE001
            return "skipped", f"audio input unavailable: {type(e).__name__}"
        self.components["voice"] = service
        return "ok", "continuous listening started"

    def _stage_wake_word(self):
        if self.headless:
            return "skipped", "headless"
        voice = self.components.get("voice")
        if voice is None:
            return "skipped", "voice unavailable"
        words = self.config.get("wake_words") or ["friday", "hey friday", "okay friday"]
        try:
            voice.pipeline.wake.set_words(words)
        except Exception:  # noqa: BLE001
            log.debug("wake word configuration failed", exc_info=True)
        return "ok", "wake words active: " + ", ".join(voice.pipeline.wake.words())

    def _stage_orb(self):
        if self.headless:
            return "skipped", "headless"
        from core.io.orb import OrbController
        runtime = self.components.get("runtime")
        controller = OrbController(bus=runtime)
        try:
            from core.infra.friday_signal import get_bus
            controller.add_source_bus(get_bus())
        except Exception:  # noqa: BLE001
            log.debug("global expression bus unavailable", exc_info=True)
        controller.start()
        self.components["orb"] = controller
        return "ok", f"orb controller online ({controller.mode} mode)"

    def _stage_ui(self):
        if self.headless:
            return "skipped", "headless"
        return "ok", "ui available"

    def _stage_ready(self):
        if not self.headless:
            self._announce_ready()
        return ("ok", "FRIDAY ready") if self.components.get("coordinator") is not None \
            else ("failed", "core not initialized")

    def _wire_voice_controls(self, runtime, service) -> None:
        from core.infra.friday_signal import Signal
        from core.audio.listener.pipeline import ListeningState
        from core.io.orb.state import InteractionMode

        async def on_orb_wake(_event):
            try:
                service.pipeline.wake_required = False
                service.pipeline._set_state(ListeningState.LISTENING)
            except Exception:  # noqa: BLE001
                log.debug("orb wake bridge failed", exc_info=True)

        async def on_mode(event):
            mode = str(getattr(event, "data", "") or "").lower()
            try:
                if mode == InteractionMode.TEXT.value:
                    service.set_privacy(True)
                elif mode == InteractionMode.VOICE.value:
                    service.set_privacy(False)
                    service.pipeline.wake_required = True
            except Exception:  # noqa: BLE001
                log.debug("voice mode bridge failed", exc_info=True)

        try:
            runtime.on(Signal.ORB_WAKE, on_orb_wake)
            runtime.on(Signal.ORB_MODE, on_mode)
            runtime.on(Signal.ORB_MODE_SET, on_mode)
        except Exception:  # noqa: BLE001
            log.debug("voice control subscription failed", exc_info=True)

    def _announce_ready(self) -> None:
        runtime = self.components.get("runtime")
        if runtime is None:
            return
        try:
            from core.infra.friday_signal import Signal
            from core.io.orb.speech_bridge import SpeechBridge
            text = "Hello. I'm FRIDAY. I'm ready."
            SpeechBridge(runtime).emit_speech(text, block=False)
            runtime.emit(Signal.SPEAK_START, text, "startup")
        except Exception:  # noqa: BLE001
            log.debug("ready announcement failed", exc_info=True)
