"""Tool registry (M2): typed access to servers, tools, immutable versions and snapshots.

Week 1 scope: the snapshot write path, read methods, JSONL export and snapshot diff.
JSONL import, corpora and expansions follow in Week 2 (FR-2.4, FR-2.6, FR-2.9).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcpgw.contracts.records import ToolRecord, canonical_json, write_snapshot
from mcpgw.ingestion.models import ServerResult
from mcpgw.ingestion.params import extract_params
from mcpgw.registry.db import RegistryError, open_database, utc_now


@dataclass(frozen=True)
class SnapshotInfo:
    snapshot_id: int
    label: str
    created_at: str
    is_partial: bool
    tool_count: int
    jsonl_sha256: str | None


@dataclass(frozen=True)
class WriteSummary:
    snapshot: SnapshotInfo
    new_versions: int


@dataclass(frozen=True)
class ServerRow:
    server_id: int
    alias: str
    transport: str
    is_synthetic: bool


@dataclass
class SnapshotDiff:
    """Changes between two snapshots, keyed by qualified name (FR-1.9).

    Tools of servers that did not succeed in the newer snapshot are ``unknown``, not removed."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.unknown)


def _record_from_row(row: sqlite3.Row) -> ToolRecord:
    def load(v: str | None) -> Any:
        return None if v is None else json.loads(v)

    return ToolRecord.model_validate(
        {
            "alias": row["alias"],
            "name": row["name"],
            "qualified_name": row["qualified_name"],
            "title": row["title"],
            "description": row["description"],
            "inputSchema": json.loads(row["input_schema"]),
            "outputSchema": load(row["output_schema"]),
            "annotations": load(row["annotations"]),
            "flags": json.loads(row["flags"]),
            "content_hash": row["content_hash"],
        }
    )


_TOOL_COLUMNS = """
    s.alias, t.name, t.qualified_name, v.title, v.description, v.input_schema,
    v.output_schema, v.annotations, v.flags, v.content_hash
"""


