"""
M22 — One Memory (Phase C exit criteria, docs/FRIDAY_5X_ROADMAP.md).

Legacy stores (chronicle.db, local_qa.json, vault) migrate once into the M2
MemoryService and are only ever read; the boot wires the real service; every
voice turn recalls before reasoning (provenance in the DecisionLog) and the
conversation itself becomes episodic memory.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.memory import (HashingEmbedder, MemoryService, MemoryStore,
                         migrate_all, migrate_local_qa, migrate_vault)


@pytest.fixture
def service(tmp_path):
    return MemoryService(store=MemoryStore(tmp_path / "mem.db"),
                         embedder=HashingEmbedder())


def _make_chronicle(path):
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE memories (id INTEGER PRIMARY KEY, type TEXT, role TEXT,
            content TEXT, topic TEXT, timestamp REAL, session_id TEXT,
            importance REAL, metadata TEXT, embed_id INTEGER);
        CREATE TABLE facts (id INTEGER PRIMARY KEY, subject TEXT, predicate TEXT,
            object TEXT, source TEXT, confidence REAL, timestamp REAL, metadata TEXT);
        INSERT INTO memories (type, role, content, topic, timestamp, session_id, importance)
            VALUES ('conversation', 'user', 'I prefer Python', 'coding', 1.0, 's1', 0.8);
        INSERT INTO facts (subject, predicate, object, confidence)
            VALUES ('Satvik', 'builds', 'FRIDAY', 0.9);
    """)
    con.commit()
    con.close()
    return path


def test_migrate_all_imports_every_source_once(service, tmp_path):
    chronicle = _make_chronicle(tmp_path / "chronicle.db")
    qa = tmp_path / "local_qa.json"
    qa.write_text(json.dumps([{"question": "what is FRIDAY?",
                               "answer": "a local cognitive system"}]),
                  encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("FRIDAY runs fully locally.", encoding="utf-8")

    report = migrate_all(service, chronicle_path=chronicle, qa_path=qa,
                         vault_dir=vault)
    assert report["chronicle"]["status"] == "ok"
    assert report["local_qa"] == {"status": "ok", "qa_pairs": 1}
    assert report["vault"] == {"status": "ok", "notes": 1}

    # second run is a no-op (idempotent — legacy stores are never re-imported)
    again = migrate_all(service, chronicle_path=chronicle, qa_path=qa,
                        vault_dir=vault)
    assert all(again[k]["status"] == "already-imported"
               for k in ("chronicle", "local_qa", "vault"))


def test_migrated_knowledge_is_recallable(service, tmp_path):
    qa = tmp_path / "local_qa.json"
    qa.write_text(json.dumps([{"question": "favourite language",
                               "answer": "Satvik prefers Python for everything"}]),
                  encoding="utf-8")
    migrate_local_qa(service, qa)
    hits = service.recall("prefers Python")
    assert hits and "Python" in hits[0]["content"]


def test_migration_never_touches_the_source(service, tmp_path):
    chronicle = _make_chronicle(tmp_path / "chronicle.db")
    before = chronicle.read_bytes()
    migrate_all(service, chronicle_path=chronicle,
                qa_path=tmp_path / "missing.json", vault_dir=tmp_path / "missing")
    assert chronicle.read_bytes() == before


def test_missing_sources_are_reported_not_fatal(service, tmp_path):
    report = migrate_all(service, chronicle_path=tmp_path / "nope.db",
                         qa_path=tmp_path / "nope.json",
                         vault_dir=tmp_path / "nope")
    assert all(report[k]["status"] == "no-source"
               for k in ("chronicle", "local_qa", "vault"))


# ── boot wiring ───────────────────────────────────────────────────────────────

def test_boot_exposes_the_memory_service():
    from core.launcher.startup import StartupSequence
    report = StartupSequence(headless=True, start_runtime=False).run()
    assert report.components.get("memory_service") is not None
    by_stage = {s.stage: s for s in report.stages}
    assert by_stage["memory"].status == "ok"


# ── memory in the conversation loop ───────────────────────────────────────────

class _Response:
    task = "general"
    strategy = "direct"
    ok = True
    answer = "the answer"
    confidence = 0.9
    models_used = ["friday-reasoner"]
    structured: dict = {}
    trace_id = "t-1"


class _IOS:
    def think(self, prompt, context=None, **kw):
        return _Response()


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


def test_voice_turns_recall_before_reasoning_and_become_memory(service):
    service.remember("system", "Satvik prefers Python", kind="fact",
                     tier="semantic")
    bridge = ConversationBridge(
        _IOS(), decision_log=_Log(), memory=service,
        speech=_SpeechOutput(synthesizer=lambda t: None))
    bridge.think("do I prefer Python?")

    row = bridge._decision_log.rows[0]
    assert row["memory_used"], "recall provenance missing from the DecisionLog"

    hits = service.recall("do I prefer Python?")
    contents = " ".join(h["content"] for h in hits)
    assert "the answer" in contents or any(
        h["kind"] == "conversation" for h in hits), \
        "the turn was not remembered"
