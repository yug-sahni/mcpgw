from pathlib import Path
from typing import Any

import pytest

from mcpgw.config import Config, parse_config
from mcpgw.contracts.errors import ConfigError, ExitCode, IngestError
from mcpgw.contracts.records import read_snapshot
from mcpgw.ingestion.ingest import ingest_all, ingest_server, redact, run_ingest
from mcpgw.ingestion.models import RawTool
from mcpgw.registry import Registry
from tests.fixtures.fake_upstreams import BASIC_TOOLS, FakeUpstream, connector, object_schema


def make_config(tmp_path: Path, *aliases: str, **ingest: Any) -> Config:
    ups = [{"alias": a, "transport": "stdio", "command": "fake"} for a in aliases]
    return parse_config(
        {"config_version": 1, "upstreams": ups, "ingest": ingest}, base_dir=tmp_path, env={}
    )


async def test_basic_ingest(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a")
    r = await ingest_server(
        cfg.upstreams[0], cfg, connector=connector({"a": FakeUpstream(BASIC_TOOLS())}), env={}
    )
    assert r.status == "ok" and r.error is None
    assert len(r.records) == 10
    assert r.info.protocol_version == "2025-11-25"


async def test_pagination_follows_cursor(tmp_path: Path) -> None:
    tools = [
        RawTool(name=f"t{i}", description="d", input_schema=object_schema()) for i in range(100)
    ]
    fake = FakeUpstream(tools, page_size=3)
    cfg = make_config(tmp_path, "a")
    r = await ingest_server(cfg.upstreams[0], cfg, connector=connector({"a": fake}), env={})
    assert len(r.records) == 100 and r.pages == 34 and not r.warnings


async def test_endless_cursor_hits_page_cap(tmp_path: Path) -> None:
    fake = FakeUpstream(BASIC_TOOLS(), page_size=1, endless_cursor=True)
    cfg = make_config(tmp_path, "a", max_pages=5)
    r = await ingest_server(cfg.upstreams[0], cfg, connector=connector({"a": fake}), env={})
    assert r.status == "ok" and r.pages == 5
    assert any("page cap" in w for w in r.warnings)


async def test_repeated_cursor_stops(tmp_path: Path) -> None:
    class Loop(FakeUpstream):
        async def list_tools_page(self, cursor: str | None) -> Any:
            from mcpgw.ingestion.models import ToolPage

            self.calls += 1
            return ToolPage(self.tools[:1], next_cursor="same")

    cfg = make_config(tmp_path, "a")
    r = await ingest_server(
        cfg.upstreams[0], cfg, connector=connector({"a": Loop(BASIC_TOOLS())}), env={}
    )
    assert r.status == "ok" and r.pages == 2
    assert len(r.records) == 1  # the duplicate is folded by name
    assert any("repeated cursor" in w for w in r.warnings)


async def test_max_tools_per_server(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a", max_tools_per_server=4)
    fake = FakeUpstream(BASIC_TOOLS(), page_size=3)
    r = await ingest_server(cfg.upstreams[0], cfg, connector=connector({"a": fake}), env={})
    assert len(r.records) == 4
    assert any("first 4 of 6" in w for w in r.warnings)


async def test_timeout_marks_failed(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a", timeout_s=0.05)
    fake = FakeUpstream(BASIC_TOOLS(), delay_s=5)
    r = await ingest_server(cfg.upstreams[0], cfg, connector=connector({"a": fake}), env={})
    assert r.status == "failed" and r.error == "timed out after 0.05s" and r.records == []


async def test_crash_mid_listing_keeps_no_partial_records(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a")
    fake = FakeUpstream(BASIC_TOOLS(), page_size=3, fail_on_page=2)
    r = await ingest_server(cfg.upstreams[0], cfg, connector=connector({"a": fake}), env={})
    assert r.status == "failed" and r.records == []
    assert r.error is not None and "ConnectionResetError" in r.error


async def test_secrets_resolved_and_redacted(tmp_path: Path) -> None:
    cfg = parse_config(
        {
            "config_version": 1,
            "upstreams": [
                {
                    "alias": "gh",
                    "transport": "stdio",
                    "command": "x",
                    "env": {"TOKEN": "HOST_TOKEN"},
                }
            ],
        },
        base_dir=tmp_path,
        env={},
    )
    fake = FakeUpstream([], fail_on_connect=RuntimeError("auth failed for token ghp_supersecret"))
    r = await ingest_server(
        cfg.upstreams[0],
        cfg,
        connector=connector({"gh": fake}),
        env={"HOST_TOKEN": "ghp_supersecret"},
    )
    assert fake.seen_secrets == {"TOKEN": "ghp_supersecret"}
    assert r.status == "failed" and r.error is not None
    assert "ghp_supersecret" not in r.error and "***" in r.error


async def test_missing_secret_env_fails_server_only(tmp_path: Path) -> None:
    cfg = parse_config(
        {
            "config_version": 1,
            "upstreams": [
                {"alias": "gh", "transport": "stdio", "command": "x", "env": {"TOKEN": "NOT_SET"}}
            ],
        },
        base_dir=tmp_path,
        env={},
    )
    r = await ingest_server(
        cfg.upstreams[0], cfg, connector=connector({"gh": FakeUpstream([])}), env={}
    )
    assert r.status == "failed" and "NOT_SET" in (r.error or "")


def test_redact_ignores_tiny_values() -> None:
    assert redact("a b abc secret", ["a", "secret"]) == "a b abc ***"


async def test_one_failing_server_does_not_block_others(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "good", "bad", "slow", concurrency=2, timeout_s=0.1)
    fakes = {
        "good": FakeUpstream(BASIC_TOOLS()),
        "bad": FakeUpstream([], fail_on_connect=OSError("spawn failed")),
        "slow": FakeUpstream(BASIC_TOOLS(), delay_s=5),
    }
    results = await ingest_all(cfg, connector=connector(fakes), env={})
    assert [(r.alias, r.status) for r in results] == [
        ("good", "ok"),
        ("bad", "failed"),
        ("slow", "failed"),
    ]


async def test_servers_filter(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a", "b")
    fakes = {"a": FakeUpstream(BASIC_TOOLS()), "b": FakeUpstream(BASIC_TOOLS())}
    results = await ingest_all(cfg, servers=["b"], connector=connector(fakes), env={})
    assert [(r.alias, r.status) for r in results] == [("a", "skipped"), ("b", "ok")]
    assert fakes["a"].calls == 0
    with pytest.raises(ConfigError, match="zzz"):
        await ingest_all(cfg, servers=["zzz"], connector=connector(fakes), env={})


async def test_run_ingest_end_to_end(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a", "b")
    fakes = {"a": FakeUpstream(BASIC_TOOLS()), "b": FakeUpstream(BASIC_TOOLS()[:3])}
    report = await run_ingest(cfg, "s1", connector=connector(fakes), env={})
    assert report.summary.snapshot.tool_count == 13 and not report.summary.snapshot.is_partial
    assert report.summary.new_versions == 13 and report.diff is None
    exported = read_snapshot(report.export_path)
    assert [r.qualified_name for r in exported] == sorted(r.qualified_name for r in exported)

    # Re-ingesting unchanged tools adds no versions; a changed description adds exactly one.
    tools_b = BASIC_TOOLS()[:3]
    tools_b[0] = RawTool(name=tools_b[0].name, description="changed", input_schema=object_schema())
    fakes = {"a": FakeUpstream(BASIC_TOOLS()), "b": FakeUpstream(tools_b)}
    report2 = await run_ingest(cfg, "s2", connector=connector(fakes), env={})
    assert report2.summary.new_versions == 1
    assert report2.diff is not None and report2.diff.changed == ["b__tool_00"]

    # A failed server gives a partial snapshot; its tools are "unknown", not removed.
    fakes = {"a": FakeUpstream(BASIC_TOOLS()), "b": FakeUpstream([], fail_on_connect=OSError("x"))}
    report3 = await run_ingest(cfg, "s3", connector=connector(fakes), env={})
    assert report3.summary.snapshot.is_partial
    assert report3.diff is not None
    assert report3.diff.removed == [] and len(report3.diff.unknown) == 3


async def test_run_ingest_all_failed_writes_nothing(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a")
    fakes = {"a": FakeUpstream([], fail_on_connect=OSError("x"))}
    with pytest.raises(IngestError) as ei:
        await run_ingest(cfg, "s1", connector=connector(fakes), env={})
    assert ei.value.exit_code == ExitCode.INGEST
    with Registry(cfg.db_path) as reg:
        assert reg.list_snapshots() == []


async def test_run_ingest_strict(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, "a", "b")
    fakes = {"a": FakeUpstream(BASIC_TOOLS()), "b": FakeUpstream([], fail_on_connect=OSError("x"))}
    with pytest.raises(IngestError, match="--strict"):
        await run_ingest(cfg, "s1", strict=True, connector=connector(fakes), env={})


@pytest.mark.parametrize("label", ["", "../escape", "has space", "x" * 65])
async def test_bad_labels(tmp_path: Path, label: str) -> None:
    with pytest.raises(ConfigError):
        await run_ingest(make_config(tmp_path, "a"), label, connector=connector({}), env={})
