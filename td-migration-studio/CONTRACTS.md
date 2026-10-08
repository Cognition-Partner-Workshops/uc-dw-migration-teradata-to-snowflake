# TD Migration Studio — contracts & workstreams

This file is the shared spec for the parallel workstreams. **Do not change existing fields or signatures in
`backend/app/contracts/*`, `backend/app/connectors/registry.py`, `backend/app/control/ddl.sql`, or the
config-field `key`s in `backend/app/targets_meta/*.yaml`.** You may add optional fields. If a contract is
truly wrong, make the smallest backwards-compatible change and call it out in your PR description.

## Layout

```
td-migration-studio/
  docker-compose.yml        postgres (tdemu + ctl DBs), seed (one-shot), api (FastAPI :8000), web (nginx :3000)
  data/olist/*.csv.gz       Olist Brazilian E-Commerce dataset (MIT), ~1.55M rows, 9 tables
  source/ddl/teradata/      Teradata-dialect DDL (RETAIL_DW) + manifest.yaml (table -> seed file)
  backend/app/
    contracts/models.py     ALL shared pydantic models (metadata, plan, run, events, report)
    contracts/source.py     SourceConnector ABC (+ Arrow type contract for extract)
    contracts/target.py     TargetConnector ABC
    contracts/checksum.py   canonical checksum definition + DuckDB reference SQL
    typemap.py              resolve_type() / target_type_info()           [targets WS]
    targets_meta/*.yaml     per-target metadata (fields, mappings, DQ, governance)  [targets WS]
    connectors/registry.py  target/source registries (frozen)
    connectors/source/      emulated.py, real.py, seed.py                 [source WS]
    connectors/targets/     sim_*.py / real_*.py per target              [targets WS]
    pipeline/               planner, orchestrator, staging, transforms, governance, dq, report [pipeline WS]
    api/                    FastAPI routers mounted from main.py          [pipeline WS]
    control/ddl.sql         control tables (frozen)
  frontend/                 React + Vite + TS wizard (Dockerfile builds -> nginx)  [frontend WS]
```

## Environment / settings (`backend/app/settings.py`)
`TD_MODE` (emulated|real), `TD_EMU_DSN`, `CTL_DSN`, `DATA_DIR` (staging under `$DATA_DIR/staging/<run>/<table>/`,
rejects under `$DATA_DIR/rejects/<run>/<table>.parquet`, simulated warehouses at `$DATA_DIR/targets/<target_id>.duckdb`),
`SEED_DIR`, `DDL_DIR`, real-mode env vars listed in `.env.example` and each YAML's `real_mode_required_env`.
Local dev: `docker compose up -d postgres` gives you Postgres on localhost:5432 (user/pass `studio`).

## Source (emulated Teradata)
- Database `tdemu`, Postgres schema `retail_dw` holds the physical tables (lower-case names).
- Postgres schema `dbc` emulates the Teradata data dictionary: `dbc.tablesv`, `dbc.columnsv`, `dbc.indicesv`,
  `dbc.all_ri_childrenv` (soft RI), `dbc.tablesizev`, with Teradata column names (DatabaseName, TableName,
  ColumnName, ColumnType codes like 'CV','I1','DA','TS','SZ','N','D', ColumnLength, DecimalTotalDigits,
  DecimalFractionalDigits, CharType 1=LATIN 2=UNICODE, Nullable 'Y'/'N', IndexType 'P'/'Q'/'S'/'U', UniqueFlag ...).
  The **emulated connector reads metadata only through these DBC views** (same queries a real Teradata gets).
- `describe_table` returns `TableMeta` with `unique_keys` from UPI/USI and `foreign_keys` from soft RI.
- Seeder (`python -m app.connectors.source.seed`): idempotent; parses the Teradata DDL, creates physical
  tables, bulk loads the CSVs with COPY, fills DBC views, records row counts. ORDER_REVIEWS.review_answer_timestamp
  is loaded as timestamptz at offset -03:00 (manifest `timezone`).
- Emulator details (source workstream): `dbc` additionally has `partitioningconstraintsv` (PPI ConstraintText),
  `tablestatsv` (RowCount), `dbcinfov` (InfoKey 'VERSION') and `seed_marker` (input hash; `--force` re-seeds).
  UPI/USI are backed by unique Postgres indexes. ORDER_REVIEWS has **99,224** records (104,720 physical CSV lines:
  review texts contain quoted newlines). Unbounded NUMBER is DecimalTotalDigits=-128 -> Arrow decimal128(38,15).

## Targets
- `TargetMeta` YAML drives everything: `config_fields` (UI forms, scope target|table), `type_mappings`
  (first match wins; `when` is a safe expression over ColumnMeta fields; `target` template supports
  `{length}`, `{precision}`, `{scale}`, `{fractional_seconds}` and simple arithmetic/min/max), `lossy`/`severity`/`reason`,
  `transform` names (below), identifier rules, DQ checksum SQL template, governance profile + role script template.
- Config-field keys (frozen): BigQuery `dataset, location, load_method | partition_column, partition_granularity,
  clustering_columns, require_partition_filter`; Synapse `schema, dwu, resource_class, load_method | distribution,
  distribution_column, index_type, partition_column`; Redshift `schema, node_type, node_count, load_method |
  diststyle, distkey, sortkey_type, sortkeys`.
