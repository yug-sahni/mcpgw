-- Migration 0001: reference schema from SRS Part 4.2.
-- Timestamps are ISO 8601 UTC text. Boolean columns are 0 or 1.
-- PRAGMAs (foreign_keys, WAL, busy_timeout) are set per connection by mcpgw.registry.db;
-- schema_version is created and maintained by the migration runner.

-- Catalog tables (M2) -------------------------------------------------------

CREATE TABLE server (
    server_id    INTEGER PRIMARY KEY,
    alias        TEXT NOT NULL UNIQUE
                 CHECK (length(alias) BETWEEN 1 AND 32 AND alias NOT GLOB '*[^a-z0-9-]*'),
    transport    TEXT NOT NULL CHECK (transport IN ('stdio','streamable_http','synthetic')),
    is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    source_url   TEXT,
    license      TEXT,
    created_at   TEXT NOT NULL,
    CHECK ((transport = 'synthetic') = (is_synthetic = 1))
);

CREATE TABLE snapshot (
    snapshot_id          INTEGER PRIMARY KEY,
    label                TEXT NOT NULL UNIQUE,
    created_at           TEXT NOT NULL,
    mcp_protocol_version TEXT,
    is_partial           INTEGER NOT NULL DEFAULT 0 CHECK (is_partial IN (0,1)),
    jsonl_sha256         TEXT,
    notes                TEXT
);

CREATE TABLE snapshot_server (
    snapshot_id      INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
    server_id        INTEGER NOT NULL REFERENCES server(server_id),
    status           TEXT NOT NULL CHECK (status IN ('ok','failed','skipped')),
    tool_count       INTEGER NOT NULL DEFAULT 0 CHECK (tool_count >= 0),
    server_name      TEXT,
    server_version   TEXT,
    protocol_version TEXT,
    error_message    TEXT,
    PRIMARY KEY (snapshot_id, server_id)
);

CREATE TABLE tool (
    tool_id        INTEGER PRIMARY KEY,
    server_id      INTEGER NOT NULL REFERENCES server(server_id),
    name           TEXT NOT NULL CHECK (length(name) > 0),
    qualified_name TEXT NOT NULL UNIQUE, -- alias || '__' || name, written once at insert
    UNIQUE (server_id, name)
);

CREATE TABLE tool_version (
    tool_version_id INTEGER PRIMARY KEY,
    tool_id         INTEGER NOT NULL REFERENCES tool(tool_id),
    content_hash    TEXT NOT NULL CHECK (length(content_hash) = 64),
    title           TEXT,
    description     TEXT NOT NULL DEFAULT '',
    input_schema    TEXT NOT NULL CHECK (json_valid(input_schema)),
    output_schema   TEXT CHECK (output_schema IS NULL OR json_valid(output_schema)),
    annotations     TEXT CHECK (annotations IS NULL OR json_valid(annotations)),
    flags           TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(flags)),
    first_seen_at   TEXT NOT NULL,
    UNIQUE (tool_id, content_hash),
    UNIQUE (tool_version_id, tool_id) -- target of composite foreign keys
);

CREATE TABLE snapshot_tool (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
    tool_id         INTEGER NOT NULL,
    tool_version_id INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, tool_id),
    FOREIGN KEY (tool_version_id, tool_id) REFERENCES tool_version(tool_version_id, tool_id)
);

CREATE TABLE tool_param (
    param_id        INTEGER PRIMARY KEY,
    tool_version_id INTEGER NOT NULL REFERENCES tool_version(tool_version_id),
    path            TEXT NOT NULL, -- dotted path, depth <= 2
    json_type       TEXT,
    is_required     INTEGER NOT NULL CHECK (is_required IN (0,1)),
    description     TEXT,
    UNIQUE (tool_version_id, path)
);

CREATE TABLE tool_expansion (
    expansion_id    INTEGER PRIMARY KEY,
    tool_version_id INTEGER NOT NULL REFERENCES tool_version(tool_version_id),
    kind            TEXT NOT NULL CHECK (kind IN ('hypothetical_query','rewritten_description')),
    text            TEXT NOT NULL CHECK (length(trim(text)) > 0),
    generator_model TEXT NOT NULL,
    prompt_sha256   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE corpus (
    corpus_id             INTEGER PRIMARY KEY,
    real_snapshot_id      INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
    synthetic_snapshot_id INTEGER REFERENCES snapshot(snapshot_id),
    target_size           INTEGER NOT NULL CHECK (target_size > 0),
    seed                  INTEGER NOT NULL,
    purpose               TEXT NOT NULL CHECK (purpose IN ('live','eval')),
    members_sha256        TEXT NOT NULL UNIQUE, -- content-addressed
    created_at            TEXT NOT NULL
);

CREATE TABLE corpus_tool (
    corpus_id       INTEGER NOT NULL REFERENCES corpus(corpus_id) ON DELETE CASCADE,
    tool_id         INTEGER NOT NULL,
    tool_version_id INTEGER NOT NULL,
    PRIMARY KEY (corpus_id, tool_id),
    FOREIGN KEY (tool_version_id, tool_id) REFERENCES tool_version(tool_version_id, tool_id)
);

CREATE TABLE index_build (
    index_id        INTEGER PRIMARY KEY,
    corpus_id       INTEGER NOT NULL REFERENCES corpus(corpus_id),
    kind            TEXT NOT NULL CHECK (kind IN ('bm25','dense','dep_graph')),
    text_repr       TEXT NOT NULL CHECK (text_repr IN ('name','name_desc','name_desc_params')),
    with_expansion  INTEGER NOT NULL DEFAULT 0 CHECK (with_expansion IN (0,1)),
    embedding_model TEXT NOT NULL DEFAULT '',
    model_revision  TEXT NOT NULL DEFAULT '',
    params          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(params)), -- canonical JSON
    artifact_path   TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    built_at        TEXT NOT NULL,
    UNIQUE (corpus_id, kind, text_repr, with_expansion, embedding_model, model_revision, params)
);

