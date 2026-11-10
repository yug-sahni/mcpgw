"""M1 ingestion: list every upstream's tools and store them as one snapshot (SRS 6.1).

Each server is ingested independently with bounded concurrency and its own timeout; one
failing server never aborts the others (FR-1.5). Secrets are resolved at connect time,
used only in memory and redacted from error messages (FR-1.7).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import anyio

from mcpgw.config import Config, UpstreamConfig, resolve_secret_env
from mcpgw.contracts.errors import ConfigError, IngestError
from mcpgw.contracts.records import ToolRecord
from mcpgw.ingestion.models import ServerResult
from mcpgw.ingestion.normalize import normalise_all
from mcpgw.ingestion.session import Connector, connect_mcp
from mcpgw.registry import Registry, SnapshotDiff, WriteSummary

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REDACTED = "***"


class IngestFailed(IngestError):
    """No snapshot was written; ``results`` says why for each server."""

    def __init__(self, message: str, results: list[ServerResult]) -> None:
        super().__init__(message)
        self.results = results


def redact(message: str, secrets: Sequence[str]) -> str:
    for s in sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True):
        message = message.replace(s, _REDACTED)
    return message


def _describe(exc: BaseException) -> str:
    """Readable one-line error, unwrapping the exception groups that anyio task groups raise."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def ingest_server(
    upstream: UpstreamConfig,
    config: Config,
    *,
    connector: Connector = connect_mcp,
    env: Mapping[str, str] | None = None,
) -> ServerResult:
    """Ingest one upstream. Never raises for upstream problems; returns status ``failed``."""
    environ = os.environ if env is None else env
    timeout = config.timeout_for(upstream)
    limits = config.ingest
    started = time.monotonic()
    result = ServerResult(alias=upstream.alias, transport=upstream.transport, status="failed")
    secrets: dict[str, str] = {}
    try:
        mapping = upstream.env if upstream.transport == "stdio" else upstream.headers_env
        secrets = resolve_secret_env(mapping, environ)
        tools = []
        with anyio.fail_after(timeout):
            async with connector(upstream, secrets, timeout) as session:
                cursor: str | None = None
                seen_cursors: set[str] = set()
                while True:
                    page = await session.list_tools_page(cursor)
                    result.pages += 1
                    tools.extend(page.tools)
                    cursor = page.next_cursor
                    if not cursor:
                        break
                    if result.pages >= limits.max_pages:
                        result.warnings.append(
                            f"stopped at the page cap ({limits.max_pages}); listing may be "
                            "incomplete"
                        )
                        break
                    if cursor in seen_cursors:
                        result.warnings.append(f"server repeated cursor {cursor!r}; stopped")
                        break
                    seen_cursors.add(cursor)
                    if len(tools) >= limits.max_tools_per_server:
                        break
                result.info = session.info
        if len(tools) > limits.max_tools_per_server:
            result.warnings.append(
                f"kept the first {limits.max_tools_per_server} of {len(tools)} tools"
            )
            tools = tools[: limits.max_tools_per_server]
        records, warnings = normalise_all(upstream.alias, tools)
        result.records = records
        result.warnings.extend(warnings)
        result.status = "ok"
    except ConfigError as e:
        result.error = e.message
    except TimeoutError:
        result.error = f"timed out after {timeout:g}s"
    except Exception as e:
        result.error = redact(_describe(e), list(secrets.values()))
    finally:
        result.elapsed_s = time.monotonic() - started
    if result.status != "ok":
        result.records = []
    return result


async def ingest_all(
    config: Config,
    *,
    servers: Sequence[str] | None = None,
    connector: Connector = connect_mcp,
    env: Mapping[str, str] | None = None,
) -> list[ServerResult]:
    """Ingest every configured upstream (or only ``servers``); results keep config order.

    Upstreams excluded by ``servers`` are reported as ``skipped``."""
    if servers is not None:
        unknown = sorted(set(servers) - {u.alias for u in config.upstreams})
        if unknown:
            raise ConfigError(f"unknown upstream alias(es): {', '.join(unknown)}")
    selected = set(servers) if servers is not None else None
    results: list[ServerResult | None] = [None] * len(config.upstreams)
    limiter = anyio.CapacityLimiter(config.ingest.concurrency)

    async def run(i: int, u: UpstreamConfig) -> None:
        async with limiter:
            results[i] = await ingest_server(u, config, connector=connector, env=env)

    async with anyio.create_task_group() as tg:
        for i, u in enumerate(config.upstreams):
            if selected is not None and u.alias not in selected:
                results[i] = ServerResult(alias=u.alias, transport=u.transport, status="skipped")
            else:
                tg.start_soon(run, i, u)
    return [r for r in results if r is not None]


@dataclass
class IngestReport:
    results: list[ServerResult]
    summary: WriteSummary
    diff: SnapshotDiff | None
    export: dict[str, object]
    export_path: Path

    @property
    def records(self) -> list[ToolRecord]:
        return [rec for r in self.results for rec in r.records]


def validate_label(label: str) -> str:
    if not LABEL_RE.fullmatch(label):
        raise ConfigError(
            f"invalid snapshot label {label!r}: use letters, digits, '.', '_' or '-' (max 64)"
        )
    return label


async def run_ingest(
    config: Config,
    label: str,
    *,
    strict: bool = False,
    servers: Sequence[str] | None = None,
    connector: Connector = connect_mcp,
    env: Mapping[str, str] | None = None,
    registry: Registry | None = None,
) -> IngestReport:
    """Ingest, write the snapshot atomically, export canonical JSONL and diff (FR-1.8, FR-1.9).

    Raises ``IngestError`` (exit code 3) when no server succeeded, or with ``strict`` when any
    selected server failed; nothing is written in that case."""
    validate_label(label)
    results = await ingest_all(config, servers=servers, connector=connector, env=env)
    attempted = [r for r in results if r.status != "skipped"]
    ok = [r for r in attempted if r.status == "ok"]
    if not ok:
        raise IngestFailed(
            "no upstream server was ingested successfully; no snapshot written", results
        )
    if strict and len(ok) < len(attempted):
        failed = ", ".join(r.alias for r in attempted if r.status != "ok")
        raise IngestFailed(f"--strict: server(s) failed: {failed}; no snapshot written", results)

    own = registry is None
    reg = registry or Registry(config.db_path)
    try:
        previous = reg.latest_snapshot()
        summary = reg.write_snapshot(label, results)
        export_path = config.data_dir / "snapshots" / f"{label}.jsonl"
        export = reg.export_snapshot(summary.snapshot.snapshot_id, export_path)
        diff = reg.diff(previous.snapshot_id, summary.snapshot.snapshot_id) if previous else None
    finally:
        if own:
            reg.close()
    return IngestReport(results, summary, diff, export, export_path)
