from pathlib import Path

import pytest

from mcpgw.config import load_config, parse_config, resolve_secret_env
from mcpgw.contracts.errors import ConfigError, ExitCode

ROOT = Path(__file__).resolve().parents[1]


def _stdio(alias: str = "fs", **kw: object) -> dict[str, object]:
    return {"alias": alias, "transport": "stdio", "command": "npx", **kw}


def test_example_config_is_valid() -> None:
    cfg = load_config(ROOT / "mcpgw.example.yaml", env={})
    assert [u.alias for u in cfg.upstreams] == ["fs", "github"]
    assert cfg.ingest.max_pages == 100
    assert cfg.db_path.is_absolute() and cfg.db_path.parent == ROOT / "data"


def test_defaults_match_srs(tmp_path: Path) -> None:
    cfg = parse_config({"config_version": 1}, base_dir=tmp_path, env={})
    assert (cfg.ingest.concurrency, cfg.ingest.max_pages, cfg.ingest.timeout_s) == (4, 100, 30)
    assert cfg.retrieval.search.default_k == 8
    assert cfg.db_path == tmp_path / "data" / "mcpgw.sqlite"


@pytest.mark.parametrize(
    "upstream",
    [
        _stdio("Bad_Alias"),
        _stdio("has_underscore"),
        _stdio("x" * 33),
        {"alias": "fs", "transport": "stdio"},
        {"alias": "fs", "transport": "streamable_http"},
        _stdio(url="http://x"),
        {"alias": "fs", "transport": "carrier-pigeon", "command": "x"},
        _stdio(unexpected_key=1),
    ],
)
def test_invalid_upstreams_rejected(tmp_path: Path, upstream: dict[str, object]) -> None:
    with pytest.raises(ConfigError) as ei:
        parse_config({"config_version": 1, "upstreams": [upstream]}, base_dir=tmp_path, env={})
    assert ei.value.exit_code == ExitCode.USAGE


def test_duplicate_alias_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate upstream alias"):
        parse_config(
            {"config_version": 1, "upstreams": [_stdio(), _stdio()]}, base_dir=tmp_path, env={}
        )


def test_error_message_names_the_field(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"ingest\.concurrency"):
        parse_config({"config_version": 1, "ingest": {"concurrency": 0}}, base_dir=tmp_path, env={})


def test_env_overrides(tmp_path: Path) -> None:
    env = {
        "MCPGW_GATEWAY__PORT": "9000",
        "MCPGW_INGEST__CONCURRENCY": "2",
        "MCPGW_DB_PATH": "other.sqlite",
        "MCPGW_LOG_LEVEL": "debug",
        "MCPGW_UPSTREAMS__0": "ignored",
    }
    cfg = parse_config({"config_version": 1}, base_dir=tmp_path, env=env)
    assert cfg.db_path == tmp_path / "other.sqlite"
    assert cfg.gateway.port == 9000
    assert cfg.ingest.concurrency == 2
    assert cfg.logging.level == "DEBUG"


def test_load_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml", env={})
    bad = tmp_path / "bad.yaml"
    bad.write_text("config_version: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="config_version"):
        load_config(bad, env={})
    bad.write_text("upstreams: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(bad, env={})


def test_mcpgw_config_env_var(tmp_path: Path) -> None:
    p = tmp_path / "custom.yaml"
    p.write_text("config_version: 1\n", encoding="utf-8")
    assert load_config(env={"MCPGW_CONFIG": str(p)}).data_dir == tmp_path / "data"


def test_resolve_secret_env() -> None:
    assert resolve_secret_env({"TOKEN": "HOST_TOKEN"}, {"HOST_TOKEN": "s3cret"}) == {
        "TOKEN": "s3cret"
    }
    with pytest.raises(ConfigError, match="HOST_TOKEN"):
        resolve_secret_env({"TOKEN": "HOST_TOKEN"}, {})
