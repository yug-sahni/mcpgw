# ADR 0001: Shared interfaces and contracts

Status: accepted. Date: 2026-11-10.

## Context
Two developers work in parallel. Workstream A owns retrieval, benchmark and evaluation.
Workstream B owns ingestion, registry, gateway and CLI. They meet only at the contracts below.

## Decision
All shared types live in `mcpgw.contracts`. Both developers must review any change to it.

- `ToolRecord`: one tool from one upstream server. `qualified_name = <alias>__<name>`; alias matches
  `[a-z0-9-]{1,32}` (no underscore, so the first `__` splits unambiguously).
  `content_hash` is SHA-256 of canonical JSON (sorted keys, compact separators, UTF-8, NFC strings)
  over name, title, description, inputSchema, outputSchema, annotations.
- Snapshots: JSONL sorted by `qualified_name`, plus a manifest (count, sha256).
- `Retriever.retrieve(query, k, filter) -> RetrievalResult` (A implements, B consumes).
- `ToolSelector.select(query, k, servers) -> SelectionResult` (harness mode).
- `LLMClient.complete(...)` and `generate(prompt)`; provider-neutral.
- `QueryRecord`: `gold` is a list of groups of interchangeable qualified names; all groups must be hit.
- Errors: `GatewayError` subclasses map to exit codes 0/1/2/3/4/5/130 and to tool error codes.

## Consequences
Each side can mock the other from these types. Breaking changes need an ADR amendment.
