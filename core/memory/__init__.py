"""
core/memory — FRIDAY 4.0 memory layer.

The Memory Service: SQLite source of truth + rebuildable vector index + tiered
working/episodic/semantic/archival memory. Import is side-effect free.

    from core.memory import get_memory_service
    mem = get_memory_service()
    mid = mem.remember("user", "I'm building Friday")
    hits = mem.recall("what am I building?")
"""

from .store import MemoryStore, TIERS
from .embedder import Embedder, HashingEmbedder, MiniLMEmbedder, get_embedder
from .index import VectorIndex, NumpyFlatIndex, FaissHNSWIndex, build_index
from .working import WorkingMemory
from .service import MemoryService, get_memory_service
from .migrate import migrate_all, migrate_from_chronicle, migrate_local_qa, migrate_vault

__all__ = [
    "MemoryStore", "TIERS",
    "Embedder", "HashingEmbedder", "MiniLMEmbedder", "get_embedder",
    "VectorIndex", "NumpyFlatIndex", "FaissHNSWIndex", "build_index",
    "WorkingMemory",
    "MemoryService", "get_memory_service",
    "migrate_all", "migrate_from_chronicle", "migrate_local_qa", "migrate_vault",
]
