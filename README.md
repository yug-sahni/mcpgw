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

## Ingest tools (M1 + M2)
```bash
cp mcpgw.example.yaml mcpgw.yaml   # edit upstreams; secrets are named env vars, never values
uv run mcpgw ingest --label 2026-11-10
uv run mcpgw snapshot list
```
Each run stores an immutable snapshot in `data/mcpgw.sqlite` and exports canonical JSONL to
`data/snapshots/<label>.jsonl`. One failing server never blocks the others (the snapshot is marked
partial); `--strict` refuses to write unless every server succeeds, and `--servers` limits the run.

## Shared fixture
`tests/fixtures/data/sample_tools.jsonl` is a 12-tool, 4-server snapshot in contract-A format,
for building retrieval and evaluation code before real ingestion data exists. Regenerate it with
`uv run python -m tests.fixtures.sample_corpus`; a test fails if it goes stale.
