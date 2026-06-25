"""
core/database/migrations/migration_runner.py — FRIDAY 4.0 (M10)
A reusable, database-agnostic schema migration runner. Closes the architecture
review's "schema_version is a gate with no runner" risk: every FRIDAY SQLite store
can now be upgraded/downgraded safely, with a consistent backup taken before any
change and an automatic rollback (restore) if a migration fails.

Compatible with the existing stores: it reads/writes the same `schema_version`
table (version INTEGER PRIMARY KEY, applied_at REAL) those stores already create,
so a store sitting at version 1 is simply "1 migration applied".

Commands: upgrade · downgrade · status · validate · backup · restore.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("friday.database.migrations")

# A migration step operates on an open sqlite3.Connection.
Step = Callable[[sqlite3.Connection], None]
Validator = Callable[[sqlite3.Connection], bool]


@dataclass
class Migration:
    version: int                 # target version this migration brings the DB TO
    name: str
    up: Step
    down: Optional[Step] = None
    validate: Optional[Validator] = None


def sql_migration(version: int, name: str, up_sql: str,
                  down_sql: str = "", validate_sql: str = "") -> Migration:
    """Build a Migration from SQL strings (executescript)."""
    def _up(c: sqlite3.Connection) -> None:
        c.executescript(up_sql)

    def _down(c: sqlite3.Connection) -> None:
        if down_sql:
            c.executescript(down_sql)

    validator = None
    if validate_sql:
        def validator(c: sqlite3.Connection) -> bool:  # noqa: E306
            try:
                c.execute(validate_sql)
                return True
            except sqlite3.Error:
                return False

    return Migration(version=version, name=name, up=_up,
                     down=_down if down_sql else None, validate=validator)


@dataclass
class MigrationResult:
    db: str
    ok: bool
    from_version: int
    to_version: int
    applied: list = field(default_factory=list)       # list[dict]
    backup: Optional[str] = None
    error: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class MigrationRunner:
    def __init__(self, db_path: str | Path, migrations: list[Migration],
                 *, backup_dir: Optional[str | Path] = None) -> None:
        self._path = Path(db_path)
        self._migrations = sorted(migrations, key=lambda m: m.version)
        self._backup_dir = Path(backup_dir) if backup_dir else (
            self._path.parent / "migration_backups")
        self._validate_versions()

    def _validate_versions(self) -> None:
        seen = set()
        for m in self._migrations:
            if m.version in seen:
                raise ValueError(f"duplicate migration version {m.version}")
            if m.version < 1:
                raise ValueError("migration versions must be >= 1")
            seen.add(m.version)

    # ── connection / bookkeeping ────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("""CREATE TABLE IF NOT EXISTS schema_version (
                       version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS migration_history (
                       id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                       version INTEGER NOT NULL, name TEXT NOT NULL,
                       direction TEXT NOT NULL)""")
        c.commit()
        return c

    def current_version(self) -> int:
        c = self._connect()
        try:
            row = c.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            return int(row["v"]) if row and row["v"] is not None else 0
        finally:
            c.close()

    def latest_version(self) -> int:
        return self._migrations[-1].version if self._migrations else 0

    def pending(self) -> list[Migration]:
        cur = self.current_version()
        return [m for m in self._migrations if m.version > cur]

    # ── status ──────────────────────────────────────────────────────────────────
    def status(self) -> dict:
        cur = self.current_version()
        return {
            "db": str(self._path),
            "exists": self._path.exists(),
            "current": cur,
            "latest": self.latest_version(),
            "up_to_date": cur >= self.latest_version(),
            "applied": [m.version for m in self._migrations if m.version <= cur],
            "pending": [m.version for m in self._migrations if m.version > cur],
        }

    # ── backup / restore ────────────────────────────────────────────────────────
    def backup(self) -> Optional[str]:
        """Consistent snapshot of the DB via the SQLite backup API. Returns the
        backup path, or None if the DB doesn't exist yet."""
        if not self._path.exists():
            return None
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = self._backup_dir / f"{self._path.stem}.{stamp}.v{self.current_version()}.bak"
        src = sqlite3.connect(str(self._path))
        try:
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return str(dest)

    def restore(self, backup_path: str | Path) -> bool:
        """Replace the live DB with a backup file."""
        backup_path = Path(backup_path)
        if not backup_path.exists():
            return False
        # drop WAL sidecars so the restored file is authoritative
        for suffix in ("-wal", "-shm"):
            side = Path(str(self._path) + suffix)
            if side.exists():
                try:
                    side.unlink()
                except OSError:
                    pass
        shutil.copyfile(backup_path, self._path)
        return True

    # ── upgrade / downgrade ─────────────────────────────────────────────────────
    def upgrade(self, to: Optional[int] = None) -> MigrationResult:
        cur = self.current_version()
        target = self.latest_version() if to is None else to
        result = MigrationResult(db=str(self._path), ok=True,
                                 from_version=cur, to_version=cur)
        steps = [m for m in self._migrations if cur < m.version <= target]
        if not steps:
            return result

        result.backup = self.backup()
        c = self._connect()
        try:
            for m in steps:
                try:
                    c.execute("BEGIN")
                    m.up(c)
                    c.execute("INSERT OR REPLACE INTO schema_version (version, applied_at) "
                              "VALUES (?, ?)", (m.version, time.time()))
                    c.execute("INSERT INTO migration_history (ts, version, name, direction) "
                              "VALUES (?, ?, ?, ?)", (time.time(), m.version, m.name, "up"))
                    c.commit()
                    result.applied.append({"version": m.version, "name": m.name})
                    result.to_version = m.version
                except Exception as e:           # noqa: BLE001 — any failure rolls back
                    c.rollback()
                    raise RuntimeError(f"migration {m.version} ({m.name}) failed: {e}") from e
        except Exception as e:                    # noqa: BLE001
            result.ok = False
            result.error = str(e)
            c.close()
            if result.backup:                     # roll the whole batch back
                self.restore(result.backup)
                result.to_version = cur
            return result
        c.close()
        return result

    def downgrade(self, to: int) -> MigrationResult:
        cur = self.current_version()
        result = MigrationResult(db=str(self._path), ok=True,
                                 from_version=cur, to_version=cur)
        steps = [m for m in reversed(self._migrations) if to < m.version <= cur]
        if not steps:
            return result

        result.backup = self.backup()
        c = self._connect()
        try:
            for m in steps:
                if m.down is None:
                    raise RuntimeError(f"migration {m.version} ({m.name}) is irreversible")
                try:
                    c.execute("BEGIN")
                    m.down(c)
                    c.execute("DELETE FROM schema_version WHERE version=?", (m.version,))
                    c.execute("INSERT INTO migration_history (ts, version, name, direction) "
                              "VALUES (?, ?, ?, ?)", (time.time(), m.version, m.name, "down"))
                    c.commit()
                    result.applied.append({"version": m.version, "name": m.name})
                except Exception as e:           # noqa: BLE001
                    c.rollback()
                    raise RuntimeError(f"downgrade {m.version} ({m.name}) failed: {e}") from e
        except Exception as e:                    # noqa: BLE001
            result.ok = False
            result.error = str(e)
            c.close()
            if result.backup:
                self.restore(result.backup)
            return result
        result.to_version = self.current_version()
        c.close()
        return result

    # ── validate ────────────────────────────────────────────────────────────────
    def validate(self) -> dict:
        """Run each applied migration's validator. Reports schema integrity."""
        cur = self.current_version()
        c = self._connect()
        checks = []
        ok = True
        try:
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                ok = False
            for m in self._migrations:
                if m.version <= cur and m.validate is not None:
                    passed = bool(m.validate(c))
                    checks.append({"version": m.version, "name": m.name, "ok": passed})
                    ok = ok and passed
        finally:
            c.close()
        return {"db": str(self._path), "ok": ok, "current": cur,
                "integrity": integrity, "checks": checks}

    def health(self) -> dict:
        s = self.status()
        return {"status": "ok" if s["up_to_date"] else "pending_migrations",
                "current": s["current"], "latest": s["latest"],
                "pending": len(s["pending"])}
