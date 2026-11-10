import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from mcpgw.contracts.records import read_snapshot
from mcpgw.ingestion.models import ServerInfo, ServerResult
from mcpgw.registry import Registry, RegistryError
from mcpgw.registry.db import connect, current_version, load_migrations, migrate, open_database
from tests.fixtures.sample_corpus import build_sample_records


def results_from_sample() -> list[ServerResult]:
    by_alias: dict[str, ServerResult] = {}
    for rec in build_sample_records():
        r = by_alias.setdefault(
            rec.alias,
            ServerResult(rec.alias, "stdio", "ok", info=ServerInfo("x", "1", "2025-11-25")),
        )
        r.records.append(rec)
    return list(by_alias.values())


@pytest.fixture
def reg(tmp_path: Path) -> Iterator[Registry]:
    r = Registry(tmp_path / "db" / "mcpgw.sqlite")
    yield r
    r.close()


def test_pragmas_and_schema(tmp_path: Path) -> None:
    conn = open_database(tmp_path / "x.sqlite")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert current_version(conn) == len(load_migrations())
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"server", "tool", "tool_version", "snapshot_tool", "query", "eval_run"} <= tables
    conn.close()


def test_migrate_is_idempotent_and_refuses_newer(tmp_path: Path) -> None:
    path = tmp_path / "x.sqlite"
    open_database(path).close()
    conn = connect(path)
    assert migrate(conn, path) == 1
    conn.execute("INSERT INTO schema_version VALUES (99, 'future')")
    with pytest.raises(RegistryError, match="newer"):
        migrate(conn, path)
    conn.close()


def test_write_and_read_snapshot(reg: Registry, tmp_path: Path) -> None:
    summary = reg.write_snapshot("s1", results_from_sample())
    assert summary.snapshot.tool_count == 12 and summary.new_versions == 12
    assert not summary.snapshot.is_partial
    tools = reg.snapshot_tools("s1")
    assert tools == sorted(build_sample_records(), key=lambda r: r.qualified_name)
    assert reg.tool("fs__read_file") == reg.tool("fs__read_file", "s1")
    assert reg.tool("nope__x") is None
    assert [s.alias for s in reg.list_servers()] == ["docs", "fs", "git", "web"]
    params = reg._conn.execute(
        "SELECT p.path FROM tool_param p JOIN tool_version v USING (tool_version_id)"
        " JOIN tool t USING (tool_id) WHERE t.qualified_name = 'web__fetch_page' ORDER BY p.path"
    ).fetchall()
    assert [p[0] for p in params] == ["options", "options.max_length", "options.raw", "url"]


def test_reingest_unchanged_adds_no_version(reg: Registry) -> None:
    reg.write_snapshot("s1", results_from_sample())
    summary = reg.write_snapshot("s2", results_from_sample())
    assert summary.new_versions == 0
    assert len(reg.version_history("fs__read_file")) == 1
    assert reg.diff("s1", "s2").is_empty


def test_duplicate_label_rejected_atomically(reg: Registry) -> None:
    reg.write_snapshot("s1", results_from_sample())
    with pytest.raises(RegistryError, match="already exists"):
        reg.write_snapshot("s1", results_from_sample())
    assert len(reg.list_snapshots()) == 1


def test_failed_write_rolls_back(reg: Registry) -> None:
    results = results_from_sample()
    results[0].records.append(results[1].records[0])  # record from another server
    with pytest.raises(RegistryError, match="does not belong"):
        reg.write_snapshot("s1", results)
    assert reg.list_snapshots() == [] and reg.list_servers() == []


def test_no_ok_server_rejected(reg: Registry) -> None:
    with pytest.raises(RegistryError, match="no successful server"):
        reg.write_snapshot("s1", [ServerResult("a", "stdio", "failed", error="x")])


def test_immutability_triggers(reg: Registry) -> None:
    reg.write_snapshot("s1", results_from_sample())
    conn = reg._conn
    for sql in (
        "UPDATE tool_version SET description = 'x'",
        "DELETE FROM tool_version",
        "DELETE FROM snapshot_tool",
        "UPDATE server SET alias = 'renamed'",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(sql)


def test_frozen_benchmark_rejects_changes(reg: Registry) -> None:
    reg.write_snapshot("s1", results_from_sample())
    c = reg._conn
    c.execute(
        "INSERT INTO dataset_release (label, snapshot_id, created_at) VALUES ('d1', 1, 'now')"
    )
    c.execute(
        "INSERT INTO query (dataset_id, text, vagueness) VALUES (1, 'read my notes', 'action')"
    )
    c.execute("INSERT INTO query_gold_tool (query_id, tool_id) VALUES (1, 1)")
    c.execute("UPDATE dataset_release SET frozen_at = 'now' WHERE dataset_id = 1")
    for sql in (
        "INSERT INTO query (dataset_id, text, vagueness) VALUES (1, 'another', 'goal')",
        "UPDATE query SET text = 'edited'",
        "DELETE FROM query",
        "INSERT INTO query_gold_tool (query_id, tool_id) VALUES (1, 2)",
        "UPDATE query_gold_tool SET gold_group = 1",
        "DELETE FROM query_gold_tool",
        "UPDATE dataset_release SET label = 'renamed'",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="frozen"):
            c.execute(sql)


def test_test_split_runs_must_be_final(reg: Registry) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        reg._conn.execute(
            "INSERT INTO eval_run (kind, dataset_id, corpus_id, split, is_final, retriever_config,"
            " config_sha256, git_sha, seed, status, started_at)"
            " VALUES ('retrieval', 1, 1, 'test', 0, '{}', 'h', 'g', 1, 'running', 'now')"
        )


def test_export_matches_contract(reg: Registry, tmp_path: Path) -> None:
    reg.write_snapshot("s1", results_from_sample())
    out = tmp_path / "out" / "s1.jsonl"
    manifest = reg.export_snapshot("s1", out)
    assert manifest["count"] == 12
    assert reg.snapshot("s1").jsonl_sha256 == manifest["sha256"]
    assert read_snapshot(out) == reg.snapshot_tools("s1")
    assert not list(out.parent.glob(".*.tmp"))


def test_unknown_snapshot(reg: Registry) -> None:
    with pytest.raises(RegistryError, match="unknown snapshot"):
        reg.snapshot("missing")
    assert reg.latest_snapshot() is None
