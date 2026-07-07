# Migration Runbook — Teradata → Snowflake (DDL: Tables & Views)

This runbook documents the conversion of every Teradata table and view under `ddl/`
to Snowflake-compatible SQL under `snowflake/ddl/`. It records each translation
decision, the Teradata feature encountered, the Snowflake equivalent chosen, and
the rationale.

## Scope

| Source (`ddl/`) | Target (`snowflake/ddl/`) |
|---|---|
| `tables/01_dim_customer.sql` | `tables/01_dim_customer.sql` |
| `tables/02_dim_account.sql` | `tables/02_dim_account.sql` |
| `tables/03_dim_product.sql` | `tables/03_dim_product.sql` |
| `tables/04_dim_branch.sql` | `tables/04_dim_branch.sql` |
| `tables/05_dim_date.sql` | `tables/05_dim_date.sql` |
| `tables/06_fact_transaction.sql` | `tables/06_fact_transaction.sql` |
| `tables/07_fact_monthly_snapshot.sql` | `tables/07_fact_monthly_snapshot.sql` |
| `views/01_vw_customer_360.sql` | `views/01_vw_customer_360.sql` |
| `views/02_vw_regulatory_large_transactions.sql` | `views/02_vw_regulatory_large_transactions.sql` |
| `views/03_vw_branch_performance.sql` | `views/03_vw_branch_performance.sql` |

The `BANKING_DW` schema/namespace is preserved verbatim. Object and column names
are unchanged so downstream consumers and validation scripts continue to resolve.

## Deployment order

Run objects in this order so dependencies resolve:

1. All tables (`01`–`07`, any order among themselves).
2. Views (`01`–`03`) — they reference the tables above.

```sql
-- Example with SnowSQL
!source snowflake/ddl/tables/01_dim_customer.sql
-- ... tables 02-07 ...
!source snowflake/ddl/views/01_vw_customer_360.sql
-- ... views 02-03 ...
```

---

## Table-level translation decisions

### Table type — `SET` / `MULTISET`
- **Teradata:** `CREATE SET TABLE` (dimensions) and `CREATE MULTISET TABLE` (facts).
- **Snowflake:** `CREATE OR REPLACE TABLE`. Snowflake has no SET/MULTISET concept —
  all tables permit duplicate rows (multiset semantics).
- **Impact:** `SET` tables previously rejected fully-duplicate rows. In Snowflake
  this is **not enforced**. If duplicate suppression is required (notably
  `DIM_CUSTOMER`, `DIM_PRODUCT`, `DIM_BRANCH`, `DIM_DATE`), enforce it in the ETL
  MERGE/INSERT logic or with a de-dup step, since the declared `PRIMARY KEY` is
  not enforced either (see below).

### Physical storage options — removed
- `NO FALLBACK`, `NO BEFORE JOURNAL`, `NO AFTER JOURNAL`, `CHECKSUM = DEFAULT`,
  `DEFAULT MERGEBLOCKRATIO` — all Teradata physical-storage directives with **no
  Snowflake equivalent** (Snowflake manages redundancy, journaling, and block
  layout automatically). Removed entirely.

### Primary Index / Partitioned Primary Index → `CLUSTER BY` + `PRIMARY KEY`
- **`UNIQUE PRIMARY INDEX` (UPI)** on dimension surrogate/natural keys → declared
  as a `PRIMARY KEY` constraint. Snowflake **does not enforce** PK/unique
  constraints (they are metadata for the optimizer and tools). Uniqueness must be
  guaranteed by ETL.
- **`PRIMARY INDEX` (PI)** on fact tables (used for data distribution across AMPs)
  → replaced with `CLUSTER BY`. Snowflake has no AMP distribution; micro-partitions
  plus a clustering key provide pruning.
- **`PARTITION BY RANGE_N(... EACH INTERVAL '1' MONTH/YEAR)`** → replaced with
  `CLUSTER BY` on the same date column. Snowflake auto-partitions into
  micro-partitions; clustering on the date preserves partition-elimination
  behaviour on range scans.