-- Benchmark tables (M6) -----------------------------------------------------

CREATE TABLE dataset_release (
    dataset_id     INTEGER PRIMARY KEY,
    label          TEXT NOT NULL UNIQUE,
    snapshot_id    INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
    frozen_at      TEXT, -- NULL while a draft
    jsonl_sha256   TEXT,
    datasheet_path TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE query (
    query_id         INTEGER PRIMARY KEY,
    dataset_id       INTEGER NOT NULL REFERENCES dataset_release(dataset_id),
    text             TEXT NOT NULL CHECK (length(trim(text)) > 0),
    vagueness        TEXT NOT NULL CHECK (vagueness IN ('named','action','goal')),
    is_multi_tool    INTEGER NOT NULL DEFAULT 0 CHECK (is_multi_tool IN (0,1)),
    targets_near_dup INTEGER NOT NULL DEFAULT 0 CHECK (targets_near_dup IN (0,1)),
    split            TEXT CHECK (split IN ('dev','test')),
    status           TEXT NOT NULL DEFAULT 'candidate'
                     CHECK (status IN ('candidate','accepted','rejected')),
    generator_model  TEXT,
    prompt_sha256    TEXT,
    leakage_score    REAL CHECK (leakage_score IS NULL OR (leakage_score BETWEEN 0 AND 1)),
    reviewed_by      TEXT,
    reviewed_at      TEXT,
    UNIQUE (dataset_id, text)
);

CREATE TABLE query_gold_tool (
    query_id   INTEGER NOT NULL REFERENCES query(query_id),
    tool_id    INTEGER NOT NULL REFERENCES tool(tool_id),
    gold_group INTEGER NOT NULL DEFAULT 0 CHECK (gold_group >= 0),
    PRIMARY KEY (query_id, tool_id)
);

-- Result tables (M7) --------------------------------------------------------

CREATE TABLE eval_run (
    run_id           INTEGER PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('retrieval','latency','e2e')),
    dataset_id       INTEGER NOT NULL REFERENCES dataset_release(dataset_id),
    corpus_id        INTEGER NOT NULL REFERENCES corpus(corpus_id),
    split            TEXT NOT NULL CHECK (split IN ('dev','test')),
    is_final         INTEGER NOT NULL DEFAULT 0 CHECK (is_final IN (0,1)),
    retriever_config TEXT NOT NULL CHECK (json_valid(retriever_config)),
    config_sha256    TEXT NOT NULL,
    git_sha          TEXT NOT NULL,
    seed             INTEGER NOT NULL,
    status           TEXT NOT NULL
                     CHECK (status IN ('running','completed','failed','incomplete')),
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    UNIQUE (kind, dataset_id, corpus_id, split, config_sha256, seed),
    CHECK (split = 'dev' OR is_final = 1) -- test-split runs must be marked final
);

CREATE TABLE eval_ranking (
    run_id   INTEGER NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
    query_id INTEGER NOT NULL REFERENCES query(query_id),
    rank     INTEGER NOT NULL CHECK (rank >= 1),
    tool_id  INTEGER NOT NULL REFERENCES tool(tool_id),
    score    REAL,
    PRIMARY KEY (run_id, query_id, rank)
);

CREATE TABLE eval_metric (
    metric_id INTEGER PRIMARY KEY,
    run_id    INTEGER NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
    query_id  INTEGER REFERENCES query(query_id), -- NULL = aggregate over queries
    metric    TEXT NOT NULL, -- recall, mrr, ndcg, all_gold, latency_ms, ...
    k         INTEGER NOT NULL DEFAULT 0, -- 0 when k does not apply
    value     REAL NOT NULL,
    ci_low    REAL,
    ci_high   REAL
);

CREATE UNIQUE INDEX eval_metric_aggregate ON eval_metric(run_id, metric, k)
    WHERE query_id IS NULL;
