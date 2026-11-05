# Teradata core post-run state

With `~/venvs/dbt` activated and the five `SNOWFLAKE_NFR_*` credential variables
provisioned (account, user, private key, role, warehouse), rebuild from the repo root:

```sh
unset SNOWFLAKE_HOST
cd dbt/teradata/core
dbt build --profiles-dir .
```

Install with `pip install 'dbt-core>=1,<2' dbt-snowflake -r requirements.txt`
from the repository root. Credentials remain in environment variables only.
The default database/warehouse/schema are FSX_20261105_DB, FSX_20261105_WH,
TD_TARGET. Inputs are exclusively TD_SOURCE, never TD_BASELINE.

All 13 models replace tables, replaying a complete run from immutable pre-run
source state; no incremental append or deduplication occurs. Explicit casts
follow the legacy DDL column order and precision. `ref()` enforces customer
SCD2 before daily facts and daily facts before monthly aggregation. Rejections
and facts precede completion logs. Control rows use the same computed batch.
`MAX(source.ETL_BATCH_CONTROL.BATCH_ID)+1` supplies the batch everywhere;
the dbt clock test asserts it equals var `batch_id` (20260131). Clock vars
`run_date` and `load_ts` default to 2026-01-31 and 2026-01-31 06:00:00.

The specification is `tools/td_baseline.py` and `baseline/teradata/README.md`.
Intentional legacy behavior includes three-valued tracked-attribute comparisons,
phone/email-only COALESCE, NOT IN null semantics, the single null-partition
brand-new customer insertion defect, no running balance on new transactions,
missing FX as zero, and silently skipped accounts without current customers.
The snapshot uses December 1 for prior balance, resolves CUSTOMER_KEY via the
post-SCD2 customer join, counts overdraft rows, retains non-SET matched columns,
and leaves unmatched BASE_CURRENCY_CLOSING null. No synthetic exception log is
produced for a successful run. Empty staging contributes no facts or rejects;
an invalid account contributes a reject, not a fact.

Evidence from repository root:

```sh
python tools/reconcile.py --snowflake FSX_20261105_DB.TD_TARGET --report reports/teradata.md
python tools/licence_status.py --report reports/teradata.json --output reports/licence.md
pytest -q
ruff check .
```

The 14 reporting outputs are outside this project and intentionally absent.
Green core fixture parity is not native Teradata execution or licence release.