| Object | Teradata PI / PPI | Snowflake choice |
|---|---|---|
| `DIM_CUSTOMER` | UPI(CUSTOMER_KEY) + RANGE_N(ONBOARDING_DATE, yearly) | `PRIMARY KEY (CUSTOMER_KEY)`, `CLUSTER BY (ONBOARDING_DATE)` |
| `DIM_ACCOUNT` | UPI(ACCOUNT_KEY) + RANGE_N(OPENING_DATE, yearly) | `PRIMARY KEY (ACCOUNT_KEY)`, `CLUSTER BY (OPENING_DATE)` |
| `DIM_PRODUCT` | UPI(PRODUCT_ID) | `PRIMARY KEY (PRODUCT_ID)` |
| `DIM_BRANCH` | UPI(BRANCH_ID) | `PRIMARY KEY (BRANCH_ID)` |
| `DIM_DATE` | UPI(DATE_KEY) | `PRIMARY KEY (DATE_KEY)`, `CLUSTER BY (CALENDAR_DATE)` |
| `FACT_TRANSACTION` | PI(ACCOUNT_KEY, TRANSACTION_DATE) + RANGE_N(TRANSACTION_DATE, monthly) | `CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)` |
| `FACT_MONTHLY_ACCOUNT_SNAPSHOT` | PI(ACCOUNT_KEY, SNAPSHOT_MONTH_KEY) + RANGE_N(SNAPSHOT_DATE, monthly) | `CLUSTER BY (SNAPSHOT_DATE, ACCOUNT_KEY)` |

- **Fact clustering key ordering:** the date column is placed **first** in
  `CLUSTER BY` because the PPI partitioned on the date and most analytical queries
  filter by date range; date-leading clustering maximizes pruning.
- **Consider `AUTOMATIC_CLUSTERING`** (background reclustering) on the high-volume
  fact tables if query patterns warrant; it is off by default here to avoid
  unexpected credit consumption.

### Secondary indexes (`INDEX`, `NUPI`) — dropped
- Teradata non-unique/secondary indexes (`NUPI_CUSTOMER_ID`, `IDX_CUST_SEGMENT`,
  `IDX_ACCT_BRANCH`, `IDX_BRANCH_REGION`, etc.) have **no Snowflake equivalent**.
  Dropped, with an inline comment in each file listing the removed indexes.
  Snowflake relies on micro-partition min/max pruning; add clustering or
  materialized views only if a specific access path proves hot.

### `COLLECT STATISTICS` — removed
- Snowflake gathers statistics automatically. All `COLLECT STATISTICS` statements
  (including `COLUMN (PARTITION)`) removed.

### `COMPRESS` (multi-value / single-value) — removed
- Teradata `COMPRESS ('A','B',...)` and `COMPRESS 0` are manual value-list
  compression hints. Snowflake compresses columnar storage automatically.
  All `COMPRESS` clauses removed; the enumerated value lists were storage hints,
  **not** check constraints, so no data-integrity behaviour is lost. (If the value
  lists should be enforced, add explicit `CHECK` constraints in ETL — not done here
  to preserve original semantics.)

### `NOT CASESPECIFIC` → `COLLATE 'en-ci'`
- Teradata `VARCHAR/CHAR ... NOT CASESPECIFIC` compares case-insensitively.
  Snowflake string comparison is **case-sensitive by default**. To preserve
  behaviour, each `NOT CASESPECIFIC` column is declared with `COLLATE 'en-ci'`
  (case-insensitive collation), so equality/join/`GROUP BY` semantics match the
  source.
- **Alternative considered:** dropping collation and applying `UPPER()`/`LOWER()`
  in queries. Rejected — it would require rewriting every downstream query.
  Column-level `COLLATE` keeps behaviour local to the schema.
- Columns **not** marked `NOT CASESPECIFIC` in the source (e.g. codes/IDs like
  `PRODUCT_CODE`, `BRANCH_CODE`, `POSTAL_CODE`, `REFERENCE_NUMBER`) are left
  case-sensitive, matching Teradata's default.

### `FORMAT 'YYYY-MM-DD'` on column definitions — removed
- Teradata column-level `FORMAT` controls **display**, not storage. Snowflake has
  no column-level display format. Removed from `DATE` columns; formatting is a
  presentation concern handled with `TO_CHAR()` in queries/views/BI tools.

### `GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` → `IDENTITY(1,1)`
- Applied to `DIM_CUSTOMER.CUSTOMER_KEY` and `DIM_ACCOUNT.ACCOUNT_KEY`. Snowflake
  `IDENTITY(1,1)` (equivalent to `AUTOINCREMENT(1,1)`) provides start-1/step-1
  sequence-backed values.
