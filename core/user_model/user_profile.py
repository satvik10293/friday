"""
core/user_model/user_profile.py — FRIDAY 4.0 (M9)
The persistent user identity. ProfileManager owns the single UserProfile row, with
update / merge semantics and a full version history so the profile's evolution is
auditable and reversible. Local-only; the user owns this data.
"""

from __future__ import annotations

from typing import Optional

from .models import UserProfile, now
from .store import UserModelEvent, UserModelStore

# Fields that are lists and should be *merged* (union, order-preserving) rather
# than overwritten when merging profile updates.
_LIST_FIELDS = ("interests", "skills", "projects", "long_term_goals", "short_term_goals")
_SCALAR_FIELDS = ("name", "preferred_name", "education")


class ProfileManager:
    def __init__(self, store: UserModelStore, emit=None) -> None:
        self._store = store
        self._emit = emit

    def get(self) -> UserProfile:
        """Return the profile, creating an empty one on first access."""
        profile = self._store.get_profile()
        if profile is None:
            profile = UserProfile()
            self._store.save_profile(profile)
        return profile

    def exists(self) -> bool:
        return self._store.get_profile() is not None

    def update(self, **fields) -> UserProfile:
        """Overwrite the given fields (scalars replace, lists replace)."""
        profile = self.get()
        for key, value in fields.items():
            if hasattr(profile, key) and key not in ("version", "created_at"):
                setattr(profile, key, value)
        return self._commit(profile)

    def merge(self, **fields) -> UserProfile:
        """Non-destructive merge: scalars fill only if empty; list fields union."""
        profile = self.get()
        for key, value in fields.items():
            if key in _SCALAR_FIELDS:
                if not getattr(profile, key) and value:
                    setattr(profile, key, value)
            elif key in _LIST_FIELDS and value:
                merged = list(getattr(profile, key))
                for item in (value if isinstance(value, (list, tuple)) else [value]):
                    if item not in merged:
                        merged.append(item)
                setattr(profile, key, merged)
            elif key == "metadata" and isinstance(value, dict):
                profile.metadata.update(value)
        return self._commit(profile)

    def add_to(self, field: str, *values) -> UserProfile:
        """Append unique values to a list field (interests, skills, goals…)."""
        if field not in _LIST_FIELDS:
            raise ValueError(f"{field} is not a list field")
        profile = self.get()
        current = list(getattr(profile, field))
        for v in values:
            if v not in current:
                current.append(v)
        setattr(profile, field, current)
        return self._commit(profile)

    def history(self, limit: int = 50) -> list[dict]:
        return self._store.profile_history(limit=limit)

    def revert(self, version: int) -> Optional[UserProfile]:
        """Restore a past profile version (itself recorded as a new version)."""
        for record in self._store.profile_history(limit=1000):
            if record["version"] == version:
                restored = UserProfile.from_dict(record["snapshot"])
                restored.version = self.get().version  # continue the version line
                return self._commit(restored)
        return None

    # ── internals ──────────────────────────────────────────────────────────────
    def _commit(self, profile: UserProfile) -> UserProfile:
        # snapshot the prior state, then bump + save
        prior = self._store.get_profile()
        if prior is not None:
            self._store.add_profile_history(prior.version, prior.to_dict())
        profile.version = (prior.version + 1) if prior is not None else 1
        profile.updated_at = now()
        self._store.save_profile(profile)
        self._store.add_event(UserModelEvent.PROFILE_UPDATED.value,
                              {"version": profile.version})
        self._store.record_metric("user.profile.updated")
        if self._emit:
            self._emit(UserModelEvent.PROFILE_UPDATED, {"version": profile.version})
        return profile
