"""
core/user_model/ — FRIDAY 4.0 (M9) Personal Model & User Intelligence System.

Turns FRIDAY from a generic assistant into a personalized companion that
understands its primary user: profile, preferences, habits, interests, projects,
communication & learning style, and approved long-term context — all stored
locally (`data/user_model.db`) and owned by the user. Privacy-first: no cloud, no
telemetry, no external sharing.

Side-effect-free to import: constructing `UserModelService` (or calling
`get_user_model_service()`) is what opens the database.
"""

from __future__ import annotations

from .dashboard import UserDashboard
from .models import (CommunicationAspect, Evidence, Habit, Interest, InterestLink,
                     LearningStyleType, Preference, PreferenceCategory, Project,
                     ProjectStatus, RelationshipFact, UserContextPackage, UserProfile)
from .personal_intelligence import PersonalIntelligence, Recommendation
from .service import UserModelService, get_user_model_service
from .store import UserModelEvent, UserModelStore
from .user_context import UserContextBuilder

__all__ = [
    "UserModelService", "get_user_model_service", "UserModelStore", "UserModelEvent",
    "UserProfile", "Preference", "PreferenceCategory", "Habit", "Interest",
    "InterestLink", "Project", "ProjectStatus", "RelationshipFact",
    "CommunicationAspect", "LearningStyleType", "Evidence", "UserContextPackage",
    "PersonalIntelligence", "Recommendation", "UserContextBuilder", "UserDashboard",
]
