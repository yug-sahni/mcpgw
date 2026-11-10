"""Configuration loader (SRS Part 8.2, FR-1.1, FR-8.2).

One YAML file validated by typed models. It holds no secrets: upstream credentials are referenced
by the *name* of a host environment variable, never by value.

Precedence, lowest to highest: model defaults, the YAML file, ``MCPGW_DB_PATH`` /
``MCPGW_INDEX_DIR`` / ``MCPGW_LOG_LEVEL``, then ``MCPGW_<SECTION>__<KEY>`` overrides.
Relative paths are resolved against the directory that contains the config file.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from mcpgw.contracts.errors import ConfigError
from mcpgw.contracts.records import ALIAS_RE

CONFIG_VERSION: Literal[1] = 1
DEFAULT_CONFIG_PATH = Path("mcpgw.yaml")
ENV_PREFIX = "MCPGW_"


class _Strict(BaseModel):
    """Unknown keys are errors, so typos fail loudly instead of being ignored."""

    model_config = ConfigDict(extra="forbid")


class UpstreamConfig(_Strict):
    alias: str
    transport: Literal["stdio", "streamable_http"]
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    # Maps the variable name the *server* expects to the *host* variable that holds the value.
    env: dict[str, str] = Field(default_factory=dict)
    # streamable_http
    url: str | None = None
    headers_env: dict[str, str] = Field(default_factory=dict)
    # None means "use ingest.timeout_s".
    timeout_s: float | None = Field(default=None, gt=0)

    @field_validator("alias")
    @classmethod
    def _alias_format(cls, v: str) -> str:
        if not ALIAS_RE.fullmatch(v):
            raise ValueError(f"alias {v!r} must match [a-z0-9-]{{1,32}} (no underscores)")
        return v

    @model_validator(mode="after")
    def _transport_fields(self) -> UpstreamConfig:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"upstream {self.alias!r}: stdio transport requires 'command'")
            if self.url or self.headers_env:
                raise ValueError(
                    f"upstream {self.alias!r}: 'url'/'headers_env' need streamable_http"
                )
        else:
            if not self.url:
                raise ValueError(f"upstream {self.alias!r}: streamable_http requires 'url'")
            if self.command or self.args:
                raise ValueError(f"upstream {self.alias!r}: 'command'/'args' need stdio")
        return self


class IngestConfig(_Strict):
    concurrency: int = Field(default=4, ge=1)
    max_pages: int = Field(default=100, ge=1)
    timeout_s: float = Field(default=30.0, gt=0)
    max_tools_per_server: int = Field(default=5000, ge=1)


class ModelRef(_Strict):
    model: str
    revision: str


class RerankerConfig(ModelRef):
    candidates: int = Field(default=30, ge=1)


class RRFConfig(_Strict):
    constant: int = Field(default=60, ge=1)
    weights: list[float] = Field(default_factory=lambda: [1.0, 1.0])


class SearchConfig(_Strict):
    default_k: int = Field(default=8, ge=1)
    max_k: int = Field(default=50, ge=1)
    compact: bool = False

    @model_validator(mode="after")
    def _k_order(self) -> SearchConfig:
        if self.default_k > self.max_k:
            raise ValueError("search.default_k must not exceed search.max_k")
        return self


class RetrievalConfig(_Strict):
    retriever: Literal["random", "bm25", "dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"
    text_repr: Literal["name", "name_desc", "name_desc_params"] = "name_desc"
    with_expansion: bool = False
    embedding: ModelRef | None = None
    reranker: RerankerConfig | None = None
    rrf: RRFConfig = Field(default_factory=RRFConfig)
    depth: int = Field(default=100, ge=1)
    search: SearchConfig = Field(default_factory=SearchConfig)


class CacheConfig(_Strict):
    entries: int = Field(default=256, ge=0)
    ttl_s: float = Field(default=600, ge=0)


class PolicyConfig(_Strict):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class GatewayConfig(_Strict):
    transport: Literal["stdio", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    mcp_path: str = "/mcp"
    call_timeout_s: float = Field(default=60, gt=0)
    refresh_debounce_s: float = Field(default=2, ge=0)
    max_result_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    per_upstream_concurrency: int = Field(default=8, ge=1)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)


class PriceConfig(_Strict):
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None


class LLMConfig(_Strict):
    provider: str | None = None  # open decision Q4
    model: str | None = None
    cache_dir: Path = Path("data/llm_cache")
    budget_usd: float = Field(default=50, ge=0)
    prices: dict[str, PriceConfig] = Field(default_factory=dict)


class DatasetConfig(_Strict):
    near_duplicate_threshold: float = Field(default=0.85, ge=0, le=1)
    leakage_threshold: float | None = Field(default=None, ge=0, le=1)  # open decision Q16
    second_review_fraction: float = Field(default=0.2, ge=0, le=1)
    dev_ratio: float = Field(default=0.6, gt=0, lt=1)


class EvaluationConfig(_Strict):
    candidate_sizes: list[int] = Field(default_factory=lambda: [50, 200, 1000])
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3])
    bootstrap_resamples: int = Field(default=1000, ge=1)
    repeats: int = Field(default=3, ge=1)
    max_turns: int = Field(default=6, ge=1)
    near_duplicate_fraction: float = Field(default=0.2, ge=0, le=1)


class LoggingConfig(_Strict):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_queries: bool = False

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v


class Config(_Strict):
    config_version: Literal[1] = CONFIG_VERSION
    data_dir: Path = Path("data")
    db_path: Path = Path("data/mcpgw.sqlite")
    index_dir: Path = Path("indexes")
    upstreams: list[UpstreamConfig] = Field(default_factory=list)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def _unique_aliases(self) -> Config:
        seen: set[str] = set()
        for u in self.upstreams:
            if u.alias in seen:
                raise ValueError(f"duplicate upstream alias {u.alias!r}")
            seen.add(u.alias)
        return self

    def upstream(self, alias: str) -> UpstreamConfig:
        for u in self.upstreams:
            if u.alias == alias:
                return u
        raise ConfigError(f"unknown upstream alias {alias!r}")

    def timeout_for(self, upstream: UpstreamConfig) -> float:
        return upstream.timeout_s if upstream.timeout_s is not None else self.ingest.timeout_s


def _set_path(tree: dict[str, Any], keys: list[str], value: Any) -> None:
    node = tree
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """Collect ``MCPGW_<SECTION>__<KEY>=value`` overrides. Values are parsed as YAML scalars,
    so ``9000`` becomes an int and ``true`` a bool."""
    out: dict[str, Any] = {}
    shortcuts = {
        "MCPGW_DB_PATH": ["db_path"],
        "MCPGW_INDEX_DIR": ["index_dir"],
        "MCPGW_LOG_LEVEL": ["logging", "level"],
    }
    for name, path in shortcuts.items():
        if name in env:
            _set_path(out, path, env[name])
    for name, raw in env.items():
        if not name.startswith(ENV_PREFIX) or "__" not in name:
            continue
        keys = [k.lower() for k in name[len(ENV_PREFIX) :].split("__")]
        if not all(keys) or keys[0] == "upstreams":
            continue  # upstreams is a list; override it in the file instead
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError:
            value = raw
        _set_path(out, keys, value)
    return out


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve_paths(cfg: Config, base: Path) -> Config:
    def r(p: Path) -> Path:
        return p if p.is_absolute() else (base / p).resolve()

    llm = cfg.llm.model_copy(update={"cache_dir": r(cfg.llm.cache_dir)})
    ups = [u.model_copy(update={"cwd": r(u.cwd)}) if u.cwd else u for u in cfg.upstreams]
    return cfg.model_copy(
        update={
            "data_dir": r(cfg.data_dir),
            "db_path": r(cfg.db_path),
            "index_dir": r(cfg.index_dir),
            "llm": llm,
            "upstreams": ups,
        }
    )


def _format_validation_error(source: str, err: ValidationError) -> str:
    lines = [f"invalid configuration in {source}:"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        lines.append(f"  {loc}: {e['msg']}")
    return "\n".join(lines)


def parse_config(
    data: Mapping[str, Any],
    *,
    base_dir: Path,
    env: Mapping[str, str] | None = None,
    source: str = "<config>",
) -> Config:
    merged = _merge(dict(data), _env_overrides(os.environ if env is None else env))
    try:
        cfg = Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(_format_validation_error(source, e)) from e
    return _resolve_paths(cfg, base_dir)


def load_config(path: Path | None = None, *, env: Mapping[str, str] | None = None) -> Config:
    """Load and validate the config file. ``path`` defaults to ``$MCPGW_CONFIG`` or
    ``./mcpgw.yaml``."""
    environ = os.environ if env is None else env
    if path is None:
        path = Path(environ.get("MCPGW_CONFIG", DEFAULT_CONFIG_PATH))
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    if data.get("config_version") != CONFIG_VERSION:
        raise ConfigError(
            f"{path}: config_version must be {CONFIG_VERSION}, got {data.get('config_version')!r}"
        )
    return parse_config(data, base_dir=path.parent.resolve(), env=environ, source=str(path))


def resolve_secret_env(mapping: Mapping[str, str], env: Mapping[str, str]) -> dict[str, str]:
    """Turn ``{target_name: host_var_name}`` into ``{target_name: value}`` at connect time.

    The values are only ever held in memory and passed to the upstream (FR-1.6)."""
    out: dict[str, str] = {}
    missing = [host for host in mapping.values() if host not in env]
    if missing:
        raise ConfigError(f"missing environment variable(s): {', '.join(sorted(set(missing)))}")
    for target, host in mapping.items():
        out[target] = env[host]
    return out
