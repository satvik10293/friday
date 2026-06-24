"""
core/user_model/relationship_memory.py — FRIDAY 4.0 (M9)
Long-term, user-approved context — the handful of facts FRIDAY should always keep
in mind about her user (important projects, long-term goals, major decisions).

Privacy gate (strict): nothing here becomes active context until the user has
*approved* it, and anything flagged sensitive is never stored automatically. A
proposal sits inactive until `approve()` is called.
"""

from __future__ import annotations

from typing import Optional

from .models import RelationshipFact
from .store import UserModelStore


class RelationshipMemory:
    def __init__(self, store: UserModelStore, emit=None) -> None:
        self._store = store
        self._emit = emit

    def propose(self, content: str, *, kind: str = "context",
                sensitive: bool = False) -> RelationshipFact:
        """Suggest a long-term fact. Stored UNAPPROVED (inactive) until the user
        approves it. Sensitive proposals are flagged and still require approval."""
        fact = RelationshipFact(kind=kind, content=content.strip(),
                                approved=False, sensitive=sensitive)
        self._store.save_relationship_fact(fact)
        return fact

    def remember(self, content: str, *, kind: str = "context") -> RelationshipFact:
        """User explicitly tells FRIDAY to remember this → approved immediately.
        Never use for sensitive data inferred without consent."""
        fact = RelationshipFact(kind=kind, content=content.strip(), approved=True)
        self._store.save_relationship_fact(fact)
        return fact

    def approve(self, fact_id: str) -> Optional[RelationshipFact]:
        fact = self._store.get_relationship_fact(fact_id)
        if fact is None:
            return None
        fact.approved = True
        self._store.save_relationship_fact(fact)
        return fact

    def reject(self, fact_id: str) -> bool:
        """Decline a proposal — it stays inactive (kept for an audit trail)."""
        fact = self._store.get_relationship_fact(fact_id)
        if fact is None:
            return False
        fact.approved = False
        self._store.save_relationship_fact(fact)
        return True

    def get(self, fact_id: str) -> Optional[RelationshipFact]:
        return self._store.get_relationship_fact(fact_id)

    def active(self) -> list[RelationshipFact]:
        """Only approved facts are ever surfaced as context."""
        return self._store.list_relationship_facts(approved_only=True)

    def pending(self) -> list[RelationshipFact]:
        return [f for f in self._store.list_relationship_facts() if not f.approved]

    def all(self) -> list[RelationshipFact]:
        return self._store.list_relationship_facts()
