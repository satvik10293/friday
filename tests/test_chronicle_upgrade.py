"""
tests/test_chronicle_upgrade.py — M32.2 base perfection.

Pins the Chronicle repairs: per-thread connections (the old single shared
connection raced across the FAISS indexer / sovereign daemon / Flask job
threads), the durable memories.embed_id link, and side-list recovery from the
DB after a crash. Plus Sovereign's concepts_learned accounting.
"""

import threading

import pytest

import core.knowledge.friday_chronicle as chronicle
import core.knowledge.friday_sovereign as sovereign


@pytest.fixture
def fresh_chronicle(tmp_path, monkeypatch):
    """Point chronicle at a scratch DB with clean module state."""
    monkeypatch.setattr(chronicle, "_DB_PATH", tmp_path / "chronicle.db")
    monkeypatch.setattr(chronicle, "_FAISS_PATH", tmp_path / "chronicle.faiss")
    monkeypatch.setattr(chronicle, "_EMBED_PATH", tmp_path / "chronicle.embeddings.npy")
    monkeypatch.setattr(chronicle, "_local", threading.local())
    monkeypatch.setattr(chronicle, "_schema_ready", False)
    monkeypatch.setattr(chronicle, "_faiss_index", None)
    monkeypatch.setattr(chronicle, "_embed_ids", [])
    monkeypatch.setattr(chronicle, "_current_session", None)
    return chronicle


@pytest.fixture
def fake_embedder(fresh_chronicle, monkeypatch):
    """Deterministic tiny embedder so tests never load a real model."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("faiss")

    def _fake_embed(text):
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        return rng.random(384, dtype=np.float32)

    monkeypatch.setattr(chronicle, "_load_embedder", lambda: True)
    monkeypatch.setattr(chronicle, "_embed", _fake_embed)
    return chronicle


def test_concurrent_writes_from_many_threads(fresh_chronicle, monkeypatch):
    """The 3.0 defect: one shared connection, lock never acquired."""
    monkeypatch.setattr(chronicle, "_load_embedder", lambda: False)  # DB only
    errors = []

    def writer(n):
        try:
            for i in range(10):
                chronicle.save_turn("user", f"turn {n}-{i}", topic="load")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writes failed: {errors[:3]}"
    assert chronicle.stats()["total_memories"] == 40


def test_embed_id_written_to_row(fake_embedder):
    """memories.embed_id was in the schema but never written — now it is."""
    m1 = chronicle.save_turn("user", "alpha content one")
    m2 = chronicle.save_turn("friday", "beta content two")

    rows = {r["id"]: r["embed_id"] for r in chronicle.search_keyword("content")}
    assert rows[m1] == 0
    assert rows[m2] == 1


def test_side_list_recovers_from_db_after_crash(fake_embedder):
    """Crash between FAISS insert and .npy save must not desync recall."""
    ids = [chronicle.save_turn("user", f"memory number {i}") for i in range(3)]
    chronicle.flush()                       # index on disk
    chronicle._EMBED_PATH.unlink()          # simulate the stale/lost side list

    # Fresh process: module reloads the index with no .npy
    chronicle._faiss_index = None
    chronicle._embed_ids = []
    assert chronicle._load_faiss()

    assert chronicle._embed_ids == ids, \
        "side list not recovered from memories.embed_id"


def test_neural_search_after_recovery(fake_embedder):
    ids = [chronicle.save_turn("user", f"unique topic {i}") for i in range(5)]
    chronicle.flush()
    chronicle._EMBED_PATH.unlink()
    chronicle._faiss_index = None
    chronicle._embed_ids = []

    results = chronicle.search_neural("unique topic 2", limit=3)
    assert results, "neural search returned nothing after recovery"
    assert all(r["id"] in ids for r in results)


def test_sovereign_counts_concepts(fresh_chronicle, monkeypatch, tmp_path):
    """concepts_learned was declared, saved, and never incremented."""
    monkeypatch.setattr(sovereign, "_STATS_PATH", tmp_path / "sovereign_stats.json")
    monkeypatch.setattr(sovereign, "_stats", sovereign.SovereignStats())
    monkeypatch.setattr(sovereign, "_domains", {})
    monkeypatch.setattr(chronicle, "_load_embedder", lambda: False)

    summary = sovereign.extract_and_store(
        user_input="What is FAISS?",
        friday_response='FAISS is a library for efficient similarity search of dense vectors. '
                        'Use `IndexFlatL2` for exact search. "Approximate search" scales further.',
        intent="question",
        used_api=True,
    )

    assert summary["concepts"] > 0
    assert sovereign._stats.concepts_learned == summary["concepts"]


def test_sovereign_used_api_signal_moves_independence(monkeypatch, tmp_path):
    """self_answered increments when used_api=False — the metric can move."""
    monkeypatch.setattr(sovereign, "_STATS_PATH", tmp_path / "sovereign_stats.json")
    monkeypatch.setattr(sovereign, "_stats", sovereign.SovereignStats())
    monkeypatch.setattr(sovereign, "_domains", {})
    monkeypatch.setattr(sovereign, "_persist_facts", lambda *a, **k: None)
    monkeypatch.setattr(sovereign, "_persist_concepts", lambda *a, **k: None)

    sovereign.extract_and_store("q1", "local answer body here.", "chat", used_api=False)
    sovereign.extract_and_store("q2", "cloud answer body here.", "chat", used_api=True)

    assert sovereign._stats.self_answered == 1
    assert sovereign._stats.api_answered == 1
    assert sovereign._stats.independence_pct == 50
