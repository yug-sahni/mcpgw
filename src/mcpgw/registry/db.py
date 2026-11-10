"""SQLite connection setup and numbered migrations (FR-2.7, FR-2.8).

Every connection gets ``foreign_keys=ON``, WAL journaling and a busy timeout. Migrations are the
files ``migrations/NNNN_<name>.sql``, applied in order inside one ``BEGIN IMMEDIATE`` transaction
each and recorded in ``schema_version``. A database newer than the code is refused, and an
existing database is backed up before any migration touches it.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from mcpgw.contracts.errors import GatewayError

BUSY_TIMEOUT_MS = 5000
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class RegistryError(GatewayError):
    """The registry database is unusable (wrong version, failed migration, integrity)."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_migrations() -> list[Migration]:
    pkg = resources.files("mcpgw.registry") / "migrations"
    out: list[Migration] = []
    for entry in pkg.iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            out.append(Migration(int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    out.sort(key=lambda mig: mig.version)
    versions = [mig.version for mig in out]
    if versions != list(range(1, len(versions) + 1)):
        raise RegistryError(f"migrations must be numbered 1..n without gaps, got {versions}")
    return out


def connect(path: Path | str, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Open a connection in autocommit mode; callers manage transactions explicitly."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            conn.close()
            raise RegistryError(f"could not enable WAL journaling on {path} (got {mode!r})")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not exists:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def _backup(conn: sqlite3.Connection, db_path: Path, from_version: int) -> Path:
    target = db_path.with_name(f"{db_path.name}.pre-v{from_version + 1}.bak")
    with sqlite3.connect(str(target)) as dst:
        conn.backup(dst)
    dst.close()
    return target


def migrate(conn: sqlite3.Connection, db_path: Path | None = None) -> int:
    """Apply pending migrations; return the resulting schema version."""
    migrations = load_migrations()
    latest = migrations[-1].version if migrations else 0
    version = current_version(conn)
    if version > latest:
        raise RegistryError(
            f"database schema version {version} is newer than this code supports ({latest}); "
            "upgrade mcpgw"
        )
    if version == latest:
        return version
    if version > 0 and db_path is not None:
        _backup(conn, db_path, version)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    for mig in migrations:
        if mig.version <= version:
            continue
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{mig.sql}\n"
            f"INSERT INTO schema_version (version, applied_at) VALUES ({mig.version}, "
            f"'{utc_now()}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as e:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise RegistryError(f"migration {mig.name} failed: {e}") from e
    return latest


def open_database(path: Path | str) -> sqlite3.Connection:
    """Connect and bring the schema up to date."""
    conn = connect(path)
    try:
        migrate(conn, None if str(path) == ":memory:" else Path(path))
    except Exception:
        conn.close()
        raise
    return conn