- **Caveat:** Snowflake identity/sequence values are **not guaranteed gap-free**
  (unlike Teradata `GENERATED ALWAYS`), but remain monotonic and unique per insert
  path. For SCD Type 2 surrogate keys this is acceptable. During historical
  bulk-load, if existing surrogate key values must be preserved, load them
  explicitly (Snowflake allows inserting into an identity column) and then `ALTER
  TABLE ... ALTER COLUMN ... SET INCREMENT`/reseed as needed.

### Data types
| Teradata | Snowflake | Notes |
|---|---|---|
| `INTEGER`, `BIGINT`, `SMALLINT` | same | All are aliases of `NUMBER(38,0)` in Snowflake. |
| `BYTEINT` | `SMALLINT` | Snowflake has **no `BYTEINT`**. Mapped to `SMALLINT` (all integer types collapse to `NUMBER(38,0)`; the 1-byte range is a Teradata storage detail only). Affects flag columns (`IS_ACTIVE`, `IS_WEEKEND`, `DAY_OF_WEEK`, etc.). |
| `DECIMAL(p,s)` | `DECIMAL(p,s)` | Unchanged. |
| `CHAR(n)`, `VARCHAR(n)` | same | Unchanged (plus `COLLATE` where noted). |
| `DATE` | `DATE` | Unchanged (FORMAT stripped). |
| `TIME(0)` | `TIME(0)` | Unchanged. |
| `TIMESTAMP(0)` / `TIMESTAMP(6)` | `TIMESTAMP_NTZ(0)` / `TIMESTAMP_NTZ(6)` | Teradata `TIMESTAMP` has no time zone → `TIMESTAMP_NTZ` (no-TZ) is the faithful mapping and avoids session-TZ surprises. |

### Defaults
- `DEFAULT CURRENT_TIMESTAMP(0)` → `DEFAULT CURRENT_TIMESTAMP()` (result stored in
  the `TIMESTAMP_NTZ(0)` column, truncated to seconds).
- `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` → `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ`
  (SCD2 "open" high-date sentinel preserved).
- Numeric/`CHAR` literal defaults (`DEFAULT 'NOR'`, `DEFAULT 0`, `DEFAULT 'Y'`,
  `DEFAULT 1`) unchanged.

### `COMMENT ON TABLE` / `COMMENT ON COLUMN` / `COMMENT ON VIEW` — retained
- Same syntax in Snowflake; kept verbatim.

---

## View-level translation decisions

### Common to all views
- **`REPLACE VIEW` → `CREATE OR REPLACE VIEW`.**
- **`LOCKING ROW FOR ACCESS` removed** — Teradata access-lock hint; Snowflake uses
  snapshot isolation and needs no equivalent.
- **`SEL` → `SELECT`** (all occurrences, including nested subqueries).
- **Column-level `(FORMAT '...')`** → wrapped in `TO_CHAR(expr, '<mask>')`. Format
  masks translated: leading-zero-suppression `Z` → `9`, mandatory digit `9`/`0` →
  `0`, grouping comma kept. Result columns become `VARCHAR` (as they did in
  Teradata display), preserving the reporting contract.

### `01_vw_customer_360.sql`
- `ZEROIFNULL(...)` — **native in Snowflake**, retained unchanged.
- `QUALIFY ROW_NUMBER() OVER (...)` inside the correlated scalar subquery —
  **native in Snowflake**, retained.
- `CAST((CURRENT_DATE - c.ONBOARDING_DATE) / 365.25 AS DECIMAL(5,1))` — Teradata
  date subtraction yields an integer day count. Snowflake does **not** allow
  `date - date` to return an integer directly, so rewritten as
  `CAST(DATEDIFF('day', c.ONBOARDING_DATE, CURRENT_DATE) / 365.25 AS DECIMAL(5,1))`
  — numerically identical.
- `WHERE ft.TRANSACTION_DATE >= CURRENT_DATE - 90` — `date - integer` (day
  subtraction) **is** supported in Snowflake, so left unchanged.
- Two `(FORMAT 'ZZZ,ZZZ,ZZ9.99')` columns → `TO_CHAR(..., '999,999,990.99')`.

