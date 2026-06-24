"""
Tests for core/memory/migrate.py — idempotent import from legacy chronicle.db.
Builds a tiny fake legacy DB so no real data is required.
"""

import sqlite3

import pytest

from core.memory import MemoryService, MemoryStore, HashingEmbedder, NumpyFlatIndex
from core.memory import migrate_from_chronicle


def _make_legacy_chronicle(path):
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, type TEXT, role TEXT, content TEXT, topic TEXT,
            timestamp REAL, session_id TEXT, importance REAL, metadata TEXT, embed_id INTEGER
        );
        CREATE TABLE facts (
            id INTEGER PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT,
            source TEXT, confidence REAL, timestamp REAL, metadata TEXT
        );
        CREATE TABLE preferences (
            id INTEGER PRIMARY KEY, category TEXT, key TEXT, value TEXT,
            weight REAL, updated_at REAL
        );
        """
    )
    con.execute("INSERT INTO memories (type,role,content,topic,timestamp,session_id,importance,metadata) "
                "VALUES ('conversation','user','I am building Friday',' friday',123.0,'s1',0.9,'{}')")
    con.execute("INSERT INTO facts (subject,predicate,object,source,confidence,timestamp,metadata) "
                "VALUES ('Friday','runs_on','Windows','test',0.9,123.0,'{}')")
    con.execute("INSERT INTO preferences (category,key,value,weight,updated_at) "
                "VALUES ('ui','theme','dark',1.0,123.0)")
    con.commit()
    con.close()


@pytest.fixture
def service(tmp_path):
    emb = HashingEmbedder()
    store = MemoryStore(path=tmp_path / "mem.db")
    svc = MemoryService(store=store, index=NumpyFlatIndex(emb.dim), embedder=emb)
    yield svc
    store.close()


def test_migrate_imports_all_kinds(tmp_path, service):
    legacy = tmp_path / "chronicle.db"
    _make_legacy_chronicle(legacy)
    res = migrate_from_chronicle(service, legacy)
    assert res["status"] == "ok"
    assert res["memories"] == 1
    assert res["facts"] == 1
    assert res["preferences"] == 1
    # migrated content is embedded + recallable in the new store
    assert any("Friday" in h["content"] for h in service.recall("building Friday", k=5))


def test_migrate_is_idempotent(tmp_path, service):
    legacy = tmp_path / "chronicle.db"
    _make_legacy_chronicle(legacy)
    first = migrate_from_chronicle(service, legacy)
    assert first["status"] == "ok"
    second = migrate_from_chronicle(service, legacy)
    assert second["status"] == "already-imported"
    # no duplicate rows
    assert service.stats()["total"] == 3


def test_migrate_no_source(tmp_path, service):
    res = migrate_from_chronicle(service, tmp_path / "does_not_exist.db")
    assert res["status"] == "no-source"
