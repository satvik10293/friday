"""
core/user_model/models.py — FRIDAY 4.0 (M9)
Pure data models for the Personal Model & User Intelligence System. No I/O — every
type here is trivially serialisable and testable. These describe *who the user is*
(profile, preferences, habits, interests, projects, communication/learning style,
approved long-term facts) and the assembled *user context* the rest of FRIDAY reasons over.

Privacy-first: these structures only ever hold what the user has provided or
explicitly approved. Nothing here implies surveillance or cloud sync.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


def now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── enums ─────────────────────────────────────────────────────────────────────────
class PreferenceCategory(str, Enum):
    UI = "ui"
    CODING = "coding"
    LEARNING = "learning"
    COMMUNICATION = "communication"
    GENERAL = "general"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"


class CommunicationAspect(str, Enum):
    DETAIL_LEVEL = "detail_level"          # brief … detailed
    TECHNICAL_DEPTH = "technical_depth"    # simple … technical
    STRUCTURE = "structure"                # prose … structured
    TERMINOLOGY = "terminology"            # layman … domain


class LearningStyleType(str, Enum):
    VISUAL = "visual"
    STEP_BY_STEP = "step_by_step"
    EXAMPLE_DRIVEN = "example_driven"
    DEEP_DIVE = "deep_dive"


# ── core models ───────────────────────────────────────────────────────────────────
@dataclass
class UserProfile:
    name: str = ""
    preferred_name: str = ""
    education: str = ""
    interests: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    projects: list = field(default_factory=list)         # project ids/names
    long_term_goals: list = field(default_factory=list)
    short_term_goals: list = field(default_factory=list)
    version: int = 1
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    metadata: dict = field(default_factory=dict)

    def display_name(self) -> str:
        return self.preferred_name or self.name or "User"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "UserProfile":
        d = dict(d or {})
        return UserProfile(**{k: d[k] for k in d if k in UserProfile.__dataclass_fields__})


@dataclass
class Preference:
    key: str
    category: str = PreferenceCategory.GENERAL.value
    value: str = ""
    score: float = 0.5            # learned strength, 0..1
    evidence_count: int = 0
    updated_at: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Habit:
    key: str                      # e.g. "coding@evening"
    kind: str = ""                # e.g. "coding"
    bucket: str = ""              # e.g. "evening"
    count: int = 0
    confidence: float = 0.0
    updated_at: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Interest:
    name: str
    weight: float = 0.5
    count: int = 0
    category: str = ""
    first_seen: float = field(default_factory=now)
    last_seen: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class InterestLink:
    a: str
    b: str
    weight: float = 1.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Project:
    id: str = field(default_factory=new_id)
    name: str = ""
    status: str = ProjectStatus.ACTIVE.value
    description: str = ""
    goals: list = field(default_factory=list)
    milestones: list = field(default_factory=list)     # list[dict]: {title, done}
    knowledge_ids: list = field(default_factory=list)
    memory_ids: list = field(default_factory=list)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Project":
        d = dict(d or {})
        return Project(**{k: d[k] for k in d if k in Project.__dataclass_fields__})


@dataclass
class RelationshipFact:
    id: str = field(default_factory=new_id)
    kind: str = "context"          # project | goal | decision | context
    content: str = ""
    approved: bool = False         # must be user-approved to be active
    sensitive: bool = False
    created_at: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Evidence:
    """One explainable reason behind a personalization decision."""
    source: str                    # interest | preference | goal | project | habit
    detail: str
    weight: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class UserContextPackage:
    """The assembled personal context, consumed by the Executive Brain, the
    Knowledge System, and the Agent Team. Fully inspectable."""
    user: dict = field(default_factory=dict)            # profile summary
    goals: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    preferences: list = field(default_factory=list)
    interests: list = field(default_factory=list)
    knowledge: list = field(default_factory=list)
    memories: list = field(default_factory=list)
    confidence: float = 0.0
    trace_id: Optional[str] = None
    created_at: float = field(default_factory=now)

    @property
    def is_empty(self) -> bool:
        return not (self.goals or self.projects or self.preferences
                    or self.interests or self.knowledge or self.memories)

    def summary(self) -> str:
        return (f"user_context(user={self.user.get('display_name','?')}, "
                f"goals={len(self.goals)}, projects={len(self.projects)}, "
                f"prefs={len(self.preferences)}, interests={len(self.interests)}, "
                f"knowledge={len(self.knowledge)}, conf={self.confidence:.2f})")

    def to_dict(self) -> dict:
        return dict(self.__dict__)
