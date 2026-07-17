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
                  "intelligence", "skills", "mind", "nervous", "voice", "wake_word",
                  "ui", "ready")


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
        detail = "perception brains: " + ", ".join(present)
        # live camera vision is OPT-IN (perception.live in config, default off):
        # continuously running a camera + detectors is heavy for a CPU box, so
        # it only starts when the owner asks. The vision brain has a real
        # backend either way; without live capture it simply sees nothing.
        if (self.config.get("perception") or {}).get("live") and not self.headless:
            try:
                from core.vision.service import get_vision_system
                vision = get_vision_system(runtime=self.components.get("runtime"))
                vision.start()
                kernel = self.components.get("kernel")
                if kernel is not None:
                    kernel.register("vision", vision)
                self.components["vision"] = vision
                detail += " (+live camera)"
            except Exception as e:  # noqa: BLE001 — vision must never break the boot
                log.debug("live vision unavailable", exc_info=True)
                detail += f" (live vision failed: {type(e).__name__})"
        return "ok", detail

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
        # THE COORDINATION LOOP: tick every brain each interval so the society
        # actually runs — observe → report → Coordinator merges → Executive.
        # Without this the 12 brains are built but dormant (they never report).
        runtime = self.components.get("runtime")
        if runtime is not None and self.start_runtime and hasattr(runtime, "schedule"):
            cs = float((self.config.get("coordinator") or {}).get("cycle_s", 2.0))
            try:
                runtime.schedule("cognitive_cycle", self._run_cognitive_cycle, cs)
            except Exception:  # noqa: BLE001 — the boot never fails on this
                log.debug("cognitive cycle scheduling failed", exc_info=True)
        return "ok", "coordinator + executive wired"

    def _run_cognitive_cycle(self) -> None:
        """One coordinated pass over the whole society: every brain observes and
        reports, then the Coordinator merges those Situation Reports into
        Unified Situations for the Executive. This is what keeps every module
        coordinated — it runs on the runtime scheduler each cycle."""
        for brain in (self.components.get("brains") or {}).values():
            try:
                brain.tick()            # observe → report → publish (never raises)
            except Exception:  # noqa: BLE001 — one brain never stalls the cycle
                log.debug("brain tick failed in cycle", exc_info=True)
        coordinator = self.components.get("coordinator")
        if coordinator is not None:
            try:
                coordinator.coordinate()   # merge → Unified Situations → Executive
            except Exception:  # noqa: BLE001
                log.debug("coordinate failed in cycle", exc_info=True)

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

    def _stage_skills(self):
        """Her body (M47): the governed action layer. Build the skill registry
        (37 tiered action skills) + the SkillExecutor, which self-wires the M3
        security pipeline (policy → clearance → approval → sandbox → audit).
        Nothing here acts; it makes acting POSSIBLE and safe."""
        from core.observability.decision_log import get_decision_log
        from core.skills import SkillRegistry
        from core.skills.builtin import register_builtins
        from core.skills.executor import SkillExecutor

        registry = SkillRegistry()
        register_builtins(registry)              # memory/system reads + 37 actions
        executor = SkillExecutor(registry=registry,
                                 decision_log=get_decision_log(),
                                 runtime=self.components.get("runtime"))
        self.components["skills"] = executor
        kernel = self.components.get("kernel")
        if kernel is not None:
            kernel.register("skills", executor)  # brains/executive reach actions here
            # give the brains real backends for the world + spatial + system
            # sensing they already try to observe (lightweight; no camera/mic
            # capture here — that's opt-in, see the perception stage)
            for name, factory in (("world", self._world_service),
                                  ("sensors", self._sensors_service),
                                  ("spatial", self._spatial_service)):
                try:
                    svc = factory()
                    if svc is not None:
                        kernel.register(name, svc)
                        self.components[name] = svc
                except Exception:  # noqa: BLE001 — an optional backend never fails boot
                    log.debug("optional service %s unavailable", name, exc_info=True)
        return "ok", f"action layer online ({len(registry)} governed skills)"

    @staticmethod
    def _world_service():
        from core.world.world_model import WorldModel
        return WorldModel()

    @staticmethod
    def _sensors_service():
        from core.sensors.manager import SensorManager
        return SensorManager()

    @staticmethod
    def _spatial_service():
        from core.spatial.service import SpatialService
        return SpatialService()      # scene-graph engine; no camera

    def _proactive_speak(self, text: str) -> None:
        """Speak a proactive nudge through the conversation bridge (resolved at
        call time — the bridge is built in the later voice stage, but proactive
        ticks only run once the runtime is up)."""
        bridge = self.components.get("conversation")
        if bridge is not None and getattr(bridge, "speak_answers", False):
            try:
                bridge.announce(text)
            except Exception:  # noqa: BLE001
                log.debug("proactive announce failed", exc_info=True)

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
        # proactive presence (M49): surface salient thoughts/proposals as tray
        # notifications. Notifications-only, config-gated, rate-limited. Not on
        # headless boots (no owner to notify).
        notifier = None
        pcfg = self.config.get("proactive") or {}
        if pcfg.get("enabled", True) and not self.headless:
            from core.io.proactive import ProactiveNotifier
            from core.io.tray import notify as _tray_notify
            notifier = ProactiveNotifier(
                thoughts=thoughts, goals=self.components.get("goals"),
                notify=_tray_notify,
                speak=(lambda t: self._proactive_speak(t)),
                min_confidence=float(pcfg.get("min_confidence", 0.6)),
                cooldown_s=float(pcfg.get("cooldown_s", 300.0)),
                max_per_hour=int(pcfg.get("max_per_hour", 6)),
                speak_aloud=bool(pcfg.get("speak_aloud", False)))
            self.components["proactive"] = notifier
        background = BackgroundCognition(
            thoughts=thoughts, memory=self.components.get("memory_service"),
            goals=self.components.get("goals"), self_model=self_model,
            generator=generator, notifier=notifier)
        self.components["background_cognition"] = background
        runtime = self.components.get("runtime")
        if runtime is not None and self.start_runtime:
            background.attach(runtime)
        thoughts.think("observation", "I'm awake. Systems are coming online.",
                       source="startup")
        return "ok", "thought stream + self model + background cognition online"

    def _stage_nervous(self):
        """The nervous system (M50): grow a nerve for every module + brain, so
        each one is sensed, self-healed by a safe reflex, and relayed to the
        brain already repaired. The Executive reaches modules through the
        nervous system's gated access — never a module a nerve knows is broken."""
        from core.nervous import NervousSystem

        executive = self.components.get("executive")
        nervous = NervousSystem(report_sink=self._relay_health_to_brain)

        # every cognitive brain is a module with a nerve
        for name, brain in (self.components.get("brains") or {}).items():
            nervous.register(name, brain)
        # plus the executive and the standing subsystems/services
        for name in ("executive", "coordinator", "simulation", "memory_service",
                     "knowledge", "goals", "intelligence", "skills", "world",
                     "sensors", "spatial", "listening", "conversation",
                     "self_model", "background_cognition"):
            module = self.components.get(name)
            if module is not None:
                nervous.register(name, module)

        self.components["nervous"] = nervous
        kernel = self.components.get("kernel")
        if kernel is not None:
            kernel.register("nervous", nervous)
        if executive is not None:
            executive._nervous = nervous     # the brain's gated access to modules

        picture = nervous.pulse()            # first heartbeat: sense + heal now
        runtime = self.components.get("runtime")
        if runtime is not None and self.start_runtime:
            every = float((self.config.get("nervous") or {}).get("pulse_s", 30.0))
            nervous.attach(runtime, every_s=every)
        healed = len(picture.get("healed", []))
        detail = f"{picture['modules']} nerves, overall {picture['overall']}"
        if healed:
            detail += f" (+{healed} self-healed)"
        return "ok", detail

    def _relay_health_to_brain(self, picture: dict) -> None:
        """Relay the consolidated, healed health picture up to the Executive as
        a health situation — the brain's true, self-corrected body map."""
        executive = self.components.get("executive")
        if executive is None or not hasattr(executive, "receive"):
            return
        try:
            executive.receive({
                "summary": f"Body status: {picture.get('overall', 'ok')} "
                           f"({picture.get('modules', 0)} modules, "
                           f"{len(picture.get('degraded', []))} degraded).",
                "category": "health",
                "priority": 0.8 if picture.get("degraded") else 0.2,
                "data": {"health": picture}})
        except Exception:  # noqa: BLE001 — relaying must never break the pulse
            log.debug("relay health to brain failed", exc_info=True)

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
                brains=self.components.get("brains"),   # addressable society (M46)
                skills=self.components.get("skills"))   # governed action layer (M47)
            self.components["conversation"] = bridge
            kernel = self.components.get("kernel")
            if kernel is not None:       # the M46 voice/reasoning brains observe this
                kernel.register("conversation", bridge)
            self_model = self.components.get("self_model")
            if self_model is not None:
                self_model._conversation = bridge
        # human-level listening (M31): require the wake word, verify transcripts,
        # and hold a follow-up window so natural conversation flows without
        # re-waking — so she stops answering TV, ambient speech, and herself
        lc = self.config.get("listening") or {}
        service = get_listening_service(
            microphone=LiveMicrophone(), intelligence_os=bridge,
            wake_required=lc.get("require_wake", True),
            verify=lc.get("verify", True),
            conversation_window_s=lc.get("conversation_window_s", 18.0),
            follow_up_min_confidence=lc.get("follow_up_min_confidence", 0.62),
            store_audio=False)
        self.components["listening"] = service   # the tray mutes the mic through this
        # hand the bridge the verifier's window so it reopens it when she
        # finishes speaking — the follow-up is timed from her last word, not
        # from when the answer was computed (otherwise her own slow reply eats
        # the window and every turn needs the wake word again)
        if bridge is not None:
            verifier = getattr(service.pipeline, "verifier", None)
            if verifier is not None and getattr(verifier, "conversation", None) is not None:
                bridge._conversation_state = verifier.conversation
                if bridge.speech._on_spoken is None:
                    bridge.speech._on_spoken = bridge._reopen_window
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
        """Let the user interrupt FRIDAY mid-answer — but only on a DELIBERATE
        signal (the wake word, or an explicit interrupt request), never on raw
        speech onset. On a CPU box with no echo cancellation, her own voice
        coming out of the speakers trips SPEECH_DETECTED and used to cut her
        off after one sentence — that was the "she only says part of it" bug.
        Saying "Friday" while she talks still stops her; her own voice can't."""
        from core.audio.listener.events import AudioEvent

        def on_interrupt(_event) -> None:
            bridge.interrupt()

        try:
            service.bus.on(AudioEvent.WAKE_WORD_DETECTED, on_interrupt)
            service.bus.on(AudioEvent.INTERRUPT_REQUESTED, on_interrupt)
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
