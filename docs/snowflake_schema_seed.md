# Snowflake schema and frozen seed

Source-only migration: legacy SQL remains untouched. No tasks, deployment pipeline,
production grants or scheduled runs are created or resumed.

## Translation

All seven tables retain their columns, nullability, numeric precision, dates and defaults.
`BYTEINT` becomes `NUMBER(3,0)`; timestamps are explicitly `TIMESTAMP_NTZ`.
`NOT CASESPECIFIC` becomes `COLLATE 'en-ci'`. Surrogates retain identity definitions,
but this seed supplies stable keys sorted by customer/account natural key. Do not mix
seed-assigned keys with subsequent identity-generated keys without reseeding.
Physical indexes, fallback, journaling, `COMPRESS`, formats and statistics are removed.
No clustering is enabled on these small tables (avoids automatic clustering compute).
Dimension PKs and fact FKs are informational, **not enforced** by Snowflake standard tables.
SET-table duplicate prevention requires validation; it is not provided by a Snowflake PK.
The account/customer relationship is a lookup on the customer natural key, not a unique
SCD2 key, so it is checked in the exception output rather than declared as a misleading FK.

## Officer privacy and exceptions

The complete legacy SQL/model search found two officer identifiers:

| Legacy location | Column | Frozen-seed handling |
|---|---|---|
| `ddl/tables/02_dim_account.sql` | `RELATIONSHIP_MGR_ID` | Always NULL |
| `ddl/tables/04_dim_branch.sql` | `MANAGER_ID` | Always NULL |

Neither appears in its source CSV; both are explicitly present as masked NULLs in
every frozen row. The masking function also discards non-empty values if supplied.
`EMPLOYEE_COUNT` is an aggregate count, not an officer ID. There is no literal
`OFFICER_ID` column. Exception `ROW_DATA` is masked before serialization too.

The loader **keeps orphan rows in their original seed tables** and writes one
`BANKING_DW.SEED_FK_EXCEPTION` row per failed non-null FK lookup, including the
masked source row, key, failed field/value and missing parent. Nullable FKs with
NULL are not orphans. Officer IDs have no officer parent table and are not FK lookups.
Synthetic fault injection tests cover multiple failed lookups and officer masking.

## Frozen input contract

`snowflake/seed_manifest.json` pins SHA-256 of all four source CSVs. Any byte change
fails closed until a deliberate manifest/version update. Empty CSV fields become NULL;
all missing timestamps and batch IDs are fixed to `2026-01-31 00:00:00` and `1`.
The deterministic date calendar spans 2000-01-01 through 2029-12-31 (10,958 rows),
uses Monday=1, ISO weeks, calendar-year fiscal periods and Norwegian public holidays.
Leap-day prior-year mapping clamps to February 28. No random values, current-date
data generation or server timestamp defaults participate in the seed.
Four CSV dimensions have 15 customers, 20 accounts, 10 products and 14 branches.
Both fact tables are empty: **there are no fact seed CSVs**. Legacy expected counts
of 50,000 transactions and 1,920 snapshots describe a different generated dataset
and are not evidence for this frozen input. Downstream parity must report this gap.

## Run and controls

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
.venv/bin/ruff check tools tests
.venv/bin/mypy --ignore-missing-imports tools/seed.py tools/load_seed.py
# Inject only SNOWFLAKE_EXT_ACCOUNT, SNOWFLAKE_EXT_USER, SNOWFLAKE_EXT_PRIVATE_KEY
# and DEVIN_SESSION_URL securely into this process; never put keys in a file.
.venv/bin/python -m tools.load_seed --evidence-dir /path/outside/repo
```

The EXT adapter uses the OtterWorks attribution library vendored at
`tools/sf_attribution.py` from commit `3b6fe0e9dfd602483fe5c554e76c2f0834e3cac8`
(PR 2471), with an in-memory DER-key option and registered endpoint
`cs_mig_td_schema_seed` (`workload=mig_td`). The ticket explicitly authorizes the
existing EXT service user/DEVIN_EXT_ROLE rather than creating a new service user.
Application `Devin_Demo` is **unregistered**. Every query inherits compact JSON
`csid,workload,phase,commit,run_id,session_url` from connection establishment.

Before any compute, the loader reads back
`RM_SFEXT_20261105A_20261119_MIG_TD_SCHEMA`, validates its monthly quota and suspend
triggers, and verifies its attachment to the single-cluster XSMALL warehouse
`WH_MIG_TD_SCHEMA_SEED_SFEXT_20261105A` with auto-suspend <= 60 seconds.
Missing/misattached controls stop execution before DML. Only ACCOUNTADMIN may attach
the monitor; this loader does not try to bypass that restriction or create a substitute.
All objects are contained in `DB_MIG_TD_SCHEMA_SEED_SFEXT_20261105A.BANKING_DW`
and carry comments with run token and expiry `2026-11-19` (including every table).
Objects are for EXT verification only; the expiry is a cleanup marker, not automatic deletion.

Each load transaction deletes then inserts **all** target tables, including empty
facts and exceptions. Run only in this dedicated seed database, never against live data.
The command runs twice and compares per-table `COUNT(*)` and order-independent
`HASH_AGG(*)`, including ETL columns; it separately records canonical input SHA-256.
Cross-platform Teradata `HASHROW` bytes are not expected to equal Snowflake hashes.
The warehouse is suspended in `finally`, including failed loads; no task is resumed.
`--preflight-only` reads controls without deploying/loading anything.
Evidence and masked frozen output must be outside the repo and are never committed.
