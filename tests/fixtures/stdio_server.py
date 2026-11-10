"""A tiny real MCP server over stdio, used by the SDK integration test.

Run as ``python tests/fixtures/stdio_server.py``.
"""

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="fixture-server", version="0.0.1")


@server.tool(description="Echo the given text back.")
def echo(text: str) -> str:
    return text


@server.tool(description="Add two integers.")
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    server.run("stdio")
