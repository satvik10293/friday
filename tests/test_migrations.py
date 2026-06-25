"""M10 — Database migration framework."""

import sqlite3

import pytest

from core.database.migrations.migration_runner import (Migration, MigrationRunner,
                                                       sql_migration)


def _runner(tmp_path, migrations):
    return MigrationRunner(tmp_path / "t.db", migrations,
                           backup_dir=tmp_path / "backups")


def _mig1():
    return sql_migration(1, "create_widgets",
                         "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);",
                         "DROP TABLE widgets;",
                         "SELECT name FROM widgets LIMIT 1;")


def _mig2():
    return sql_migration(2, "add_color",
                         "ALTER TABLE widgets ADD COLUMN color TEXT DEFAULT 'red';",
                         "")   # irreversible (no down)


def test_status_empty(tmp_path):
    r = _runner(tmp_path, [_mig1(), _mig2()])
    s = r.status()
    assert s["current"] == 0 and s["latest"] == 2
    assert s["pending"] == [1, 2] and not s["up_to_date"]


def test_upgrade_all(tmp_path):
    r = _runner(tmp_path, [_mig1(), _mig2()])
    res = r.upgrade()
    assert res.ok and res.to_version == 2
    assert [m["version"] for m in res.applied] == [1, 2]
    assert r.current_version() == 2
    # schema actually changed
    c = sqlite3.connect(str(tmp_path / "t.db"))
    cols = [row[1] for row in c.execute("PRAGMA table_info(widgets)")]
    c.close()
    assert "color" in cols


def test_upgrade_to_target(tmp_path):
    r = _runner(tmp_path, [_mig1(), _mig2()])
    r.upgrade(to=1)
    assert r.current_version() == 1
    assert r.status()["pending"] == [2]


def test_downgrade(tmp_path):
    r = _runner(tmp_path, [_mig1(), _mig2()])
    r.upgrade(to=1)            # only mig1 (reversible)
    res = r.downgrade(to=0)
    assert res.ok and r.current_version() == 0


def test_irreversible_downgrade_rolls_back(tmp_path):
    r = _runner(tmp_path, [_mig1(), _mig2()])
    r.upgrade()
    res = r.downgrade(to=0)   # mig2 has no down → fail, restore
    assert not res.ok
    assert "irreversible" in res.error
    assert r.current_version() == 2          # restored to pre-downgrade state


def test_validate(tmp_path):
    r = _runner(tmp_path, [_mig1()])
    r.upgrade()
    report = r.validate()
    assert report["ok"] and report["integrity"] == "ok"
    assert report["checks"][0]["ok"]


def test_backup_and_restore(tmp_path):
    r = _runner(tmp_path, [_mig1()])
    r.upgrade()
    backup = r.backup()
    assert backup is not None
    # corrupt forward: add a row, then restore
    c = sqlite3.connect(str(tmp_path / "t.db"))
    c.execute("INSERT INTO widgets (name) VALUES ('temp')"); c.commit(); c.close()
    assert r.restore(backup) is True


def test_failing_migration_rolls_back(tmp_path):
    bad = Migration(version=1, name="bad",
                    up=lambda c: c.executescript("CREATE TABLE x(a); INSERT INTO nope VALUES(1);"))
    r = _runner(tmp_path, [bad])
    res = r.upgrade()
    assert not res.ok
    assert r.current_version() == 0          # rolled back, version not advanced


def test_duplicate_versions_rejected(tmp_path):
    with pytest.raises(ValueError):
        _runner(tmp_path, [_mig1(), Migration(1, "dup", up=lambda c: None)])


def test_health(tmp_path):
    r = _runner(tmp_path, [_mig1()])
    assert r.health()["status"] == "pending_migrations"
    r.upgrade()
    assert r.health()["status"] == "ok"


def test_works_for_any_db_name(tmp_path):
    # the runner is db-agnostic — same code for memory/knowledge/user_model/etc.
    for name in ("memory", "knowledge", "user_model", "mission_control"):
        runner = MigrationRunner(tmp_path / f"{name}.db", [_mig1()],
                                 backup_dir=tmp_path / "b")
        assert runner.upgrade().ok
        assert runner.current_version() == 1
