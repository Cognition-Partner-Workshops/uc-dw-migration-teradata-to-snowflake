# td-cloud-migrator

Proof of concept that takes two client-provided Teradata dumps, analyses them, converts the Teradata objects to
**Google BigQuery**, **Amazon Redshift** and **Azure Synapse Analytics (dedicated SQL pool)**, generates the migration
outputs and runs a simulated load with validation.

| Step | What happens |
| --- | --- |
| 1. Upload | Three columns, left to right: configuration dump, data dump, then target and run. Each upload panel has a format dropdown and a list of accepted formats and accepts multiple files or a `.zip`. One target (BigQuery, Redshift or Synapse) is chosen per job. |
| 2. Analyse & validate | The job runs in the background; the screen shows % complete, the current stage, elapsed time and ETA, then the results in pipeline order: stage timeline, an upload summary (file count, format and size per dump), object inventory, dependencies and create order from the configuration dump; per-file format/delimiter/header/row/column detection, table mapping and type/NOT NULL validation for the data dump. |
| 3. Outputs | Converted SQL for the chosen target with rules applied and warnings, type mapping, conversion report, mapping report and data-loading instructions/scripts. Downloadable as one ZIP. |
| 4. Load & validate | Creates the destination tables in a local DuckDB warehouse that mirrors the chosen target, loads the validated rows, reconciles row counts, NULL counts, numeric sums and string-length checksums, and creates the converted views. |

## Accepted formats

**Configuration / metadata dump**

| Format | Files |
| --- | --- |
| Teradata DDL / SQL scripts | `.sql`, `.ddl`, `.txt` (tables, views, macros, procedures) |
| BTEQ scripts | `.btq`, `.bteq` |
| DBC dictionary export (CSV) | `TablesV`, `ColumnsV`, `IndicesV` exports; file name identifies the view |
| DBC dictionary export (JSON) | `{"tables": [...], "columns": [...], "indices": [...]}` |
| Archive | `.zip` of any of the above |

**Data dump**

| Format | Files |
| --- | --- |
| CSV / delimited text | `.csv`, `.psv`, `.tsv`, `.txt`, `.dat`, optionally `.gz`; delimiter and header are auto-detected or chosen in the UI |
| Parquet | `.parquet` |
| Manifest / table-to-file mapping | `manifest.csv`, `.json`, `.yaml` (`table`, `file`/`files`, optional `delimiter`, `header`) |
| Archive | `.zip` of any of the above |

A table can be split across several files. Files are mapped to tables by manifest, then by file name, then by fuzzy
name + column overlap; any mapping can be overridden in the UI.

## Conversion scope

| Object | Result |
| --- | --- |
| Tables | Fully converted: types, NOT NULL, defaults, identity, PI → cluster/dist/hash keys, partitioning, unique keys, statistics, comments. |
| Simple views | Converted with `sqlglot` plus Teradata rewrites (`SEL`, `LOCKING`, `ZEROIFNULL`, `NULLIFZERO`, `ADD_MONTHS`, `FORMAT`, `CASESPECIFIC`, date arithmetic). |
| Views using `CSUM`/`MAVG`/`MSUM`, `HASHROW`, `SAMPLE` | Best-effort draft, status **manual review**. |
| Macros, stored procedures, BTEQ | Detected, dependencies extracted, embedded DML drafted, status **manual review**. |
| Anything that fails to parse | Reported as **unsupported**; the rest of the run continues. |

Generated real-cloud load scripts (`bq load`, Redshift `COPY ... FROM s3://`, Synapse `COPY INTO` from ADLS) are
written to the output bundle but never executed; bucket, project and storage account names come from the job options.

## Run locally

```bash
# backend (Python 3.10+)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --port 8000

# frontend (Node 20+), in another shell
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to :8000
```

Jobs and simulated warehouses are stored under `backend/var/` (override with `TDCM_DATA_DIR`).

## Worked example: BANKING_DW

`examples/banking_dw/` is built from the repository's `ddl/`, `dml/` and `data/seed/` folders by
`scripts/build_example.py`:

- `config_dump.zip`: 7 tables, 3 views, 3 macros, 3 procedures, 2 BTEQ scripts.
- `config_dump_dbc.zip`: the same tables and views as a DBC dictionary export.
- `data_dump.zip`: the 4 pipe-delimited seed files, `DIM_DATE` as Parquet, `FACT_TRANSACTION` split into a `.psv` and a
  headerless `.csv.gz`, and `manifest.yaml`. The fact files contain 3 deliberately bad rows (invalid date, NULL in a
  NOT NULL key, invalid decimal), and the seed files omit identity and SCD columns, so validation has something to report.

Click **Run example** on the upload page, or call `POST /api/examples/banking_dw/run?target=bigquery`. With **Presentation pace** ticked
(`&pace=1.5`), each stage takes at least 1.5 seconds so the progress bar can be followed in a live demo; uploads always run at full speed.

**Job history** (header button) lists the last 10 jobs, newest first, with target, uploads, counts, duration and status; **Open** reloads a job.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/formats` | Accepted formats, delimiters and targets |
| POST | `/api/jobs` | Multipart upload: `config_files`, `data_files`, `options` (JSON, `targets` must hold exactly one target), `name`. Returns immediately with `status: "running"` |
| GET | `/api/jobs` | Last 10 jobs (`{"jobs": [...], "total": n, "limit": 10}`) |
| GET | `/api/jobs/{id}` | Job with `progress` (stages, %), upload summary, analysis, conversions and load results; poll while `running` |
| POST | `/api/jobs/{id}/mappings` | `{"overrides": {"<file path>": "TABLE:DB.NAME"}}` |
| POST | `/api/jobs/{id}/load` | Simulated load and validation into the job's target |
| GET | `/api/jobs/{id}/outputs`, `/bundle.zip` | Generated files |

## Checks

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/python -m pytest -q
cd frontend && npm run lint && npm run build
```
