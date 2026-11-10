# Open decisions (SRS 2.1.6, Q1–Q17)

Every open question from the SRS with its recommended answer, an owner and the week by which it
must be settled (weeks follow the 8-week plan). Update the **Status** column as decisions are
made, and record anything that changes a shared contract in an ADR.

Owners follow the plan: **D1** = Developer 1 (ingestion, registry, indexer, retrieval, gateway,
engineering CLI); **D2** = Developer 2 (corpus, dataset, evaluation, reporting); **Both** = decide
together.

The SRS (11.4) names four decisions that **block the start of development**: Q1, Q2, Q4, Q14.

| ID | Decision | SRS recommendation | Owner | Decide by | Status |
|---|---|---|---|---|---|
| Q1 | Team size and schedule | Schedule-neutral; priorities follow the scope tiers | Both | Week 1 ⛔ | **Decided:** 2 developers, 8-week plan (drops 5,000-tool scale, fine-tuned retriever, poisoned-description detection) |
| Q2 | Which 10+ upstream servers | Credential-free servers plus 3–4 with free-tier tokens; at least 2 usable for the demo | D2 (D1 checks they ingest) | Week 1 ⛔ | Open. `mcpgw ingest` is ready to try candidates; record each server's license (see Q11) |
| Q3 | Embedding models | Two small open models pinned by revision: `all-MiniLM-L6-v2` and `bge-small-en-v1.5` | D1 | Week 2 (dense index in Week 3) | Open. Benchmark CPU speed on Windows early |
| Q4 | LLM provider, models and spend cap | Provider-agnostic wrapper, on-disk cache of every call, spend cap | D2 | Week 1 ⛔ | Open. `LLMClient` contract exists; `llm.budget_usd` defaults to 50 |
| Q5 | Definition of end-to-end task success | Simulated tool results with programmatic checks for all trials; real execution only in a small demo | D2 | Week 5 (E2E runs in Week 6) | Open |
| Q6 | How to synthesize distractor tools | LLM-generated, flagged `is_synthetic`, under synthetic servers | D2 | Week 2 (distractors start in Week 2) | Open. Schema already enforces the synthetic flag |
| Q7 | Transports and MCP spec revision | stdio MUST, streamable HTTP SHOULD; pin the latest stable spec revision at project start | D1 | Week 3 (gateway in Week 4) | **Partly done:** stdio ingestion works (MCP SDK 2.3.0, protocol `2025-11-25`); HTTP connector written but untested. Pin the revision in an ADR |
| Q8 | `search_tools` result format | Full schemas for k ≤ 10; compact mode behind a config flag | D1 | Week 3 | Open. `retrieval.search.compact` config key exists |
| Q9 | Expose retrieved tools via `tools/list_changed` (Mode C) | Exclude from v1; client support varies | D1 | Week 3 | Open (recommend: exclude) |
| Q10 | Dataset size and dev/test split | 200 queries, 60/40 dev/test, stratified by vagueness and multi-tool; queries sharing a gold tool stay together | D2 | Week 2 | Open. `dataset.dev_ratio` defaults to 0.6 |
| Q11 | Redistributing tool descriptions | Record each server's license; publish text only where permitted, otherwise IDs plus a fetch script | D2 | Week 7 (but record licenses from Week 1) | Open. `server.license` column exists |
| Q12 | Which novel method | Default to description expansion; decide after baseline error analysis on dev | Both | Week 5 | Open (by design, after baselines) |
| Q13 | Windows support | — | Both | CI setup | **Decided:** supported; CI runs Windows too. See [ADR 0002](adr/0002-windows-support.md) |
| Q14 | Do MCP-specific tool-retrieval benchmarks already exist? | Check the literature in the first week; adjust the contribution claim | D2 | Week 1 ⛔ | Open. Start with ToolBench/ToolLLM, RAG-MCP and provider "tool search" features |
| Q15 | Storage of data and results | git-lfs for small files; DVC if indexes or embeddings are versioned | Both | Week 2 (before large files land) | Open. `.gitattributes` already treats `*.sqlite` / `*.npy` as binary |
| Q16 | Leakage threshold between query and tool text | Pilot on 30 queries, then fix the threshold before generating at scale | D2 | Week 2 | Open. `dataset.leakage_threshold` is `null` until decided |
| Q17 | Token counting method | Provider-reported usage as primary; a local tokenizer only to attribute tokens to tool definitions | D2 | Week 5 | Open |

## Suggested agenda for the first call
1. Confirm Q1 and Q13 (already decided) and the owners above.
2. Decide the four blockers now if possible: **Q2** (shortlist), **Q4** (provider and spend cap), **Q14** (who checks the literature, by when).
3. Agree the quick ones with clear recommendations: **Q3, Q9, Q10, Q17**.
4. Leave Q12 until after baselines, by design.
