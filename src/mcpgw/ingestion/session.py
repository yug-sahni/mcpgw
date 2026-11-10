"""Upstream sessions: the only place ingestion touches the MCP SDK.

Ingestion depends on the small ``UpstreamSession`` protocol, so tests drive it with in-process
fakes and the SDK (v2 at the time of writing) can change without touching ingestion logic.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any, Protocol, TextIO

from mcpgw.config import UpstreamConfig
from mcpgw.ingestion.models import RawTool, ServerInfo, ToolPage


class UpstreamSession(Protocol):
    """An initialised connection to one upstream server."""

    @property
    def info(self) -> ServerInfo: ...

    async def list_tools_page(self, cursor: str | None) -> ToolPage: ...


# ``(upstream, resolved_secrets) -> async context manager yielding an initialised session``.
# ``resolved_secrets`` holds ``env`` values for stdio or header values for HTTP.
Connector = Callable[
    [UpstreamConfig, Mapping[str, str], float], AbstractAsyncContextManager[UpstreamSession]
]


def raw_tool_from_sdk(tool: Any) -> RawTool:
    """Map an SDK ``Tool`` (snake_case fields in SDK v2) to a ``RawTool``."""

    def get(*names: str) -> Any:
        for n in names:
            if hasattr(tool, n):
                return getattr(tool, n)
        return None

    def plain(v: Any) -> Any:
        return v.model_dump(mode="json", exclude_none=True) if hasattr(v, "model_dump") else v

    return RawTool(
        name=get("name"),
        title=get("title"),
        description=get("description"),
        input_schema=plain(get("input_schema", "inputSchema")),
        output_schema=plain(get("output_schema", "outputSchema")),
        annotations=plain(get("annotations")),
    )


class _SdkSession:
    def __init__(self, session: Any, info: ServerInfo) -> None:
        self._session = session
        self._info = info

    @property
    def info(self) -> ServerInfo:
        return self._info

    async def list_tools_page(self, cursor: str | None) -> ToolPage:
        from mcp import types

        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        result = await self._session.list_tools(params=params)
        return ToolPage(
            tools=[raw_tool_from_sdk(t) for t in result.tools],
            next_cursor=result.next_cursor or None,
        )


def _child_errlog(stack: AsyncExitStack) -> TextIO:
    """Where the upstream's stderr goes. A subprocess needs a real file descriptor, which
    ``sys.stderr`` lacks when a host captures it (test runners, embedding apps)."""
    try:
        sys.stderr.fileno()
        return sys.stderr
    except (AttributeError, OSError, ValueError):
        devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - closed by the stack
        stack.callback(devnull.close)
        return devnull


@asynccontextmanager
async def connect_mcp(
    upstream: UpstreamConfig, secrets: Mapping[str, str], timeout_s: float
) -> AsyncIterator[UpstreamSession]:
    """Open the transport, run ``initialize`` and yield a session (FR-1.2)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    from mcpgw import __version__

    client_info: Any = {"name": "mcpgw", "version": __version__}
    try:
        from mcp.types import Implementation

        client_info = Implementation(name="mcpgw", version=__version__)
    except ImportError:  # pragma: no cover - older SDKs
        pass

    async with AsyncExitStack() as stack:
        if upstream.transport == "stdio":
            assert upstream.command is not None  # enforced by UpstreamConfig
            params = StdioServerParameters(
                command=upstream.command,
                args=list(upstream.args),
                env=dict(secrets) or None,
                cwd=str(upstream.cwd) if upstream.cwd else None,
            )
            streams = await stack.enter_async_context(
                stdio_client(params, errlog=_child_errlog(stack))
            )
        else:
            assert upstream.url is not None
            import httpx2  # the SDK's HTTP client dependency

            # Built directly: the SDK's own helper lives in a private module.
            http = await stack.enter_async_context(
                httpx2.AsyncClient(
                    headers=dict(secrets),
                    timeout=httpx2.Timeout(timeout_s),
                    follow_redirects=True,
                )
            )
            streams = await stack.enter_async_context(
                streamable_http_client(upstream.url, http_client=http)
            )
        read, write = streams[0], streams[1]
        session = await stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=timeout_s, client_info=client_info)
        )
        init = await session.initialize()
        server = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
        info = ServerInfo(
            name=getattr(server, "name", None),
            version=getattr(server, "version", None),
            protocol_version=getattr(init, "protocol_version", None)
            or getattr(init, "protocolVersion", None),
        )
        yield _SdkSession(session, info)