CREATE UNIQUE INDEX eval_metric_per_query ON eval_metric(run_id, query_id, metric, k)
    WHERE query_id IS NOT NULL;

CREATE TABLE e2e_trial (
    trial_id         INTEGER PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
    query_id         INTEGER NOT NULL REFERENCES query(query_id),
    mode             TEXT NOT NULL CHECK (mode IN ('all_tools','meta_tool','preselect')),
    repeat_idx       INTEGER NOT NULL DEFAULT 0 CHECK (repeat_idx >= 0),
    llm_model        TEXT NOT NULL,
    tools_in_context INTEGER NOT NULL CHECK (tools_in_context >= 0),
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    tool_def_tokens  INTEGER,
    latency_ms       REAL,
    cost_usd         REAL, -- NULL when no price is configured
    success          INTEGER CHECK (success IN (0,1)),
    failure_reason   TEXT,
    UNIQUE (run_id, query_id, mode, repeat_idx)
);

CREATE TABLE e2e_tool_call (
    trial_id       INTEGER NOT NULL REFERENCES e2e_trial(trial_id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,
    tool_id        INTEGER REFERENCES tool(tool_id), -- NULL if the name did not resolve
    requested_name TEXT NOT NULL,
    arguments      TEXT CHECK (arguments IS NULL OR json_valid(arguments)),
    schema_valid   INTEGER CHECK (schema_valid IN (0,1)),
    PRIMARY KEY (trial_id, seq)
);

-- Lookup indexes ------------------------------------------------------------

CREATE INDEX idx_tool_server       ON tool(server_id);
CREATE INDEX idx_version_tool      ON tool_version(tool_id);
CREATE INDEX idx_snapshot_tool_ver ON snapshot_tool(tool_version_id);
CREATE INDEX idx_param_version     ON tool_param(tool_version_id);
CREATE INDEX idx_expansion_version ON tool_expansion(tool_version_id, kind);
CREATE INDEX idx_index_corpus      ON index_build(corpus_id, kind);
CREATE INDEX idx_query_release     ON query(dataset_id, split, status);
CREATE INDEX idx_gold_tool         ON query_gold_tool(tool_id);
CREATE INDEX idx_run_lookup        ON eval_run(dataset_id, corpus_id, kind);
CREATE INDEX idx_ranking_tool      ON eval_ranking(tool_id);
CREATE INDEX idx_trial_run         ON e2e_trial(run_id, mode);

-- Immutability triggers -----------------------------------------------------

CREATE TRIGGER server_alias_immutable BEFORE UPDATE OF alias ON server
BEGIN SELECT RAISE(ABORT, 'server.alias is immutable'); END;

CREATE TRIGGER tool_version_no_update BEFORE UPDATE ON tool_version
BEGIN SELECT RAISE(ABORT, 'tool_version is immutable'); END;

CREATE TRIGGER tool_version_no_delete BEFORE DELETE ON tool_version
BEGIN SELECT RAISE(ABORT, 'tool_version is immutable'); END;

CREATE TRIGGER snapshot_tool_no_update BEFORE UPDATE ON snapshot_tool
BEGIN SELECT RAISE(ABORT, 'snapshot_tool is immutable'); END;

CREATE TRIGGER snapshot_tool_no_delete BEFORE DELETE ON snapshot_tool
BEGIN SELECT RAISE(ABORT, 'snapshot_tool is immutable'); END;

CREATE TRIGGER release_frozen_immutable BEFORE UPDATE ON dataset_release
WHEN OLD.frozen_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;

CREATE TRIGGER query_frozen_insert BEFORE INSERT ON query
WHEN (SELECT frozen_at FROM dataset_release WHERE dataset_id = NEW.dataset_id) IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;

CREATE TRIGGER query_frozen_update BEFORE UPDATE ON query
WHEN (SELECT frozen_at FROM dataset_release WHERE dataset_id = OLD.dataset_id) IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;

CREATE TRIGGER query_frozen_delete BEFORE DELETE ON query
WHEN (SELECT frozen_at FROM dataset_release WHERE dataset_id = OLD.dataset_id) IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;

CREATE TRIGGER gold_frozen_insert BEFORE INSERT ON query_gold_tool
WHEN (SELECT r.frozen_at FROM query q JOIN dataset_release r ON r.dataset_id = q.dataset_id
      WHERE q.query_id = NEW.query_id) IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;

CREATE TRIGGER gold_frozen_update BEFORE UPDATE ON query_gold_tool
WHEN (SELECT r.frozen_at FROM query q JOIN dataset_release r ON r.dataset_id = q.dataset_id
      WHERE q.query_id = OLD.query_id) IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;

CREATE TRIGGER gold_frozen_delete BEFORE DELETE ON query_gold_tool
WHEN (SELECT r.frozen_at FROM query q JOIN dataset_release r ON r.dataset_id = q.dataset_id
      WHERE q.query_id = OLD.query_id) IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'dataset release is frozen'); END;
