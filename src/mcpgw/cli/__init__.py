"""Command-line interface (owned by Developer 2, task B-CLI)."""

import typer

app = typer.Typer(help="MCP Tool Retrieval Gateway", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the package version."""
    from mcpgw import __version__

    typer.echo(__version__)