class Registry:
    def __init__(self, path: Path | str) -> None:
        self.path = path
        self._conn = open_database(path)

    # -- lifecycle ---------------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Registry:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One ``BEGIN IMMEDIATE`` transaction: all rows or none."""
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    # -- writes ------------------------------------------------------------------------------

    def _upsert_server(self, conn: sqlite3.Connection, alias: str, transport: str) -> int:
        row = conn.execute("SELECT server_id FROM server WHERE alias = ?", (alias,)).fetchone()
        if row:
            return int(row[0])
        cur = conn.execute(
            "INSERT INTO server (alias, transport, is_synthetic, created_at) VALUES (?, ?, ?, ?)",
            (alias, transport, int(transport == "synthetic"), utc_now()),
        )
        return int(cur.lastrowid or 0)

    def _upsert_tool(self, conn: sqlite3.Connection, server_id: int, rec: ToolRecord) -> int:
        row = conn.execute(
            "SELECT tool_id FROM tool WHERE server_id = ? AND name = ?", (server_id, rec.name)
        ).fetchone()
        if row:
            return int(row[0])
        cur = conn.execute(
            "INSERT INTO tool (server_id, name, qualified_name) VALUES (?, ?, ?)",
            (server_id, rec.name, rec.qualified_name),
        )
        return int(cur.lastrowid or 0)

    def _find_or_insert_version(
        self, conn: sqlite3.Connection, tool_id: int, rec: ToolRecord, now: str
    ) -> tuple[int, bool]:
        row = conn.execute(
            "SELECT tool_version_id FROM tool_version WHERE tool_id = ? AND content_hash = ?",
            (tool_id, rec.content_hash),
        ).fetchone()
        if row:
            return int(row[0]), False

        def dump(v: Any) -> str | None:
            return None if v is None else canonical_json(v)

        cur = conn.execute(
            "INSERT INTO tool_version (tool_id, content_hash, title, description, input_schema,"
            " output_schema, annotations, flags, first_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tool_id,
                rec.content_hash,
                rec.title,
                rec.description or "",
                canonical_json(rec.input_schema),
                dump(rec.output_schema),
                dump(rec.annotations),
                canonical_json(sorted(rec.flags)),
                now,
            ),
        )
        version_id = int(cur.lastrowid or 0)
        conn.executemany(
            "INSERT INTO tool_param (tool_version_id, path, json_type, is_required, description)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (version_id, p.path, p.json_type, int(p.is_required), p.description)
                for p in extract_params(rec.input_schema)
            ],
        )
        return version_id, True

    def write_snapshot(
        self, label: str, results: Iterable[ServerResult], *, notes: str | None = None
    ) -> WriteSummary:
        """Store one ingestion run as an immutable snapshot, atomically (FR-1.8, FR-2.2)."""
        results = list(results)
        if not any(r.status == "ok" for r in results):
            raise RegistryError("refusing to write a snapshot with no successful server")
        if not label.strip():
            raise RegistryError("snapshot label must not be empty")
        is_partial = any(r.status == "failed" for r in results)
        protocols = {r.info.protocol_version for r in results if r.status == "ok"}
        protocol = protocols.pop() if len(protocols) == 1 else None
        now = utc_now()
        new_versions = 0
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM snapshot WHERE label = ?", (label,)).fetchone():
                raise RegistryError(f"snapshot label {label!r} already exists")
            cur = conn.execute(
                "INSERT INTO snapshot (label, created_at, mcp_protocol_version, is_partial, notes)"
                " VALUES (?, ?, ?, ?, ?)",
                (label, now, protocol, int(is_partial), notes),
            )
            snap_id = int(cur.lastrowid or 0)
            for r in results:
                server_id = self._upsert_server(conn, r.alias, r.transport)
                conn.execute(
                    "INSERT INTO snapshot_server (snapshot_id, server_id, status, tool_count,"
                    " server_name, server_version, protocol_version, error_message)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        snap_id,
                        server_id,
                        r.status,
                        len(r.records),
                        r.info.name,
                        r.info.version,
                        r.info.protocol_version,
                        r.error,
                    ),
                )
                for rec in r.records:
                    if rec.alias != r.alias:
                        raise RegistryError(
                            f"record {rec.qualified_name!r} does not belong to server {r.alias!r}"
                        )
                    tool_id = self._upsert_tool(conn, server_id, rec)
                    version_id, created = self._find_or_insert_version(conn, tool_id, rec, now)
                    new_versions += created
                    conn.execute(
                        "INSERT INTO snapshot_tool (snapshot_id, tool_id, tool_version_id)"
                        " VALUES (?, ?, ?)",
                        (snap_id, tool_id, version_id),
                    )
        return WriteSummary(self.snapshot(label), new_versions)

    def export_snapshot(self, snapshot: str | int, path: Path) -> dict[str, Any]:
        """Write canonical JSONL (temp file, fsync, rename) and record its SHA-256."""
        info = self.snapshot(snapshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        manifest = write_snapshot(self.snapshot_tools(info.snapshot_id), tmp)
        with tmp.open("r+b") as fh:  # fsync needs a writable handle on Windows
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        self._conn.execute(
            "UPDATE snapshot SET jsonl_sha256 = ? WHERE snapshot_id = ?",
            (manifest["sha256"], info.snapshot_id),
        )
        return {"label": info.label, **manifest}

    # -- reads -------------------------------------------------------------------------------

    def snapshot(self, snapshot: str | int) -> SnapshotInfo:
        column = "snapshot_id" if isinstance(snapshot, int) else "label"
        row = self._conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM snapshot_tool st"
            " WHERE st.snapshot_id = s.snapshot_id) AS tool_count"
            f" FROM snapshot s WHERE s.{column} = ?",
            (snapshot,),
        ).fetchone()
        if row is None:
            raise RegistryError(f"unknown snapshot {snapshot!r}")
        return SnapshotInfo(
            snapshot_id=row["snapshot_id"],
            label=row["label"],
            created_at=row["created_at"],
            is_partial=bool(row["is_partial"]),
            tool_count=row["tool_count"],
            jsonl_sha256=row["jsonl_sha256"],
        )

    def list_snapshots(self) -> list[SnapshotInfo]:
        rows = self._conn.execute(
            "SELECT snapshot_id FROM snapshot ORDER BY snapshot_id"
        ).fetchall()
        return [self.snapshot(int(r[0])) for r in rows]

    def latest_snapshot(self) -> SnapshotInfo | None:
        row = self._conn.execute("SELECT MAX(snapshot_id) FROM snapshot").fetchone()
        return None if row[0] is None else self.snapshot(int(row[0]))

    def list_servers(self) -> list[ServerRow]:
        rows = self._conn.execute(
            "SELECT server_id, alias, transport, is_synthetic FROM server ORDER BY alias"
        ).fetchall()
        return [ServerRow(r[0], r[1], r[2], bool(r[3])) for r in rows]

    def snapshot_tools(self, snapshot: str | int) -> list[ToolRecord]:
        info = self.snapshot(snapshot)
        rows = self._conn.execute(
            f"SELECT {_TOOL_COLUMNS} FROM snapshot_tool st"
            " JOIN tool t ON t.tool_id = st.tool_id"
            " JOIN tool_version v ON v.tool_version_id = st.tool_version_id"
            " JOIN server s ON s.server_id = t.server_id"
            " WHERE st.snapshot_id = ? ORDER BY t.qualified_name",
            (info.snapshot_id,),
        ).fetchall()
        return [_record_from_row(r) for r in rows]

    def tool(self, qualified_name: str, snapshot: str | int | None = None) -> ToolRecord | None:
        """A tool as of ``snapshot``, or its newest version when ``snapshot`` is None."""
        if snapshot is not None:
            info = self.snapshot(snapshot)
            row = self._conn.execute(
                f"SELECT {_TOOL_COLUMNS} FROM snapshot_tool st"
                " JOIN tool t ON t.tool_id = st.tool_id"
                " JOIN tool_version v ON v.tool_version_id = st.tool_version_id"
                " JOIN server s ON s.server_id = t.server_id"
                " WHERE st.snapshot_id = ? AND t.qualified_name = ?",
                (info.snapshot_id, qualified_name),
            ).fetchone()
        else:
            row = self._conn.execute(
                f"SELECT {_TOOL_COLUMNS} FROM tool t"
                " JOIN tool_version v ON v.tool_id = t.tool_id"
                " JOIN server s ON s.server_id = t.server_id"
                " WHERE t.qualified_name = ? ORDER BY v.tool_version_id DESC LIMIT 1",
                (qualified_name,),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def version_history(self, qualified_name: str) -> list[tuple[str, str]]:
        """``(content_hash, first_seen_at)`` for every version, oldest first."""
        rows = self._conn.execute(
            "SELECT v.content_hash, v.first_seen_at FROM tool t"
            " JOIN tool_version v ON v.tool_id = t.tool_id"
            " WHERE t.qualified_name = ? ORDER BY v.tool_version_id",
            (qualified_name,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def diff(self, old: str | int, new: str | int) -> SnapshotDiff:
        old_info, new_info = self.snapshot(old), self.snapshot(new)
        old_tools = {r.qualified_name: r for r in self.snapshot_tools(old_info.snapshot_id)}
        new_tools = {r.qualified_name: r for r in self.snapshot_tools(new_info.snapshot_id)}
        not_ok = {
            r[0]
            for r in self._conn.execute(
                "SELECT s.alias FROM snapshot_server ss JOIN server s ON s.server_id = ss.server_id"
                " WHERE ss.snapshot_id = ? AND ss.status != 'ok'",
                (new_info.snapshot_id,),
            )
        }
        out = SnapshotDiff()
        for q in sorted(new_tools.keys() - old_tools.keys()):
            out.added.append(q)
        for q in sorted(old_tools.keys() - new_tools.keys()):
            (out.unknown if old_tools[q].alias in not_ok else out.removed).append(q)
        for q in sorted(old_tools.keys() & new_tools.keys()):
            if old_tools[q].content_hash != new_tools[q].content_hash:
                out.changed.append(q)
        return out
