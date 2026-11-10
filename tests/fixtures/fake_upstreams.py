"""In-process fake upstreams for ingestion tests (SRS 7.2).

``FakeUpstream`` stands in for an initialised MCP session; ``connector(...)`` maps aliases to
fakes and plugs into ``ingest_server`` / ``run_ingest`` in place of the real SDK connector.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio

from mcpgw.config import UpstreamConfig
from mcpgw.ingestion.models import RawTool, ServerInfo, ToolPage
from mcpgw.ingestion.session import Connector, UpstreamSession


def object_schema(**props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": sorted(props)[:1]}


@dataclass
class FakeUpstream:
    tools: list[RawTool]
    page_size: int | None = None
    endless_cursor: bool = False
    delay_s: float = 0.0
    fail_on_connect: Exception | None = None
    fail_on_page: int | None = None  # 1-based page that raises mid-listing ("crashy")
    info: ServerInfo = field(
        default_factory=lambda: ServerInfo(
            name="fake", version="1.0", protocol_version="2025-11-25"
        )
    )
    calls: int = 0
    seen_secrets: dict[str, str] = field(default_factory=dict)

    async def list_tools_page(self, cursor: str | None) -> ToolPage:
        self.calls += 1
        if self.delay_s:
            await anyio.sleep(self.delay_s)
        if self.fail_on_page is not None and self.calls >= self.fail_on_page:
            raise ConnectionResetError("server exited in the middle of a call")
        start = int(cursor) if cursor else 0
        size = self.page_size or len(self.tools) or 1
        page = self.tools[start : start + size]
        end = start + size
        if self.endless_cursor:
            return ToolPage(page, next_cursor=str(end))
        return ToolPage(page, next_cursor=str(end) if end < len(self.tools) else None)


def connector(fakes: Mapping[str, FakeUpstream]) -> Connector:
    @asynccontextmanager
    async def connect(
        upstream: UpstreamConfig, secrets: Mapping[str, str], timeout_s: float
    ) -> AsyncIterator[UpstreamSession]:
        fake = fakes[upstream.alias]
        fake.seen_secrets = dict(secrets)
        if fake.fail_on_connect is not None:
            raise fake.fail_on_connect
        yield fake

    return connect


# -- canned tool sets ---------------------------------------------------------------------------

BASIC_TOOLS: Callable[[], list[RawTool]] = lambda: [  # noqa: E731
    RawTool(
        name=f"tool_{i:02d}",
        title=f"Tool {i}",
        description=f"Does thing number {i}.",
        input_schema=object_schema(arg={"type": "string", "description": f"argument {i}"}),
        annotations={"readOnlyHint": i % 2 == 0},
    )
    for i in range(10)
]


def malformed_tools() -> list[RawTool]:
    return [
        RawTool(name="no_desc", description=None, input_schema=object_schema()),
        RawTool(name="blank_desc", description="   ", input_schema=object_schema()),
        RawTool(name="bad_schema", description="Schema is a list.", input_schema=["nope"]),
        RawTool(
            name="not_object", description="Schema type string.", input_schema={"type": "string"}
        ),
        RawTool(name="missing_schema", description="No schema at all.", input_schema=None),
        RawTool(name="dupe", description="First definition.", input_schema=object_schema()),
        RawTool(name="dupe", description="Second definition.", input_schema=object_schema()),
        RawTool(name="huge", description="x" * 30_000, input_schema=object_schema()),
        RawTool(
            name="ctrl",
            description="Bell\x07 and\x00 nul\r\nkept\ttab",
            input_schema=object_schema(),
        ),
        RawTool(name="", description="Nameless."),
    ]
