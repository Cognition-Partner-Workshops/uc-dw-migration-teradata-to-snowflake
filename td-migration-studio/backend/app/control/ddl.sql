-- Control schema (database `ctl`). Applied idempotently at API startup.
-- Every migrated object's state lives here so runs are resumable and idempotent.
CREATE SCHEMA IF NOT EXISTS ctl;

CREATE TABLE IF NOT EXISTS ctl.plans (
    plan_id      TEXT PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status       TEXT NOT NULL DEFAULT 'draft',          -- draft | approved
    target_id    TEXT NOT NULL,
    target_mode  TEXT NOT NULL,
    plan_json    JSONB NOT NULL                          -- MigrationPlan
);

CREATE TABLE IF NOT EXISTS ctl.runs (
    run_id       TEXT PRIMARY KEY,
    plan_id      TEXT NOT NULL REFERENCES ctl.plans(plan_id),
    target_id    TEXT NOT NULL,
    target_mode  TEXT NOT NULL,
    status       TEXT NOT NULL,                          -- RunStatus
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    resumed_from TEXT,
    report_json  JSONB                                   -- RunReport (written at end of run)
);

-- One row per (run, table). `stage` follows contracts.models.Stage.
CREATE TABLE IF NOT EXISTS ctl.run_objects (
    run_id          TEXT NOT NULL REFERENCES ctl.runs(run_id),
    table_name      TEXT NOT NULL,
    target_table    TEXT NOT NULL,
    stage           TEXT NOT NULL DEFAULT 'pending',
    attempts        INT  NOT NULL DEFAULT 0,
    rows_extracted  BIGINT NOT NULL DEFAULT 0,
    rows_staged     BIGINT NOT NULL DEFAULT 0,
    rows_rejected   BIGINT NOT NULL DEFAULT 0,
    rows_loaded     BIGINT NOT NULL DEFAULT 0,
    bytes_staged    BIGINT NOT NULL DEFAULT 0,
    staged_path     TEXT,                                -- durable stage artefact (Parquet dir)
    source_profile  JSONB,                               -- TableProfile from source engine
    staged_profile  JSONB,                               -- TableProfile over transformed Parquet
    target_profile  JSONB,                               -- TableProfile from target engine
    load_id         TEXT,
    error           TEXT,
    stage_timings   JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    PRIMARY KEY (run_id, table_name)
);

-- Latest successfully loaded version of each target object, across runs (idempotency / skip logic).
CREATE TABLE IF NOT EXISTS ctl.object_registry (
    target_id     TEXT NOT NULL,
    target_mode   TEXT NOT NULL,
    target_table  TEXT NOT NULL,                         -- container.table
    source_table  TEXT NOT NULL,
    definition_hash TEXT NOT NULL,                       -- hash of TablePlan columns+options
    last_run_id   TEXT NOT NULL,
    last_load_id  TEXT NOT NULL,
    row_count     BIGINT NOT NULL,
    checksum      TEXT,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, target_mode, target_table)
);

CREATE TABLE IF NOT EXISTS ctl.run_events (
    run_id   TEXT NOT NULL,
    seq      BIGINT NOT NULL,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind     TEXT NOT NULL,                              -- log | state | progress | run
    level    TEXT NOT NULL DEFAULT 'info',
    table_name TEXT,
    message  TEXT NOT NULL,
    data     JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS ctl.run_checks (
    run_id       TEXT NOT NULL,
    table_name   TEXT NOT NULL,
    check_name   TEXT NOT NULL,
    column_name  TEXT NOT NULL DEFAULT '',
    passed       BOOLEAN NOT NULL,
    source_value TEXT,
    target_value TEXT,
    diff         TEXT,
    threshold    TEXT,
    detail       TEXT,
    PRIMARY KEY (run_id, table_name, check_name, column_name)
);
