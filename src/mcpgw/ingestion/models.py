"""Data passed between the upstream session, ingestion (M1) and the registry (M2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mcpgw.contracts.records import ToolRecord

ServerStatus = Literal["ok", "failed", "skipped"]
Transport = Literal["stdio", "streamable_http", "synthetic"]


@dataclass(frozen=True)
class RawTool:
    """A tool exactly as an upstream listed it. Fields are ``Any`` because upstreams send
    malformed data (missing descriptions, non-object schemas) that normalisation must flag."""

    name: Any
    title: Any = None
    description: Any = None
    input_schema: Any = None
    output_schema: Any = None
    annotations: Any = None


@dataclass(frozen=True)
class ToolPage:
    tools: list[RawTool]
    next_cursor: str | None = None


@dataclass(frozen=True)
class ServerInfo:
    name: str | None = None
    version: str | None = None
    protocol_version: str | None = None


@dataclass
class ServerResult:
    """Outcome of ingesting one upstream (FR-1.5, FR-1.11)."""

    alias: str
    transport: Transport
    status: ServerStatus
    records: list[ToolRecord] = field(default_factory=list)
    info: ServerInfo = field(default_factory=ServerInfo)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    elapsed_s: float = 0.0


@dataclass(frozen=True)
class Param:
    """One parameter extracted from an ``inputSchema`` (FR-1.6)."""

    path: str
    json_type: str | None
    is_required: bool
    description: str | None
