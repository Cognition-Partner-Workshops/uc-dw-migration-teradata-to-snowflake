# Teradata core on DuckDB

Run from the repository root (Python 3.10+). No Snowflake connection or objects
are used. Install dbt-core 1.9 explicitly because the adapter's dependency range
also permits newer core releases:

```sh
python -m pip install -r requirements.txt
python -m pip install 'dbt-core==1.9.10' 'duckdb==1.4.1'
python tools/generate_seed.py --check
python tools/td_baseline.py --check
export TD_DUCKDB_PATH="$PWD/dbt/teradata/core/target/td.duckdb"
# Choose a new, nonexistent database path for a fresh verification run.
python dbt/teradata/core/load_inputs.py
dbt build --project-dir dbt/teradata/core --profiles-dir dbt/teradata/core
python tools/reconcile.py --duckdb "$TD_DUCKDB_PATH" --schema main --report reports/core.md
```

The last command exits nonzero because the other 14 non-core objects are absent.
All 13 core objects must be GREEN; inspect the Markdown and JSON report.
`TD_DUCKDB_PATH` should be absolute so the loader and dbt resolve it identically.
Without the variable, the profile uses `target/td.duckdb` relative to dbt's working
directory. The loader defaults to `target/td.duckdb` relative to its caller;
run both from this project directory when using that default.

The loader replaces only `td_src_core` input tables, using explicit DDL types,
the frozen manifest's column order/counts and the actual pipe-delimited CSVs
(not commas), with `\N` as null. Models read only these inputs and upstream
models. They never read baseline outputs. Every build replaces `main` tables
with the complete post-run state, rather than appending a second daily run.

Defaults are dbt vars `as_of_date: '2026-01-31'`,
`load_timestamp: '2026-01-31 06:00:00'`, `batch_id: 20260131`,
`snapshot_year: 2026`, `snapshot_month: 1`. Override via `dbt build --vars`.
The explicit batch var represents MAX(input batch)+1 for this fixture. The
monthly call follows daily loading and uses the snapshot year/month vars.

## Preserved derived semantics

Follow `baseline/teradata/README.md`: SQL null comparisons, NOT IN null
semantics, no transaction deduplication, no invented running balances, missing
FX zero, and current customer/account joins are preserved. SCD2 expiration
precedes anti-join; windowing keeps a single shared null partition for all new
customers. Identity allocation is max frozen key plus row_number in customer-ID
order (16/17 here), not a claim about native parallel identity allocation.
Invalid QUALIFY/WHERE order is repaired as documented; effective-date ties use
the documented deterministic keys. Names/address-line-2 alone are untracked.

The monthly absent `a.CUSTOMER_KEY` is resolved through the existing customer
join as `c.CUSTOMER_KEY`, the documented evaluator repair (native owner approval
unverified). Previous snapshot date is the previous month's **first** day.
Overdraft counts transaction rows; TRANSFER is excluded from debit/credit totals.
Matched snapshots retain dimensions, customer key, currency and base-currency
closing; new rows leave base-currency closing null. Logs represent the successful
frozen execution with duration 0; dbt errors fail the build rather than fabricate
an exception log or completed warehouse state. BTEQ operational/export commands
are not relational tables. This establishes only derived fixture parity, not
native Teradata collation, physical behavior or production identity guarantees.

## Checks

```sh
pytest -q
pytest -q dbt/teradata/core/test_load_inputs.py
ruff check .
```

`dbt build` also runs core fixture assertions (SCD2 keys, rejects, default
transaction values and monthly merge retention).
