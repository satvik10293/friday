"""
core/database/ — FRIDAY 4.0 (M10)
Shared database infrastructure. Currently the migration framework — a reusable,
DB-agnostic runner that upgrades/downgrades any FRIDAY SQLite store (memory,
knowledge, user_model, mission_control, and future DBs) with backup + rollback,
so no future milestone has to stop for a hand-rolled schema change.

Side-effect-free to import.
"""

from __future__ import annotations

from .migrations.migration_runner import (Migration, MigrationResult,
                                           MigrationRunner, sql_migration)

__all__ = ["Migration", "MigrationResult", "MigrationRunner", "sql_migration"]
