"""
core/society/bus.py — FRIDAY 4.0 (M11)
The agent communication bus. Every message hops through the Passive Brain
Coordinator — agent → passive_brain → agent. Direct agent-to-agent messaging is
forbidden (it would allow uncontrolled, unobservable behaviour), and the bus
rejects it.
"""

from __future__ import annotations

from typing import Optional

from .models import Message

COORDINATOR = "passive_brain"


class DirectMessageError(RuntimeError):
    """Raised when two non-coordinator agents try to talk directly."""


class AgentBus:
    def __init__(self, capacity: int = 1000) -> None:
        self._log: list[Message] = []
        self._capacity = capacity

    def relay(self, frm: str, to: str, content: Optional[dict] = None,
              kind: str = "info") -> Message:
        """The only sanctioned send path: routes frm → passive_brain → to and
        records the message. Used by the Coordinator on behalf of agents."""
        msg = Message(frm=frm, to=to, relay=COORDINATOR, kind=kind, content=content or {})
        self._append(msg)
        return msg

    def deliver_direct(self, frm: str, to: str, content: Optional[dict] = None) -> Message:
        """Attempt a direct agent→agent send. Allowed ONLY if one endpoint is the
        coordinator; otherwise rejected. This is what enforces the no-mesh rule."""
        if frm != COORDINATOR and to != COORDINATOR:
            raise DirectMessageError(
                f"direct agent→agent messaging forbidden ({frm} → {to}); route via {COORDINATOR}")
        msg = Message(frm=frm, to=to, relay="", kind="direct", content=content or {})
        self._append(msg)
        return msg

    def _append(self, msg: Message) -> None:
        self._log.append(msg)
        if len(self._log) > self._capacity:
            self._log = self._log[-self._capacity:]

    def history(self, limit: int = 100) -> list[dict]:
        return [m.to_dict() for m in self._log[-limit:]]

    def __len__(self) -> int:
        return len(self._log)
