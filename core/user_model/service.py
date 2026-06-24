"""
core/user_model/service.py — FRIDAY 4.0 (M9)
The public facade of the Personal Model. Composes the store and every engine
(profile, preferences, habits, interests, projects, communication, learning,
relationship memory) plus the Personal Intelligence Engine and User Context
Builder into one object the rest of FRIDAY uses.

Holds optional, injected references to the M2 Memory, M4 Goals, and M7/M8
Knowledge services — additive integration, no edits to those modules. Observability
mirrors the M4/M5/M7 pattern: events on the runtime bus + metrics + health.

Privacy-first: all state lives in `data/user_model.db` locally; nothing is sent
anywhere.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .communication_model import CommunicationModel
from .habits import HabitTracker
from .interests import InterestGraph
from .learning_profile import LearningProfile
from .preferences import PreferenceEngine
from .project_tracker import ProjectTracker
from .relationship_memory import RelationshipMemory
from .store import UserModelEvent, UserModelStore
from .user_profile import ProfileManager

log = logging.getLogger("friday.user_model.service")


class UserModelService:
    def __init__(self, store: Optional[UserModelStore] = None, *,
                 knowledge_service=None, goal_service=None, memory_service=None,
                 runtime=None) -> None:
        self._store = store if store is not None else UserModelStore()
        self._runtime = runtime
        self.knowledge_service = knowledge_service
        self.goal_service = goal_service
        self.memory_service = memory_service
        self._lock = threading.RLock()

        emit = self._emit
        self.profile = ProfileManager(self._store, emit=emit)
        self.preferences = PreferenceEngine(self._store, emit=emit)
        self.habits = HabitTracker(self._store, emit=emit)
        self.interests = InterestGraph(self._store, emit=emit)
        self.projects = ProjectTracker(self._store, emit=emit)
        self.communication = CommunicationModel(self._store, emit=emit)
        self.learning = LearningProfile(self._store, emit=emit)
        self.relationship = RelationshipMemory(self._store, emit=emit)

        # lazily-built higher layers (avoid import cycles)
        self._intelligence = None
        self._context_builder = None

    @property
    def store(self) -> UserModelStore:
        return self._store

    @property
    def intelligence(self):
        if self._intelligence is None:
            from .personal_intelligence import PersonalIntelligence
            self._intelligence = PersonalIntelligence(self)
        return self._intelligence

    @property
    def context_builder(self):
        if self._context_builder is None:
            from .user_context import UserContextBuilder
            self._context_builder = UserContextBuilder(self)
        return self._context_builder

    # ── convenience pass-throughs ───────────────────────────────────────────────
    def build_user_context(self, query: str = "", **kw):
        return self.context_builder.build(query, **kw)

    def suggest_knowledge(self, query: str, **kw):
        return self.intelligence.suggest_knowledge(query, **kw)

    def understanding(self) -> dict:
        return self.intelligence.build_understanding()

    # ── observability ───────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        counts = self._store.counts()
        return {
            **counts,
            "events": {
                "profile_updates": len(self._store.events(
                    UserModelEvent.PROFILE_UPDATED.value, limit=1000)),
                "preference_changes": len(self._store.events(
                    UserModelEvent.PREFERENCE_CHANGED.value, limit=1000)),
                "interest_growth": len(self._store.events(
                    UserModelEvent.INTEREST_GROWN.value, limit=1000)),
                "habit_discoveries": len(self._store.events(
                    UserModelEvent.HABIT_DISCOVERED.value, limit=1000)),
                "project_updates": len(self._store.events(
                    UserModelEvent.PROJECT_UPDATED.value, limit=1000)),
                "learning_adaptations": len(self._store.events(
                    UserModelEvent.LEARNING_ADAPTED.value, limit=1000)),
            },
        }

    def health(self) -> dict:
        return {"status": "ok", "store": self._store.health(),
                "has_profile": self._store.get_profile() is not None,
                "interests": len(self._store.list_interests()),
                "active_projects": len(self.projects.active())}

    def attach(self, runtime) -> None:
        """Wire into the M1 runtime: register a health probe."""
        self._runtime = runtime
        try:
            runtime.register_health("user_model", self.health)
        except Exception:
            log.debug("runtime attach partial", exc_info=True)

    def _emit(self, event: UserModelEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data=data, source="user_model")
        except Exception:
            log.debug("event emit failed", exc_info=True)

    def close(self) -> None:
        self._store.close()


# ── singleton ─────────────────────────────────────────────────────────────────────
_service: Optional[UserModelService] = None
_svc_lock = threading.Lock()


def get_user_model_service() -> UserModelService:
    global _service
    with _svc_lock:
        if _service is None:
            _service = UserModelService()
    return _service
