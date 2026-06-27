"""
core/cognition_core/migration.py — FRIDAY 6.0 (M13)
The additive World Model schema upgrade (v2): give world entities a `stable_id`
column so they can reference the persistent entity registry. This is an *extension*,
not a redesign — M5's `WorldModel` code is untouched (its explicit-column INSERT/
SELECT ignore the new nullable column). Driven by the M10 MigrationRunner, so the
upgrade takes a backup and can roll back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.database.migrations.migration_runner import (Migration, MigrationRunner,
                                                       sql_migration)


def world_stable_id_migration() -> Migration:
    """v2: add a nullable `stable_id` column + index to world.db entities."""
    return sql_migration(
        version=2, name="world_entity_stable_id",
        up_sql=(
            "ALTER TABLE entities ADD COLUMN stable_id TEXT;\n"
            "CREATE INDEX IF NOT EXISTS idx_entities_stable_id ON entities(stable_id);"
        ),
        down_sql=(
            "DROP INDEX IF EXISTS idx_entities_stable_id;\n"
            "ALTER TABLE entities DROP COLUMN stable_id;"
        ),
        validate_sql="SELECT stable_id FROM entities LIMIT 1;")


def world_migration_runner(db_path: str | Path, *,
                           backup_dir: Optional[str | Path] = None) -> MigrationRunner:
    """A runner pre-loaded with the world.db migration set (v1 is M5's baseline)."""
    return MigrationRunner(db_path, [world_stable_id_migration()], backup_dir=backup_dir)


def upgrade_world_model(db_path: str | Path, *,
                        backup_dir: Optional[str | Path] = None):
    """Apply the v2 stable_id extension to a world.db (backed up + rollback-safe)."""
    return world_migration_runner(db_path, backup_dir=backup_dir).upgrade()
