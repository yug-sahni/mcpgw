"""Command-line interface (contract D). Errors map to the exit codes in ``contracts.errors``."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import anyio
import typer

from mcpgw.contracts.errors import ExitCode, GatewayError
from mcpgw.ingestion.models import ServerResult

app = typer.Typer(help="MCP Tool Retrieval Gateway", no_args_is_help=True)
snapshot_app = typer.Typer(help="Inspect stored snapshots.", no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")

ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Config file (default: $MCPGW_CONFIG or ./mcpgw.yaml)."),
]


def _fail(err: GatewayError) -> typer.Exit:
    typer.secho(f"error: {err.message}", err=True, fg=typer.colors.RED)
    return typer.Exit(err.exit_code)


def _print_server_results(results: Sequence[ServerResult]) -> None:
    for r in results:
        color = {"ok": typer.colors.GREEN, "failed": typer.colors.RED}.get(r.status)
        line = f"  {r.alias:<20} {r.status:<8} {len(r.records):>5} tools  {r.elapsed_s:6.2f}s"
        if r.info.name:
            line += f"  {r.info.name} {r.info.version or ''}".rstrip()
        typer.secho(line, fg=color)
        if r.error:
            typer.secho(f"      error: {r.error}", fg=typer.colors.RED)
        for w in r.warnings:
            typer.secho(f"      warning: {w}", fg=typer.colors.YELLOW)


@app.command()
def version() -> None:
    """Print the package version."""
    from mcpgw import __version__

    typer.echo(__version__)


@app.command()
def ingest(
    label: Annotated[str, typer.Option("--label", "-l", help="Unique snapshot label.")],
    config: ConfigOpt = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Fail (and write nothing) if any server fails.")
    ] = False,
    servers: Annotated[
        list[str] | None,
        typer.Option("--servers", "-s", help="Only ingest these aliases (repeatable)."),
    ] = None,
) -> None:
    """List tools from every upstream and store them as a new snapshot."""
    from mcpgw.config import load_config
    from mcpgw.ingestion.ingest import IngestFailed, run_ingest

    try:
        cfg = load_config(config)
        report = anyio.run(lambda: run_ingest(cfg, label, strict=strict, servers=servers or None))
    except IngestFailed as e:
        _print_server_results(e.results)
        raise _fail(e) from e
    except GatewayError as e:
        raise _fail(e) from e
    except KeyboardInterrupt:
        raise typer.Exit(ExitCode.INTERRUPTED) from None

    _print_server_results(report.results)

    snap = report.summary.snapshot
    partial = " (partial)" if snap.is_partial else ""
    typer.echo(
        f"snapshot {snap.label!r}{partial}: {snap.tool_count} tools, "
        f"{report.summary.new_versions} new versions"
    )
    typer.echo(f"exported {report.export_path} sha256={report.export['sha256']}")
    if report.diff is not None:
        d = report.diff
        typer.echo(
            f"diff vs previous: +{len(d.added)} -{len(d.removed)} ~{len(d.changed)} "
            f"?{len(d.unknown)} (unknown: tools of servers that did not succeed)"
        )


@snapshot_app.command("list")
def snapshot_list(config: ConfigOpt = None) -> None:
    """List snapshots, oldest first."""
    from mcpgw.config import load_config
    from mcpgw.registry import Registry

    try:
        cfg = load_config(config)
        with Registry(cfg.db_path) as reg:
            snaps = reg.list_snapshots()
    except GatewayError as e:
        raise _fail(e) from e
    if not snaps:
        typer.echo("no snapshots")
        return
    for s in snaps:
        partial = "partial" if s.is_partial else ""
        typer.echo(
            f"{s.snapshot_id:>4}  {s.label:<24} {s.created_at}  {s.tool_count:>5} tools  {partial}"
        )
