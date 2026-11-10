import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mcpgw.cli import app
from mcpgw.contracts.errors import ExitCode

runner = CliRunner()
FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "stdio_server.py"


def write_config(tmp_path: Path, upstreams: list[dict[str, object]]) -> Path:
    p = tmp_path / "mcpgw.yaml"
    p.write_text(
        yaml.safe_dump({"config_version": 1, "upstreams": upstreams, "ingest": {"timeout_s": 20}}),
        encoding="utf-8",
    )
    return p


def test_version() -> None:
    assert runner.invoke(app, ["version"]).exit_code == 0


def test_missing_config_is_usage_error(tmp_path: Path) -> None:
    res = runner.invoke(app, ["ingest", "-l", "s1", "-c", str(tmp_path / "nope.yaml")])
    assert res.exit_code == ExitCode.USAGE


def test_snapshot_list_empty(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, [])
    res = runner.invoke(app, ["snapshot", "list", "-c", str(cfg)])
    assert res.exit_code == 0 and "no snapshots" in res.output


def test_ingest_all_failed_exit_code(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        [{"alias": "ghost", "transport": "stdio", "command": "definitely-not-a-command-xyz"}],
    )
    res = runner.invoke(app, ["ingest", "-l", "s1", "-c", str(cfg)])
    assert res.exit_code == ExitCode.INGEST
    assert "ghost" in res.output and "failed" in res.output  # per-server reasons still shown


@pytest.mark.integration
def test_ingest_real_stdio_server(tmp_path: Path) -> None:
    """Spawns a real MCP server through the SDK: initialize, tools/list, snapshot, export."""
    cfg = write_config(
        tmp_path,
        [
            {
                "alias": "fixture",
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(FIXTURE_SERVER)],
            },
            {"alias": "ghost", "transport": "stdio", "command": "definitely-not-a-command-xyz"},
        ],
    )
    res = runner.invoke(app, ["ingest", "-l", "s1", "-c", str(cfg)])
    assert res.exit_code == 0, res.output
    assert "partial" in res.output
    assert (tmp_path / "data" / "snapshots" / "s1.jsonl").is_file()
    listed = runner.invoke(app, ["snapshot", "list", "-c", str(cfg)])
    assert "s1" in listed.output and "2 tools" in listed.output
