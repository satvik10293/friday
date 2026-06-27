"""M13 — World Model v2 migration (additive stable_id column, rollback-safe)."""

import sqlite3

import pytest

from core.cognition_core.migration import (upgrade_world_model, world_migration_runner)


def _make_world_v1(path):
    """Reproduce M5's world.db v1 baseline (entities + schema_version=1)."""
    c = sqlite3.connect(str(path))
    c.executescript(
        """CREATE TABLE entities (entity_id TEXT PRIMARY KEY, kind TEXT, name TEXT,
              state TEXT, attributes TEXT, confidence REAL, created_at REAL, updated_at REAL);
           CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at REAL);
           INSERT INTO schema_version VALUES (1, 0.0);
           INSERT INTO entities VALUES ('user:satvik','user','satvik','{}','{}',1.0,0.0,0.0);""")
    c.commit(); c.close()


def test_status_pending(tmp_path):
    db = tmp_path / "world.db"; _make_world_v1(db)
    runner = world_migration_runner(db, backup_dir=tmp_path / "bak")
    s = runner.status()
    assert s["current"] == 1 and s["latest"] == 2 and s["pending"] == [2]


def test_upgrade_adds_stable_id(tmp_path):
    db = tmp_path / "world.db"; _make_world_v1(db)
    res = upgrade_world_model(db, backup_dir=tmp_path / "bak")
    assert res.ok and res.to_version == 2
    c = sqlite3.connect(str(db))
    cols = [r[1] for r in c.execute("PRAGMA table_info(entities)")]
    c.close()
    assert "stable_id" in cols                       # additive column present


def test_existing_rows_preserved(tmp_path):
    db = tmp_path / "world.db"; _make_world_v1(db)
    upgrade_world_model(db, backup_dir=tmp_path / "bak")
    c = sqlite3.connect(str(db))
    row = c.execute("SELECT entity_id, stable_id FROM entities").fetchone()
    c.close()
    assert row[0] == "user:satvik" and row[1] is None   # old data intact, new col NULL


def test_validate(tmp_path):
    db = tmp_path / "world.db"; _make_world_v1(db)
    runner = world_migration_runner(db, backup_dir=tmp_path / "bak")
    runner.upgrade()
    report = runner.validate()
    assert report["ok"] and report["current"] == 2


def test_rollback(tmp_path):
    db = tmp_path / "world.db"; _make_world_v1(db)
    runner = world_migration_runner(db, backup_dir=tmp_path / "bak")
    runner.upgrade()
    assert runner.current_version() == 2
    res = runner.downgrade(to=1)
    assert res.ok and runner.current_version() == 1
    c = sqlite3.connect(str(db))
    cols = [r[1] for r in c.execute("PRAGMA table_info(entities)")]
    c.close()
    assert "stable_id" not in cols                   # column dropped on downgrade


def test_idempotent_status_after_upgrade(tmp_path):
    db = tmp_path / "world.db"; _make_world_v1(db)
    runner = world_migration_runner(db, backup_dir=tmp_path / "bak")
    runner.upgrade()
    assert runner.status()["up_to_date"]
