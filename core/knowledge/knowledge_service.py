"""
core/knowledge/knowledge_service.py — FRIDAY 4.0 (M7)
The public face of the Knowledge & Learning Core. Composes the store, vector
index, graph, validator, learning engine, coding library, documentation bridge,
consolidator, and Obsidian vault into one coherent API.

Design (per the M7 charter):
  • Local-first: every read tries local knowledge first; external is last resort.
  • Vault is the source of truth: every stored entry is also written as a note;
    the store + index are rebuildable from the vault.
  • Observability: mutating actions emit a KnowledgeEvent on the runtime bus and
    record a metric — mirroring the GoalService/ExecutiveBrain pattern.
  • Additive: integrates M3 memories and M4 reflections via promote_* adapters
    without modifying those modules.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Optional

from .coding_knowledge import CodingKnowledge
from .documentation_service import DocumentationService, Fetcher
from .knowledge_consolidator import KnowledgeConsolidator
from .knowledge_graph import KnowledgeGraph
from .knowledge_index import KnowledgeIndex
from .knowledge_models import (ConsolidationResult, KnowledgeCategory,
                               KnowledgeEntry, KnowledgeRelation, KnowledgeStatus,
                               ValidationReport, new_knowledge)
from .knowledge_store import KnowledgeStore
from .knowledge_validator import KnowledgeValidator
from .learning_engine import LearningEngine
from .vault import ObsidianVault

log = logging.getLogger("friday.knowledge.service")


class KnowledgeEvent(str, Enum):
    CREATED = "knowledge.created"
    UPDATED = "knowledge.updated"
    LEARNED = "knowledge.learned"
    CONSOLIDATED = "knowledge.consolidated"
    ARCHIVED = "knowledge.archived"
    RETRIEVED = "knowledge.retrieved"


class KnowledgeService:
    def __init__(self, store: Optional[KnowledgeStore] = None,
                 index: Optional[KnowledgeIndex] = None,
                 vault: Optional[ObsidianVault] = None,
                 fetcher: Optional[Fetcher] = None,
                 runtime=None, use_vault: bool = True) -> None:
        self._store = store if store is not None else KnowledgeStore()
        self._index = index if index is not None else KnowledgeIndex()
        self._vault = vault if vault is not None else ObsidianVault()
        self._use_vault = use_vault
        self._graph = KnowledgeGraph(self._store)
        self._validator = KnowledgeValidator(self._store)
        self._learner = LearningEngine(self._store)
        self._coding = CodingKnowledge(self._store)
        self._docs = DocumentationService(self._store, fetcher=fetcher)
        self._consolidator = KnowledgeConsolidator(self._store)
        self._runtime = runtime
        self._lock = threading.RLock()
        self._rebuild_index_from_store()

    # ── exposed collaborators ──────────────────────────────────────────────────
    @property
    def graph(self) -> KnowledgeGraph:
        return self._graph

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @property
    def coding(self) -> CodingKnowledge:
        return self._coding

    @property
    def docs(self) -> DocumentationService:
        return self._docs

    # ── write path ─────────────────────────────────────────────────────────────
    def remember_knowledge(self, title: str, content: str, *,
                           category: str = KnowledgeCategory.GENERAL,
                           confidence: float = 0.6, source: str = "system",
                           validate: bool = True,
                           metadata: Optional[dict] = None) -> KnowledgeEntry:
        """Store a piece of knowledge (validated, indexed, vaulted). If validation
        recommends 'update' against an existing duplicate, the existing entry is
        refined in place instead of creating a near-twin."""
        entry = new_knowledge(title, content, category=category,
                              confidence=confidence, source=source, metadata=metadata)
        with self._lock:
            if validate:
                report = self._validator.validate(entry)
                if report.recommendation == "reject":
                    log.debug("knowledge rejected: %s", title)
                    return entry
                if report.recommendation == "update" and report.duplicates:
                    return self._refine(report.duplicates[0], entry)
            return self._persist(entry, KnowledgeEvent.CREATED)

    def _persist(self, entry: KnowledgeEntry, event: "KnowledgeEvent") -> KnowledgeEntry:
        if self._use_vault:
            try:
                entry.vault_path = self._vault.write(entry)
            except Exception:
                log.debug("vault write failed", exc_info=True)
        self._store.create(entry)
        self._index.add(entry.id, f"{entry.title}\n{entry.content}")
        self._store.add_history(entry.id, "created", {"source": entry.source})
        self._store.record_metric("knowledge.created")
        self._emit(event, entry)
        return entry

    def _refine(self, existing_id: str, candidate: KnowledgeEntry) -> KnowledgeEntry:
        existing = self._store.get(existing_id)
        if existing is None:
            return self._persist(candidate, KnowledgeEvent.CREATED)
        # keep the stronger confidence; prefer the newer content
        existing.content = candidate.content or existing.content
        existing.confidence = max(existing.confidence, candidate.confidence)
        existing.touch()
        self._store.update(existing)
        self._index.add(existing.id, f"{existing.title}\n{existing.content}")
        if self._use_vault:
            try:
                self._vault.write(existing, force=True)
            except Exception:
                log.debug("vault write failed", exc_info=True)
        self._store.add_history(existing.id, "updated", {"refined_from": candidate.source})
        self._store.record_metric("knowledge.updated")
        self._emit(KnowledgeEvent.UPDATED, existing)
        return existing

    def update_knowledge(self, knowledge_id: str, *, content: Optional[str] = None,
                         confidence: Optional[float] = None,
                         title: Optional[str] = None) -> Optional[KnowledgeEntry]:
        with self._lock:
            entry = self._store.get(knowledge_id)
            if entry is None:
                return None
            if title is not None:
                entry.title = title
            if content is not None:
                entry.content = content
            if confidence is not None:
                entry.confidence = max(0.0, min(1.0, confidence))
            entry.touch()
            self._store.update(entry)
            self._index.add(entry.id, f"{entry.title}\n{entry.content}")
            if self._use_vault:
                try:
                    self._vault.write(entry, force=True)
                except Exception:
                    log.debug("vault write failed", exc_info=True)
            self._store.record_metric("knowledge.updated")
            self._emit(KnowledgeEvent.UPDATED, entry)
            return entry

    # ── read path (local-first) ────────────────────────────────────────────────
    def search_knowledge(self, query: str, k: int = 5,
                         semantic: bool = True) -> list[KnowledgeEntry]:
        """Local knowledge search. Semantic (vector) first, with keyword backfill."""
        results: list[KnowledgeEntry] = []
        seen: set[str] = set()
        if semantic:
            for kid, _score in self._index.search(query, k=k):
                entry = self._store.get(kid)
                if entry and entry.status == KnowledgeStatus.ACTIVE.value and kid not in seen:
                    seen.add(kid)
                    results.append(entry)
        for entry in self._store.search_text(query, limit=k):
            if entry.id not in seen:
                seen.add(entry.id)
                results.append(entry)
        for entry in results[:k]:
            self._store.touch_usage(entry.id)
        if results:
            self._emit(KnowledgeEvent.RETRIEVED, results[0])
        return results[:k]

    def answer(self, query: str, *, category: str = KnowledgeCategory.GENERAL,
               k: int = 5, allow_external: bool = False) -> dict:
        """Resolve a question. ALWAYS local first; only if local knowledge is
        insufficient AND external is explicitly allowed does it consult the
        documentation bridge (which summarises before returning a candidate)."""
        local = self.search_knowledge(query, k=k)
        if local:
            return {"source": "local", "entries": local, "candidate": None}
        if not allow_external:
            return {"source": "none", "entries": [], "candidate": None}
        return self._docs.lookup(query, category=category, k=k)

    def get(self, knowledge_id: str) -> Optional[KnowledgeEntry]:
        return self._store.get(knowledge_id)

    # ── learning / teaching ────────────────────────────────────────────────────
    def learn(self, text: str, *, title: Optional[str] = None,
              category: Optional[str] = None, confidence: float = 0.6,
              source: str = "experience") -> Optional[KnowledgeEntry]:
        """Distil a lesson from experience text and store it (validated)."""
        candidate = self._learner.extract_lesson(
            text, title=title, category=category, confidence=confidence, source=source)
        if candidate is None:
            return None
        with self._lock:
            stored = self._store_candidate(candidate, KnowledgeEvent.LEARNED)
        return stored

    def teach(self, title: str, content: str, *,
              category: str = KnowledgeCategory.GENERAL,
              confidence: float = 0.9) -> KnowledgeEntry:
        """Explicit user-taught knowledge: trusted, stored without rejection."""
        return self.remember_knowledge(
            title, content, category=category, confidence=confidence,
            source="user", validate=False)

    def promote_memory(self, memory: dict, *, confidence: float = 0.6
                       ) -> Optional[KnowledgeEntry]:
        candidate = self._learner.promote_memory(memory, confidence=confidence)
        if candidate is None:
            return None
        with self._lock:
            return self._store_candidate(candidate, KnowledgeEvent.LEARNED)

    def promote_reflection(self, reflection: dict, *, confidence: float = 0.7
                           ) -> Optional[KnowledgeEntry]:
        candidate = self._learner.promote_reflection(reflection, confidence=confidence)
        if candidate is None:
            return None
        with self._lock:
            return self._store_candidate(candidate, KnowledgeEvent.LEARNED)

    def learn_from_goal(self, reflection: dict) -> Optional[KnowledgeEntry]:
        """M4 integration hook: turn a completed goal's reflection into knowledge."""
        return self.promote_reflection(reflection)

    def _store_candidate(self, candidate: KnowledgeEntry,
                         event: "KnowledgeEvent") -> KnowledgeEntry:
        report = self._validator.validate(candidate)
        if report.recommendation == "reject":
            return candidate
        if report.recommendation == "update" and report.duplicates:
            return self._refine(report.duplicates[0], candidate)
        return self._persist(candidate, event)

    # ── relationships ──────────────────────────────────────────────────────────
    def relate(self, source_id: str, target_id: str,
               relation: str = KnowledgeRelation.RELATED.value) -> None:
        with self._lock:
            self._graph.add_relation(source_id, target_id, relation)

    def explain(self, source_id: str, target_id: str) -> str:
        return self._graph.explain(source_id, target_id)

    # ── maintenance ────────────────────────────────────────────────────────────
    def validate(self, title: str, content: str,
                 category: str = KnowledgeCategory.GENERAL) -> ValidationReport:
        return self._validator.validate(
            new_knowledge(title, content, category=category))

    def consolidate(self, category: Optional[str] = None) -> ConsolidationResult:
        with self._lock:
            result = self._consolidator.consolidate(category=category)
            for sid in result.summary_ids:
                entry = self._store.get(sid)
                if entry:
                    self._index.add(entry.id, f"{entry.title}\n{entry.content}")
                    if self._use_vault:
                        try:
                            self._vault.write(entry)
                        except Exception:
                            log.debug("vault write failed", exc_info=True)
                    self._emit(KnowledgeEvent.CONSOLIDATED, entry)
            self._store.record_metric("knowledge.consolidated", result.summaries_created)
            return result

    def archive(self, knowledge_id: str) -> None:
        with self._lock:
            entry = self._store.get(knowledge_id)
            if entry is None:
                return
            self._store.set_status(knowledge_id, KnowledgeStatus.ARCHIVED.value)
            self._index.remove(knowledge_id)
            self._store.record_metric("knowledge.archived")
            self._emit(KnowledgeEvent.ARCHIVED, entry)

    def seed_coding_patterns(self) -> list[str]:
        with self._lock:
            created = self._coding.seed()
            for kid in created:
                entry = self._store.get(kid)
                if entry:
                    self._index.add(entry.id, f"{entry.title}\n{entry.content}")
                    if self._use_vault:
                        try:
                            self._vault.write(entry)
                        except Exception:
                            log.debug("vault write failed", exc_info=True)
            return created

    # ── vault sync ─────────────────────────────────────────────────────────────
    def rebuild_from_vault(self) -> int:
        """Reconstruct the store + index from the Obsidian vault (the source of
        truth). User edits in the vault win. Returns the number of notes imported."""
        with self._lock:
            entries = self._vault.scan()
            for entry in entries:
                existing = self._store.get(entry.id)
                if existing is None:
                    self._store.create(entry)
                else:
                    self._store.update(entry)
            self._rebuild_index_from_store()
            return len(entries)

    def _rebuild_index_from_store(self) -> int:
        items = [(e.id, f"{e.title}\n{e.content}")
                 for e in self._store.all_entries(status=KnowledgeStatus.ACTIVE.value)]
        return self._index.rebuild(items)

    # ── diagnostics ────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        s = self._store.counts()
        s["index"] = self._index.health()
        s["vault"] = self._vault.health()
        return s

    def health(self) -> dict:
        return {"status": "ok", "store": self._store.health(),
                "index": self._index.health(), "vault": self._vault.health(),
                "can_fetch_external": self._docs.can_fetch}

    def attach(self, runtime, consolidate_every_s: float = 3600.0) -> None:
        """Wire into the M1 runtime: health probe + periodic consolidation."""
        self._runtime = runtime
        try:
            runtime.register_health("knowledge", self.health)
            runtime.schedule("knowledge.consolidate", self.consolidate,
                             every=consolidate_every_s)
        except Exception:
            log.debug("runtime attach partial", exc_info=True)

    # ── events ─────────────────────────────────────────────────────────────────
    def _emit(self, event: "KnowledgeEvent", entry: KnowledgeEntry) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data={
                "id": entry.id, "title": entry.title, "category": entry.category,
                "confidence": entry.confidence, "status": entry.status,
            }, source="knowledge")
        except Exception:
            log.debug("event emit failed", exc_info=True)

    def close(self) -> None:
        self._store.close()


# ── singleton ─────────────────────────────────────────────────────────────────────
_service: Optional[KnowledgeService] = None
_svc_lock = threading.Lock()


def get_knowledge_service() -> KnowledgeService:
    global _service
    with _svc_lock:
        if _service is None:
            # activate the M7 documentation bridge with the default world
            # fetcher (wikipedia; config-gated, None when disabled) — without
            # a fetcher the external-knowledge path is dead code
            try:
                from .world_fetcher import make_world_fetcher
                fetcher = make_world_fetcher()
            except Exception:  # noqa: BLE001 — offline construction must never fail
                fetcher = None
            _service = KnowledgeService(fetcher=fetcher)
    return _service
