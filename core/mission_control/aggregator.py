"""
core/mission_control/aggregator.py — FRIDAY 4.0 (M10)
Assembles the cockpit's panel payloads from FRIDAY's live subsystems. Every panel
is built through `safe_call`, so a failing subsystem degrades to a marker instead
of breaking the whole view (Part 7 resilience).

Panels: cognitive_state · goal_network (3D) · knowledge_space (3D galaxy) ·
agent_team (3D, M11-ready) · resource_monitor · security_center · event_stream.
"""

from __future__ import annotations

from typing import Optional

from .resilience import is_degraded, safe_call


class MissionControlAggregator:
    def __init__(self, *, executive=None, goal_service=None, knowledge_service=None,
                 user_model=None, agent_runtime=None, authenticator=None,
                 resources=None, events=None, vision=None) -> None:
        self.executive = executive
        self.goals = goal_service
        self.knowledge = knowledge_service
        self.user_model = user_model
        self.agent_runtime = agent_runtime
        self.auth = authenticator
        self.resources = resources
        self.events = events
        self.vision = vision               # M14: VisionSystem (optional, additive)

    # ── 3D panels ───────────────────────────────────────────────────────────────
    def cognitive_state(self) -> dict:
        def build():
            if self.executive is None:
                return {"status": "absent", "brain": "offline"}
            status = self.executive.status() if hasattr(self.executive, "status") else {}
            health = self.executive.health() if hasattr(self.executive, "health") else {}
            return {
                "status": "ok",
                "current_focus": status.get("focus") or status.get("current_focus"),
                "active_plan": status.get("plan") or status.get("active_plan"),
                "current_goal": status.get("goal") or status.get("current_goal"),
                "confidence": status.get("confidence", 0.0),
                "active_context": status.get("context") or status.get("active_context"),
                "brain_status": health.get("status", "ok"),
                "raw": {"status": status, "health": health},
            }
        return safe_call("cognitive_state", build)

    def goal_network(self) -> dict:
        def build():
            if self.goals is None:
                return {"status": "absent", "nodes": [], "edges": []}
            from core.goals import GoalStatus
            goals = self.goals.list_goals()
            nodes, edges = [], []
            active = blocked = 0
            for g in goals:
                st = g.status.value if hasattr(g.status, "value") else str(g.status)
                if st == "active":
                    active += 1
                elif st == "blocked":
                    blocked += 1
                nodes.append({"id": g.goal_id, "label": g.title, "status": st,
                              "priority": g.priority,
                              "progress": getattr(g, "completion_percent", 0.0)})
                for dep in getattr(g, "dependencies", []) or []:
                    edges.append({"source": g.goal_id, "target": dep, "relation": "depends_on"})
                if getattr(g, "parent_goal", None):
                    edges.append({"source": g.parent_goal, "target": g.goal_id,
                                  "relation": "subgoal"})
            return {"status": "ok", "total": len(goals), "active": active,
                    "blocked": blocked, "nodes": nodes, "edges": edges, "render": "3d"}
        return safe_call("goal_network", build)

    def knowledge_space(self) -> dict:
        def build():
            if self.knowledge is None:
                return {"status": "absent", "nodes": [], "edges": []}
            from core.knowledge_portal.portal_graph import build_graph
            graph = build_graph(self.knowledge.store)
            stats = self.knowledge.stats() if hasattr(self.knowledge, "stats") else {}
            return {"status": "ok", "render": "3d", "galaxy": True,
                    "nodes": graph["nodes"], "edges": graph["edges"],
                    "concepts": graph["stats"]["nodes"],
                    "relationships": graph["stats"]["edges"],
                    "growth": stats.get("total", 0),
                    "by_category": stats.get("by_category", {})}
        return safe_call("knowledge_space", build)

    def agent_team(self) -> dict:
        # M11-ready: today it reports the process runtime's lifecycle metrics; the
        # team/sub-agent topology fills in when agent teams land.
        def build():
            metrics = {}
            if self.agent_runtime is not None and hasattr(self.agent_runtime, "snapshot"):
                metrics = self.agent_runtime.snapshot()
            return {"status": "ready", "render": "3d", "leaders": [], "sub_agents": [],
                    "events": [], "runtime_metrics": metrics, "future": "M11"}
        return safe_call("agent_team", build)

    def vision_panel(self) -> dict:
        # M14: the Vision System cockpit panel — connected cameras, FPS/latency/queue,
        # object count, detection rate, processing time, thread status, errors/warnings.
        def build():
            if self.vision is None:
                return {"status": "absent", "cameras": []}
            from core.vision.mission_control import VisionPanel
            return VisionPanel(self.vision).panel()
        return safe_call("vision_panel", build)

    # ── 2D overlays ─────────────────────────────────────────────────────────────
    def resource_monitor(self) -> dict:
        def build():
            if self.resources is None:
                return {"status": "absent"}
            return {"status": "ok", **self.resources.snapshot()}
        return safe_call("resource_monitor", build)

    def security_center(self) -> dict:
        def build():
            if self.auth is None:
                return {"status": "absent", "recent": [], "failures": []}
            recent = self.auth.audit.recent(limit=30)
            failures = self.auth.audit.failures(limit=30)
            return {"status": "ok", "recent": recent, "failures": failures,
                    "failed_access_attempts": len(failures),
                    "tokens": len(self.auth.tokens.list())}
        return safe_call("security_center", build)

    def event_stream(self) -> dict:
        def build():
            if self.events is None:
                return {"status": "absent", "events": [], "alerts": []}
            return {"status": "ok", "events": self.events.recent(100),
                    "alerts": self.events.alerts(50)}
        return safe_call("event_stream", build)

    # ── full state ──────────────────────────────────────────────────────────────
    def panels(self) -> dict:
        return {
            "cognitive_state": self.cognitive_state(),
            "goal_network": self.goal_network(),
            "knowledge_space": self.knowledge_space(),
            "agent_team": self.agent_team(),
            "vision": self.vision_panel(),
            "resource_monitor": self.resource_monitor(),
            "security_center": self.security_center(),
            "event_stream": self.event_stream(),
        }

    def state(self) -> dict:
        panels = {}
        degraded = []
        for name, value in self.panels().items():
            payload = value.to_dict() if hasattr(value, "to_dict") else value
            panels[name] = payload
            if is_degraded(payload) or payload.get("status") in ("absent",):
                if is_degraded(payload):
                    degraded.append(name)
        return {"ok": True, "panels": panels, "degraded": degraded,
                "operational": True}

    def health(self) -> dict:
        st = self.state()
        return {"status": "ok" if not st["degraded"] else "degraded",
                "degraded": st["degraded"], "operational": True}
