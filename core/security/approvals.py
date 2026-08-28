"""
core/security/approvals.py — FRIDAY 4.0
Human-in-the-loop approval workflow. The executor calls request_and_wait() for any
restricted skill; the request blocks (on a threading.Event) until approved/rejected
by a UI/CLI (approve()/reject()) or auto-decided by an injected decider, or it times
out. Built thread-safe and UI-ready (Mission Control will surface list_pending()).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.skills.exceptions import ApprovalTimeout

log = logging.getLogger("friday.security.approvals")


@dataclass
class ApprovalRequest:
    id: str
    skill_name: str
    args: dict
    role: str
    caller: str
    trace_id: Optional[str]
    created_at: float
    status: str = "pending"          # pending | approved | rejected
    reason: str = ""
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def snapshot(self) -> dict:
        return {
            "id": self.id, "skill_name": self.skill_name, "args": self.args,
            "role": self.role, "caller": self.caller, "trace_id": self.trace_id,
            "created_at": self.created_at, "status": self.status, "reason": self.reason,
        }


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str = ""


# auto_decider(request) -> True (approve) | False (reject) | None (wait for human)
AutoDecider = Callable[[ApprovalRequest], Optional[bool]]


class ApprovalManager:
    def __init__(self, default_timeout: float = 30.0,
                 auto_decider: Optional[AutoDecider] = None) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._timeout = default_timeout
        self._auto = auto_decider

    def request_and_wait(self, skill, args: dict, context) -> ApprovalDecision:
        role = getattr(context.user_role, "value", str(context.user_role))
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:12],
            skill_name=getattr(skill, "name", str(skill)),
            args=dict(args),
            role=role,
            caller=getattr(context, "caller", "system"),
            trace_id=getattr(context, "trace_id", None),
            created_at=time.time(),
        )
        with self._lock:
            self._pending[req.id] = req

        if self._auto is not None:
            decision = self._auto(req)
            if decision is True:
                self._resolve(req.id, "approved", "auto-approved")
            elif decision is False:
                self._resolve(req.id, "rejected", "auto-rejected")

        if req.status == "pending":
            if not req._event.wait(self._timeout):
                with self._lock:
                    self._pending.pop(req.id, None)
                raise ApprovalTimeout(f"approval timed out for '{req.skill_name}'")

        with self._lock:
            self._pending.pop(req.id, None)
        return ApprovalDecision(req.status == "approved", req.reason)

    def _resolve(self, request_id: str, status: str, reason: str = "") -> None:
        with self._lock:
            req = self._pending.get(request_id)
        if req is not None:
            req.status = status
            req.reason = reason
            req._event.set()
            log.info("approval %s -> %s (%s)", request_id, status, reason)

    def approve(self, request_id: str, by: str = "user") -> None:
        self._resolve(request_id, "approved", f"approved by {by}")

    def reject(self, request_id: str, reason: str = "rejected") -> None:
        self._resolve(request_id, "rejected", reason)

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [r.snapshot() for r in self._pending.values()]
