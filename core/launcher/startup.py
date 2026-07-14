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
                  "intelligence", "mind", "voice", "wake_word", "ui", "ready")


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
        # One Memory (Phase C): the M2 service is the single long-term store.
        from core.memory import get_memory_service, migrate_all
        memory_service = get_memory_service()
        self.components["memory_service"] = memory_service
        imported: list = []
        if not self.headless:                       # full boots migrate; tests don't
            migration = migrate_all(memory_service)  # idempotent; legacy stores read-only
            imported = [k for k, v in migration.items()
                        if isinstance(v, dict) and v.get("status") == "ok"]
        kernel = self.components.get("kernel")
        if kernel is not None:
            from core.services.memory_service import MemoryService as MemoryAdapter
            kernel.register("memory", MemoryAdapter(memory_service))
        detail = "memory service online"
        if imported:
            detail += " (migrated: " + ", ".join(imported) + ")"
        return "ok", detail

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

    def _stage_intelligence(self):
        from core.goals.service import get_goal_service
        from core.intelligence.service import get_intelligence_os
        from core.user_model.service import get_user_model_service
        kernel = self.components.get("kernel")
        self.components["goals"] = get_goal_service()
        self.components["user_model"] = get_user_model_service()
        from core.memory.core_memory import get_core_memory
        ios = get_intelligence_os(
            memory_service=self.components.get("memory_service") or
            (kernel.try_get("memory") if kernel is not None else None),
            knowledge_service=self.components.get("knowledge"),
            goal_service=self.components.get("goals"),
            user_model=self.components.get("user_model"),
            simulation_service=self.components.get("simulation"),
            core_memory=get_core_memory(),         # standing memory (M43)
            discover_optional=not self.headless)   # flan-t5 when transformers is present
        self.components["intelligence"] = ios
        # register the module services the M46 brains observe — the brains
        # resolve lazily, so registering here (after the brains stage) works
        if kernel is not None:
            kernel.register("intelligence", ios)
            kernel.register("goals", self.components["goals"])
            try:
                from core.knowledge.knowledge_service import get_knowledge_service
                kernel.register("knowledge", get_knowledge_service())
            except Exception:  # noqa: BLE001 — the library is always optional
                pass
        runtime = self.components.get("runtime")
        if runtime is not None:
            ios.attach(runtime)
        loaded = ios.health_report().get("models_loaded", 0)
        return "ok", f"intelligence OS online ({loaded} local models)"

    def _stage_mind(self):
        """Internal Mind (M23): thought stream + self model + background cognition."""
        from core.cognition.background import BackgroundCognition
        from core.cognition.thoughts import ThoughtStream
        from core.observability.decision_log import get_decision_log
        from core.self_model import SelfModel

        thoughts = ThoughtStream()
        self.components["thoughts"] = thoughts
        self_model = SelfModel(ios=self.components.get("intelligence"),
                               decision_log=get_decision_log(),
                               runtime=self.components.get("runtime"),
                               goals=self.components.get("goals"),
                               thoughts=thoughts)
        self.components["self_model"] = self_model
        generator = None
        if self.components.get("goals") is not None:
            from core.goals.generator import GoalGenerator
            generator = GoalGenerator(self.components["goals"], thoughts=thoughts)
        background = BackgroundCognition(
            thoughts=thoughts, memory=self.components.get("memory_service"),
            goals=self.components.get("goals"), self_model=self_model,
            generator=generator)
        self.components["background_cognition"] = background
        runtime = self.components.get("runtime")
        if runtime is not None and self.start_runtime:
            background.attach(runtime)
        thoughts.think("observation", "I'm awake. Systems are coming online.",
                       source="startup")
        return "ok", "thought stream + self model + background cognition online"

    def _stage_voice(self):
        if self.headless:
            return "skipped", "headless"
        import importlib.util
        if importlib.util.find_spec("sounddevice") is None:
            return "skipped", "no audio device backend"
        from core.audio.listener.microphone import LiveMicrophone
        from core.audio.listener.service import get_listening_service
        bridge = None
        ios = self.components.get("intelligence")
        if ios is not None:
            from .conversation import ConversationBridge
            teacher = None
            try:                             # temporary cloud teacher (M30)
                from core.intelligence.teacher import get_teacher
                teacher = get_teacher()      # None unless enabled + key present
            except Exception:  # noqa: BLE001 — the teacher is always optional
                pass
            reasoner = None
            try:                             # cloud-primary basic reasoner (M42)
                from core.intelligence.cloud_reasoner import get_cloud_reasoner
                reasoner = get_cloud_reasoner()  # None unless cloud-primary + key
            except Exception:  # noqa: BLE001 — cloud-off must never break boot
                pass
            knowledge = None
            try:                             # librarian: M7 bridge + world fetcher (M40)
                from core.knowledge.knowledge_service import get_knowledge_service
                knowledge = get_knowledge_service()
            except Exception:  # noqa: BLE001 — the librarian is always optional
                pass
            bridge = ConversationBridge(
                ios, memory=self.components.get("memory_service"),
                self_model=self.components.get("self_model"),
                goals=self.components.get("goals"), teacher=teacher,
                knowledge=knowledge, reasoner=reasoner,
                brains=self.components.get("brains"))   # addressable society (M46)
            self.components["conversation"] = bridge
            kernel = self.components.get("kernel")
            if kernel is not None:       # the M46 voice/reasoning brains observe this
                kernel.register("conversation", bridge)
            self_model = self.components.get("self_model")
            if self_model is not None:
                self_model._conversation = bridge
        # human-level listening (M31): require the wake word, verify transcripts,
        # and hold a short follow-up window so natural conversation flows without
        # re-waking — so she stops answering TV, ambient speech, and herself
        lc = self.config.get("listening") or {}
        service = get_listening_service(
            microphone=LiveMicrophone(), intelligence_os=bridge,
            wake_required=lc.get("require_wake", True),
            verify=lc.get("verify", True),
            conversation_window_s=lc.get("conversation_window_s", 8.0),
            store_audio=False)
        runtime = self.components.get("runtime")
        if runtime is not None:
            service.attach(runtime)
            self._wire_voice_controls(runtime, service)
            if bridge is not None:
                self._wire_speech_output(runtime, bridge)
        if bridge is not None:
            self._wire_barge_in(service, bridge)
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

        async def on_mode(event):
            mode = str(getattr(event, "data", "") or "").lower()
            try:
                if mode == "text":
                    service.set_privacy(True)
                elif mode == "voice":
                    service.set_privacy(False)
                    service.pipeline.wake_required = False
            except Exception:  # noqa: BLE001
                log.debug("voice mode bridge failed", exc_info=True)

        try:
            if hasattr(Signal, "UI_MODE"):
                runtime.on(Signal.UI_MODE, on_mode)
        except Exception:  # noqa: BLE001
            log.debug("voice control subscription failed", exc_info=True)

    def _wire_barge_in(self, service, bridge) -> None:
        """The user starting to speak stops FRIDAY mid-answer."""
        from core.audio.listener.events import AudioEvent

        def on_user_speech(_event) -> None:
            bridge.interrupt()

        try:
            service.bus.on(AudioEvent.SPEECH_DETECTED, on_user_speech)
            service.bus.on(AudioEvent.INTERRUPT_REQUESTED, on_user_speech)
        except Exception:  # noqa: BLE001
            log.debug("barge-in wiring failed", exc_info=True)

    def _wire_speech_output(self, runtime, bridge) -> None:
        """SPEAK_START on the runtime bus → spoken aloud via the bridge."""
        from core.infra.friday_signal import Signal

        async def on_speak(event):
            try:
                bridge.announce(str(getattr(event, "data", "") or ""))
            except Exception:  # noqa: BLE001
                log.debug("speech output failed", exc_info=True)

        try:
            runtime.on(Signal.SPEAK_START, on_speak)
        except Exception:  # noqa: BLE001
            log.debug("speech output subscription failed", exc_info=True)

    def _announce_ready(self) -> None:
        runtime = self.components.get("runtime")
        text = "Hello. I'm FRIDAY. I'm ready."
        if runtime is not None and self.start_runtime:
            try:
                from core.infra.friday_signal import Signal
                runtime.emit(Signal.SPEAK_START, text, "startup")
                return
            except Exception:  # noqa: BLE001
                log.debug("ready announcement failed", exc_info=True)
        bridge = self.components.get("conversation")
        if bridge is not None:
            try:
                bridge.announce(text)
            except Exception:  # noqa: BLE001
                log.debug("ready announcement failed", exc_info=True)
