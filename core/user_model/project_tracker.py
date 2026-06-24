"""
core/user_model/project_tracker.py — FRIDAY 4.0 (M9)
Understands the user's projects: which are active, completed, or paused, and for
each — its goals, milestones, and the knowledge/memories that relate to it. This
is the spine that lets FRIDAY say "for your FRIDAY 4.0 project, here's what's
relevant" instead of treating every request in a vacuum.

Integrates outward (additively): project goals can reference M4 goal ids,
knowledge_ids reference M7/M8 knowledge, memory_ids reference M2 memories.
"""

from __future__ import annotations

from typing import Optional

from .models import Project, ProjectStatus, now
from .store import UserModelEvent, UserModelStore


class ProjectTracker:
    def __init__(self, store: UserModelStore, emit=None) -> None:
        self._store = store
        self._emit = emit

    def add_project(self, name: str, *, description: str = "",
                    status: str = ProjectStatus.ACTIVE.value,
                    goals: Optional[list] = None) -> Project:
        existing = self._store.find_project_by_name(name)
        if existing is not None:
            return existing
        project = Project(name=name.strip(), description=description, status=status,
                          goals=list(goals or []))
        self._store.save_project(project)
        self._event(project, "created")
        return project

    def get(self, project_id: str) -> Optional[Project]:
        return self._store.get_project(project_id)

    def find(self, name: str) -> Optional[Project]:
        return self._store.find_project_by_name(name)

    def list(self, status: Optional[str] = None) -> list[Project]:
        return self._store.list_projects(status=status)

    def active(self) -> list[Project]:
        return self._store.list_projects(status=ProjectStatus.ACTIVE.value)

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def set_status(self, project_id: str, status: str) -> Optional[Project]:
        project = self._store.get_project(project_id)
        if project is None:
            return None
        project.status = status
        return self._save(project, "status")

    def complete(self, project_id: str) -> Optional[Project]:
        return self.set_status(project_id, ProjectStatus.COMPLETED.value)

    def pause(self, project_id: str) -> Optional[Project]:
        return self.set_status(project_id, ProjectStatus.PAUSED.value)

    def resume(self, project_id: str) -> Optional[Project]:
        return self.set_status(project_id, ProjectStatus.ACTIVE.value)

    # ── enrichment ─────────────────────────────────────────────────────────────
    def add_milestone(self, project_id: str, title: str, done: bool = False
                      ) -> Optional[Project]:
        project = self._store.get_project(project_id)
        if project is None:
            return None
        project.milestones.append({"title": title, "done": done})
        return self._save(project, "milestone")

    def complete_milestone(self, project_id: str, title: str) -> Optional[Project]:
        project = self._store.get_project(project_id)
        if project is None:
            return None
        for m in project.milestones:
            if m.get("title") == title:
                m["done"] = True
        return self._save(project, "milestone")

    def link_goal(self, project_id: str, goal_id: str) -> Optional[Project]:
        return self._append(project_id, "goals", goal_id)

    def link_knowledge(self, project_id: str, knowledge_id: str) -> Optional[Project]:
        return self._append(project_id, "knowledge_ids", knowledge_id)

    def link_memory(self, project_id: str, memory_id) -> Optional[Project]:
        return self._append(project_id, "memory_ids", memory_id)

    def progress(self, project_id: str) -> float:
        """Fraction of milestones completed (0..1)."""
        project = self._store.get_project(project_id)
        if not project or not project.milestones:
            return 0.0
        done = sum(1 for m in project.milestones if m.get("done"))
        return done / len(project.milestones)

    # ── internals ──────────────────────────────────────────────────────────────
    def _append(self, project_id: str, field: str, value) -> Optional[Project]:
        project = self._store.get_project(project_id)
        if project is None:
            return None
        lst = getattr(project, field)
        if value not in lst:
            lst.append(value)
        return self._save(project, field)

    def _save(self, project: Project, what: str) -> Project:
        project.updated_at = now()
        self._store.save_project(project)
        self._event(project, what)
        return project

    def _event(self, project: Project, what: str) -> None:
        self._store.add_event(UserModelEvent.PROJECT_UPDATED.value,
                              {"id": project.id, "name": project.name,
                               "status": project.status, "change": what})
        self._store.record_metric("user.project.updated")
        if self._emit:
            self._emit(UserModelEvent.PROJECT_UPDATED,
                       {"id": project.id, "name": project.name, "status": project.status})