- `typemap.resolve_type(meta, column) -> MappingDecision`, `typemap.target_type_info(meta, type_str) -> TargetTypeInfo`
  (Arrow type string + length limit/unit) — the pipeline uses TargetTypeInfo to cast staged data.
- Simulated connectors: one DuckDB file per target, schema = `TablePlan.target_container`. `render_ddl` returns
  native dialect DDL (Synapse `WITH (DISTRIBUTION=HASH(x), CLUSTERED COLUMNSTORE INDEX)`, BigQuery
  `PARTITION BY DATE_TRUNC(col, MONTH) CLUSTER BY ...`, Redshift `DISTSTYLE KEY DISTKEY(x) COMPOUND SORTKEY(...)`);
  the DuckDB DDL actually executed is derived from the same column list. `load` = `CREATE TABLE <t>__stg_<load_id>
  AS SELECT * FROM read_parquet([...])` + transactional swap. `profile` uses `contracts/checksum.py`.
- Real connectors (activated when `real_mode_required_env` present or connection given): BigQuery
  (google-cloud-bigquery, `load_table_from_file` Parquet, WRITE_TRUNCATE — sandbox-compatible), Redshift
  (redshift_connector + boto3 S3 upload + `COPY ... FORMAT AS PARQUET IAM_ROLE`, staging table + swap),
  Synapse (pyodbc ODBC18 `Encrypt=yes` + ADLS Gen2 upload + `COPY INTO`, CTAS/RENAME swap). Unit-test with mocks.

## Transform names (TypeMappingRule.transform) — implemented by the pipeline
`tz_to_utc`, `round_scale` (decimal scale reduction; rows that overflow precision -> rejects),
`truncate` (string longer than TargetTypeInfo.max_length in its unit -> truncate, flagged lossy; in strict mode -> reject),
`to_string` (INTERVAL/PERIOD/JSON/XML -> text), `none`. Casting to TargetTypeInfo.arrow_type is always applied;
values that cannot be cast go to rejects with a reason.

## Pipeline (per table; state in `ctl.run_objects`, events in `ctl.run_events`)
`pending -> extracting -> staged -> transforming -> loading -> loaded -> validating -> passed|failed`.
Resume: tables already `passed` in the resumed run are skipped; a failed table restarts from the last durable
stage (`staged_path` + `source_profile` present => skip extract). Retries with backoff up to `max_attempts`.
Idempotency: target `load` has replace semantics; `ctl.object_registry` records the last load per target table.
DQ: row_count (source - rejected vs target), sum/min/max per numeric column (staged vs target, and source vs
staged when no transform touched the column), null_ratio, checksum (staged Parquet DuckDB reference vs target
`profile`), uniqueness on `TableMeta.unique_keys`, referential_integrity on `foreign_keys` (orphan count vs
parent in staged data), rejected_rows vs `max_rejected_rows_pct`. Governance: PII classification (name rules +
regex sampling), masking (hash = salted SHA-256 hex, partial, nullify) applied before load; encryption/role notes
per target from YAML; toggles from `GovernanceOptions`.

## REST API (prefix `/api`, JSON bodies = models in contracts/models.py)
| Method | Path | Body -> Response |
|---|---|---|
| GET | `/health` | `{status}` |
| GET | `/source/connection` | `{mode, host, database}` |
| POST | `/source/test` | `{}` -> `ConnectionTestResult` |
| GET | `/source/databases` | `list[str]` |
| GET | `/source/tables?database=RETAIL_DW` | `list[SourceTableSummary]` |
| GET | `/source/tables/{database}/{table}` | `TableMeta` |
| GET | `/targets` | `list[TargetSummary]` |
| GET | `/targets/{id}` | `TargetMeta` (UI renders forms from `config_fields`/`connection_fields`) |
| POST | `/targets/{id}/test` | `{mode, connection}` -> `ConnectionTestResult` |
| POST | `/plans` | `PlanRequest` -> `MigrationPlan` |
| GET | `/plans/{id}` | `MigrationPlan` |
| POST | `/plans/{id}/overrides` | `list[ColumnOverride]` -> `MigrationPlan` (re-rendered DDL/warnings) |
| POST | `/plans/{id}/approve` | -> `MigrationPlan` |
| POST | `/runs` | `{plan_id}` -> `Run` (plan must be approved) |
| GET | `/runs` | `list[Run]` |
| GET | `/runs/{id}` | `Run` |
| GET | `/runs/{id}/events?after=<seq>` | SSE stream of `RunEvent` (event: `run_event`, data: JSON); also works as one-shot JSON list with `Accept: application/json` |
| POST | `/runs/{id}/resume` | -> `Run` (continues same run; skips passed tables) |
| POST | `/runs/{id}/retry` | `{tables: [..]}` -> `Run` |
| GET | `/runs/{id}/report` | `RunReport` |
| GET | `/runs/{id}/report.csv` | per-table CSV |
| GET | `/runs/{id}/rejects/{table}` | `{rows: [...], total}` |

## Conventions
Python 3.10+ (Docker uses 3.11), ruff (`ruff check . && ruff format --check .`), pytest. Tests that need Postgres
are marked `@pytest.mark.integration`; real-cloud tests `@pytest.mark.real` (skipped by default).
TypeScript strict, ESLint, `npm run build` must pass.