### `02_vw_regulatory_large_transactions.sql`
- Column-level `(NOT CASESPECIFIC)` projection on `FIRST_NAME` / `LAST_NAME`
  **removed** — case-insensitivity now lives on the base-table columns via
  `COLLATE 'en-ci'`, so the per-projection override is unnecessary.
- `HASHROW(ft.TRANSACTION_ID, ft.TRANSACTION_DATE)` → `HASH(ft.TRANSACTION_ID,
  ft.TRANSACTION_DATE)`. **Note:** the hash *algorithm/values differ* between
  Teradata `HASHROW` and Snowflake `HASH`; `ROW_HASH` values will not match the
  legacy system. It is used here for change detection/row identity, which remains
  valid as long as producers and consumers both use the Snowflake `HASH`.
- `QUALIFY ROW_NUMBER() ...` — retained (native).

### `03_vw_branch_performance.sql`
- `TRIM(d.CALENDAR_YEAR (FORMAT '9999'))` → `TRIM(TO_CHAR(d.CALENDAR_YEAR))`
  (year rendered as text for the `MONTH_LABEL` concatenation).
- **`CSUM(SUM(snap.FEES_CHARGED), snap.SNAPSHOT_MONTH_KEY)`** → 
  `SUM(SUM(snap.FEES_CHARGED)) OVER (ORDER BY snap.SNAPSHOT_MONTH_KEY ROWS UNBOUNDED PRECEDING)`.
  Teradata `CSUM(value, sort)` is a cumulative sum ordered by `sort` with **no
  partition**; the equivalent window frame is unbounded-preceding-to-current-row.
  (The `_YTD` column name is inherited from the source; the original `CSUM` did not
  actually reset per year, and this behaviour is preserved. To make it true YTD,
  add `PARTITION BY <year>` — intentionally **not** done, to keep parity.)
- **`MAVG(SUM(snap.TOTAL_DEBITS + snap.TOTAL_CREDITS), 3, snap.SNAPSHOT_MONTH_KEY)`** →
  `AVG(SUM(...)) OVER (ORDER BY snap.SNAPSHOT_MONTH_KEY ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)`.
  Teradata `MAVG(value, n, sort)` averages the current row plus the `n-1` preceding
  rows (a 3-row window here) ordered by `sort`.
- `RANK() OVER (PARTITION BY ... ORDER BY ...)` — retained (native).
- `NULLIFZERO(...)` — **native in Snowflake**, retained.
- `ADD_MONTHS(CURRENT_DATE, -24)` — **native in Snowflake**, retained.
- Nested aggregate-in-window `SUM(SUM(...)) OVER (...)` — valid in Snowflake within
  a `GROUP BY` query; retained.
- `(FORMAT 'ZZZ,ZZZ,ZZZ,ZZ9.99')` and `(FORMAT 'ZZ9.99')` → `TO_CHAR(...,
  '999,999,999,990.99')` and `TO_CHAR(..., '990.99')`.

---

## Post-migration validation

1. **Object existence:** confirm all 7 tables and 3 views resolve
   (`SHOW TABLES IN SCHEMA BANKING_DW;`, `SHOW VIEWS IN SCHEMA BANKING_DW;`).
2. **Row counts:** reconcile against `data/validation/` expected counts after load.
3. **Case-insensitive parity:** spot-check joins/filters on `COLLATE 'en-ci'`
   columns (e.g. `CUSTOMER_SEGMENT = 'retail'` matches `'RETAIL'`).
4. **View results:** compare `VW_CUSTOMER_360`, `VW_REGULATORY_LARGE_TRANSACTIONS`,
   and `VW_BRANCH_PERFORMANCE` outputs against the Teradata source for a sample of
   keys/months. Expect `ROW_HASH` to differ (documented above).
5. **Uniqueness:** since PK/SET are not enforced, run duplicate checks on natural
   keys (`CUSTOMER_ID`, `PRODUCT_ID`, `BRANCH_ID`, `DATE_KEY`, `ACCOUNT_KEY`).

## Open items / follow-ups (out of scope for this DDL pass)
- Enforce enumerated `COMPRESS` value lists as `CHECK` constraints if the business
  requires domain validation.
- Evaluate `AUTOMATIC_CLUSTERING` on `FACT_TRANSACTION` / `FACT_MONTHLY_ACCOUNT_SNAPSHOT`.
- DML, stored procedures, macros, and BTEQ scripts (`dml/`) are **not** part of this
  conversion.
