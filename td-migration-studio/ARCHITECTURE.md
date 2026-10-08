# Architecture

```
            ┌──────────── web (nginx :3000) ────────────┐
 browser ──▶│ React wizard: Planner → Review → Run → Results │──/api──▶ api (FastAPI :8000)
            └───────────────────────────────────────────┘                │
                                                                         ▼
   ┌──────────────── Postgres ────────────────┐     ┌──────── pipeline (thread pool) ────────┐
   │ tdemu: retail_dw.* (Olist, ~1.55M rows)  │◀────│ extract → stage Parquet → transform/mask │
   │        dbc.* emulated Teradata dictionary│     │ → create (target DDL) → load (swap)     │
   │ ctl:   plans/runs/run_objects/events/... │◀───▶│ → DQ + reconciliation → report          │
   └──────────────────────────────────────────┘     └───────────────┬─────────────────────────┘
                                                                     ▼
                                       TargetConnector (registry, YAML metadata)
                         simulated: DuckDB file per target │ real: BigQuery / Redshift / Synapse SDKs
```

## Key ideas
- **One connector interface each side.** `SourceConnector` (emulated Postgres+DBC views, or real Teradata via
  `teradatasql`) and `TargetConnector` (`render_ddl`, `create_table`, `load`, `profile`, ...). Connectors register
  via `@register_target(id, mode)`; the registry discovers targets from `backend/app/targets_meta/*.yaml`.
- **Metadata-driven targets.** Each YAML defines the UI config fields, Teradata→target type-mapping rules
  (with lossy flags and transforms), identifier rules, checksum SQL, and governance notes/role scripts. The UI
  renders forms generically from it, and the planner/pipeline never branch on target id. To add a target, add one
  YAML and one connector class.
- **Control tables make runs resumable and idempotent.** `ctl.run_objects` stores each table's state machine
  (`pending → extracting → staged → transforming → loading → loaded → validating → passed|failed`), the staged
  path and the profiles. Resume skips passed tables and restarts failed ones from the last durable stage. Loads
  use staging-table + swap (replace) semantics, so re-running a table never duplicates rows.
- **Validation happens in the pipeline.** None of the three warehouses enforces PK/FK, so uniqueness and referential
  integrity are checked on staged data. Row counts, sum/min/max, null ratios and an order-independent
  canonical checksum (`contracts/checksum.py`) are compared between source/staged data and the target.

## Simulated vs real
| Piece | Demo (default) | Production path |
|---|---|---|
| Teradata source | Postgres + emulated `dbc.*` views, seeded from Teradata DDL | `RealTeradataSource` (`teradatasql`, real `DBC.*V`) when `TD_MODE=real` |
| Targets | One DuckDB file per target; native DDL rendered and shown, DuckDB-equivalent executed | Real BigQuery / Redshift / Synapse connectors (cloud-storage staging + COPY / load jobs) when credentials exist |
| Staging | Local Parquet under `DATA_DIR` | Same files, uploaded to GCS/S3/ADLS by real connectors |
| Encryption / roles | Documented per target; role scripts generated, not executed | Apply the generated scripts / cloud IAM |
| PII masking | Salted SHA-256 / partial / nullify before load | Same; native masking options noted per target |

Not production-hardened: there's no auth on the API, the thread pool is single-node, and secrets come from env vars rather than a vault.
