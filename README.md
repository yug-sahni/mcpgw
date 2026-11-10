# mcpgw: MCP Tool Retrieval Gateway

Query-aware tool retrieval for agents connected to many MCP servers. The gateway indexes tools
from upstream servers and exposes only the tools relevant to a natural-language query.

Goals: efficiency (fewer tool tokens), accuracy (relevant tools retrieved), scalability.
Task success is *measured*, not assumed.

## Develop
```bash
uv sync
make check
```
See `docs/adr/` for interface decisions.
