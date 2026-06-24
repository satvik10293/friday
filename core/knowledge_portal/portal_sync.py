"""
core/knowledge_portal/portal_sync.py — FRIDAY 4.0 (M8)
Keeps the three representations of knowledge consistent:

    SQLite (data/knowledge.db)   ← source of truth
    Obsidian vault (Markdown)    ← human-readable mirror
    Portal website              ← live view (reads the API, no separate store)

The portal reads the API directly, so "website" sync is a pull, not a copy — the
only durable sync is SQLite ↔ vault, which reuses the M7 KnowledgeService methods.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("friday.portal.sync")


@dataclass
class SyncResult:
    db_to_vault: int = 0
    vault_to_db: int = 0
    ts: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class PortalSync:
    def __init__(self, knowledge_service) -> None:
        self._k = knowledge_service

    def db_to_vault(self) -> int:
        """Write every active store entry out to the vault (mirror DB → Markdown).
        Honours manual edits — the vault writer won't clobber a newer note."""
        n = 0
        for entry in self._k.store.all_entries(status="active"):
            try:
                self._k._vault.write(entry)
                n += 1
            except Exception:
                log.debug("vault write failed for %s", entry.id, exc_info=True)
        return n

    def vault_to_db(self) -> int:
        """Re-import the vault into the store + index (Markdown → DB). User edits
        in the vault win. Returns the number of notes imported."""
        return self._k.rebuild_from_vault()

    def full_sync(self, *, prefer: str = "db") -> SyncResult:
        """Reconcile both ways. `prefer` decides which side leads on conflict:
        'db' pushes the store out first, 'vault' pulls the vault in first."""
        result = SyncResult(ts=time.time())
        if prefer == "vault":
            result.vault_to_db = self.vault_to_db()
            result.db_to_vault = self.db_to_vault()
        else:
            result.db_to_vault = self.db_to_vault()
            result.vault_to_db = self.vault_to_db()
        return result

    def health(self) -> dict:
        return {"status": "ok", "store": self._k.store.counts().get("active"),
                "vault": self._k._vault.health().get("notes")}
