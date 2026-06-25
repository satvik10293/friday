# M10 — Database Migration Framework

> Closes the architecture review's "`schema_version` is a gate with no runner"
> risk. New additive package `core/database/migrations/`. **Tests:
> `tests/test_migrations.py` (11).**

## What it is

A reusable, **database-agnostic** schema migration runner. Any FRIDAY SQLite store
— `memory.db`, `knowledge.db`, `user_model.db`, `model_registry`/`mission_control`,
and future DBs — can be upgraded/downgraded safely, with a consistent backup taken
before any change and an automatic rollback if a migration fails. No redesign per
database.

It is **compatible with the existing stores**: it reads/writes the same
`schema_version (version, applied_at)` table they already create, so a store at
version 1 is simply "1 migration applied".

## `MigrationRunner`

```python
from core.database.migrations import MigrationRunner, sql_migration

runner = MigrationRunner("data/knowledge.db", [
    sql_migration(2, "add_tags",
                  up_sql="ALTER TABLE knowledge ADD COLUMN tags TEXT DEFAULT '';",
                  down_sql="",                       # irreversible → no down
                  validate_sql="SELECT tags FROM knowledge LIMIT 1;"),
])
runner.status()      # {current, latest, pending, applied, up_to_date}
runner.upgrade()     # backup → apply pending in tx → rollback-on-failure
```

A `Migration` is `(version, name, up, down?, validate?)` where `up`/`down` operate
on an open `sqlite3.Connection`; `sql_migration(...)` builds one from SQL strings.

## Commands

| Command | Behaviour |
|---|---|
| `upgrade(to=None)` | Backup, then apply each pending migration ≤ `to` in its own transaction; record `schema_version` + `migration_history`. **Any failure restores the backup** and leaves the version unchanged. |
| `downgrade(to)` | Backup, then run `down()` for migrations above `to`, newest-first. Irreversible (no `down`) → restore + error. |
| `status()` | current / latest / applied / pending / up_to_date. |
| `validate()` | `PRAGMA integrity_check` + each applied migration's validator. |
| `backup()` | Consistent snapshot via the SQLite backup API → timestamped `.bak`. |
| `restore(path)` | Replace the live DB with a backup (drops stale WAL sidecars). |

## Safety properties (tested)

- **Atomic per step** — each migration runs in a transaction; a failing migration
  (`test_failing_migration_rolls_back`) leaves the DB at its prior version.
- **Backup before change** — `upgrade`/`downgrade` snapshot first; a failed batch is
  restored automatically.
- **Irreversible guard** — downgrading past a migration with no `down` restores and
  errors rather than corrupting (`test_irreversible_downgrade_rolls_back`).
- **DB-agnostic** — the same code drives memory/knowledge/user_model/mission_control
  DBs (`test_works_for_any_db_name`).
- **Duplicate-version guard** — constructing with two migrations at the same version
  raises.

## Why this matters going forward

Existing stores ship at version 1. When M11+ needs a schema change, it adds a
`Migration(version=2, …)` to that store's runner and calls `upgrade()` — backed up,
transactional, validated, reversible. No hand-rolled `ALTER TABLE` at boot, no risk
of a half-migrated DB.
