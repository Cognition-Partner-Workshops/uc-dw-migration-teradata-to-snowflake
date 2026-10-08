# TD Migration Studio

This web app migrates a Teradata warehouse to **Azure Synapse**, **Google BigQuery** or **Amazon Redshift**.
The flow is planner, plan review, run monitor, then reconciliation results.
By default everything runs offline with zero credentials. The Teradata source is emulated and each target is a simulated
warehouse backed by a local DuckDB file. When credentials are present, the same pipeline uses the real connectors.

## Run the demo (one command)

```bash
cd td-migration-studio
make demo            # = docker compose up --build -d
```
Open **http://localhost:3000**. The API docs are at http://localhost:8000/docs.
The first start seeds the emulated Teradata with the Olist dataset: 9 tables and 1,550,922 rows, in a few seconds.

1. **Planner**: click *Test connection* for Teradata, then pick a target. The config form below the target changes with
   your choice. Then choose tables, set the DQ and governance toggles, and click *Generate plan*.
2. **Plan review**: shows the native DDL and the Teradata→target type-mapping table, with lossy rows flagged
   (e.g. unbounded `NUMBER` and `TIMESTAMP WITH TIME ZONE`). You can override types or masking per column, then click
   *Approve & run*.
3. **Run monitor**: shows each table's status as it moves through extracting, loading, validating and passed/failed,
   plus a progress bar and a live log over SSE. To see recovery, use the Planner's *Demo* section before generating the plan to
   inject a failure on a table. That table ends *failed*; click *Retry failed* and only it is redone, from its staged Parquet.
   Passed tables are not re-extracted, and loads replace rather than append, so there are no duplicates.
4. **Results**: summary cards, a source-vs-target chart, and per-table row counts, checksums, checks vs thresholds
   and rejected rows. You can export the results as CSV or JSON.

`make reset` wipes the emulator, the control DB and the simulated warehouses. `make logs` tails the API.

## What's simulated vs real

| Component | Default (simulated) | Real mode |
|---|---|---|
| Teradata source | Postgres seeded from Teradata-dialect DDL (`source/ddl/teradata/`). Metadata comes from emulated `DBC.TablesV/ColumnsV/IndicesV/All_RI_ChildrenV` views | `TD_MODE=real` + `TD_HOST/TD_USER/TD_PASSWORD` → `teradatasql`, same DBC queries |
| Synapse | DuckDB file `targets/synapse.duckdb`. The T-SQL DDL is rendered and shown | pyodbc (ODBC 18, `Encrypt=yes`) + ADLS Gen2 upload + `COPY INTO`, rename-swap |
| BigQuery | DuckDB file `targets/bigquery.duckdb` | google-cloud-bigquery Parquet **load jobs** (`WRITE_TRUNCATE`, no DML) |
| Redshift | DuckDB file `targets/redshift.duckdb` | redshift_connector + S3 + `COPY ... FORMAT AS PARQUET`, staging-table swap |

Everything else is the same in both modes and is not faked: extraction, Parquet staging, type mapping and transforms,
PII masking, DQ and reconciliation, control tables, and resume/retry.

## Plugging in real credentials
1. `cp .env.example .env` and fill in the section for your target, then run `docker compose up -d`. Put any credential files
   (e.g. a BigQuery service-account JSON) under the `studio-data` volume at `/data/creds/`.
2. In the Planner, the target shows **real available** once its `real_mode_required_env` variables are set. Pick
   *real* mode. You can also type the connection fields in the UI, which are rendered from the target YAML.
3. **Free real target: the BigQuery sandbox.** Create a GCP project with no billing account. The sandbox allows
   load jobs and queries but not DML, and this connector only uses load jobs plus a copy job, so it works there.
   Tables in the sandbox expire after 60 days.
4. **Real Teradata:** set `TD_MODE=real` and `TD_HOST`, `TD_USER`, `TD_PASSWORD` (and optionally `TD_LOGMECH`). The planner reads the same DBC views.

## Adding a target
Add `backend/app/targets_meta/<id>.yaml`, which defines config fields, type-mapping rules (`when`, `lossy`, `transform`),
identifiers, checksum SQL and governance. Then add a connector class with `@register_target("<id>", "simulated"|"real")`.
The UI, planner and pipeline need no other changes. See [CONTRACTS.md](CONTRACTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Development
```bash
cd backend && uv venv -p 3.11 .venv && uv pip install -p .venv/bin/python -e '.[real,dev]'
docker compose up -d postgres seed                  # emulated Teradata + control DB on :5432
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/python -m pytest -q
DATA_DIR=$PWD/../.data .venv/bin/uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev        # http://localhost:5173 (VITE_MOCK=1 for a backend-free mock)
```

Dataset: [Olist Brazilian E-Commerce](https://github.com/olist/work-at-olist-data) (MIT, see `data/olist/LICENSE`).
