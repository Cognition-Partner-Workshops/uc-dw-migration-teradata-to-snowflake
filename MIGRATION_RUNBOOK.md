# Teradata to Snowflake DDL Migration Runbook

This document records every translation decision made while converting the
`BANKING_DW` data warehouse DDL from Teradata SQL to Snowflake SQL.

Converted files are located in **`snowflake/`**, mirroring the original
`ddl/` directory structure.

| Source (Teradata) | Target (Snowflake) |
|---|---|
| `ddl/tables/01_dim_customer.sql` | `snowflake/tables/01_dim_customer.sql` |
| `ddl/tables/02_dim_account.sql` | `snowflake/tables/02_dim_account.sql` |
| `ddl/tables/03_dim_product.sql` | `snowflake/tables/03_dim_product.sql` |
| `ddl/tables/04_dim_branch.sql` | `snowflake/tables/04_dim_branch.sql` |
| `ddl/tables/05_dim_date.sql` | `snowflake/tables/05_dim_date.sql` |
| `ddl/tables/06_fact_transaction.sql` | `snowflake/tables/06_fact_transaction.sql` |
| `ddl/tables/07_fact_monthly_snapshot.sql` | `snowflake/tables/07_fact_monthly_snapshot.sql` |
| `ddl/views/01_vw_customer_360.sql` | `snowflake/views/01_vw_customer_360.sql` |
| `ddl/views/02_vw_regulatory_large_transactions.sql` | `snowflake/views/02_vw_regulatory_large_transactions.sql` |
| `ddl/views/03_vw_branch_performance.sql` | `snowflake/views/03_vw_branch_performance.sql` |

---

## 1. Table-Level Physical Attributes

### 1.1 SET / MULTISET Tables

| Teradata | Snowflake | Rationale |
|---|---|---|
| `CREATE SET TABLE` | `CREATE OR REPLACE TABLE` | Teradata SET tables reject duplicate rows at insert time. Snowflake has no SET table concept; all tables allow duplicates. Duplicate prevention should be handled by application logic or MERGE statements. |
| `CREATE MULTISET TABLE` | `CREATE OR REPLACE TABLE` | Direct equivalent; both allow duplicates. |

### 1.2 Physical Storage Clauses

The following Teradata-specific physical clauses are **removed entirely** because
Snowflake manages storage, journaling, and checksums automatically:

| Removed Clause | Purpose in Teradata |
|---|---|
| `NO FALLBACK` | Disables row-level data redundancy across AMPs |
| `NO BEFORE JOURNAL` / `NO AFTER JOURNAL` | Controls change-capture journaling |
| `CHECKSUM = DEFAULT` | Row-level checksum validation |
| `DEFAULT MERGEBLOCKRATIO` | Controls merge-block compaction ratio |

**Affected files:** All 7 table DDLs.

---

## 2. Data Types

### 2.1 BYTEINT to SMALLINT

| Teradata | Snowflake | Rationale |
|---|---|---|
| `BYTEINT` | `SMALLINT` | Snowflake does not support `BYTEINT`. `SMALLINT` is the smallest integer type available. Used for flag columns (`IS_ACTIVE`, `IS_WEEKEND`, etc.). |

**Affected files:** `01_dim_customer`, `02_dim_account`, `03_dim_product`,
`04_dim_branch`, `05_dim_date`, `06_fact_transaction`.

### 2.2 TIMESTAMP and Defaults

| Teradata | Snowflake | Rationale |
|---|---|---|
| `TIMESTAMP(0)` | `TIMESTAMP_NTZ(0)` | Snowflake defaults to `TIMESTAMP_NTZ` for timezone-naive timestamps, matching Teradata's `TIMESTAMP` semantics. |
| `DEFAULT CURRENT_TIMESTAMP(0)` | `DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)` | Explicit cast ensures precision and type alignment. |
| `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` | `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ(0)` | Snowflake requires cast syntax for timestamp literals in defaults. |
| `TIMESTAMP(6)` | `TIMESTAMP_NTZ(6)` | Retained precision; Snowflake supports up to nanosecond (9). |
| `TIME(0)` | `TIME(0)` | Directly supported in Snowflake. |

### 2.3 Other Data Types

| Teradata | Snowflake | Notes |
|---|---|---|
| `INTEGER` | `INTEGER` | Direct equivalent. |
| `BIGINT` | `BIGINT` | Direct equivalent. |
| `SMALLINT` | `SMALLINT` | Direct equivalent. |
| `DECIMAL(p,s)` | `DECIMAL(p,s)` | Direct equivalent. |
| `VARCHAR(n)` | `VARCHAR(n)` | Direct equivalent. |
| `CHAR(n)` | `CHAR(n)` | Direct equivalent. |
| `DATE` | `DATE` | Direct equivalent. |

---

## 3. Column-Level Features

### 3.1 COMPRESS

| Teradata | Snowflake | Rationale |
|---|---|---|
| `COMPRESS ('val1', 'val2', ...)` | *(removed)* | Teradata COMPRESS stores frequently occurring values in the column header to save storage. Snowflake applies automatic columnar compression (Zstandard, LZO, etc.) that is at least as effective. No manual intervention needed. |
| `COMPRESS 0` / `COMPRESS ''` | *(removed)* | Single-value compression; same rationale. |

**Affected files:** All 7 table DDLs (40+ column occurrences).

### 3.2 NOT CASESPECIFIC

| Teradata | Snowflake | Rationale |
|---|---|---|
| `NOT CASESPECIFIC` (column definition) | *(removed)* | Teradata `NOT CASESPECIFIC` makes string comparisons case-insensitive for that column. Snowflake string comparisons are case-sensitive by default, but the collation can be set at the database or column level if needed. Removing the clause keeps the DDL clean; if case-insensitive behavior is required, use `COLLATE 'en-ci'` or apply `UPPER()`/`LOWER()` in queries. |
| `(NOT CASESPECIFIC)` (inline in SELECT) | *(removed)* | Same reasoning; removed from view `02_vw_regulatory_large_transactions`. |

**Affected files:** All 7 table DDLs, view `02_vw_regulatory_large_transactions`.

> **Action item:** Verify with business users whether any columns require
> case-insensitive comparison semantics. If so, add `COLLATE 'en-ci'` to those
> columns or adjust query predicates.

### 3.3 FORMAT

| Teradata | Snowflake | Rationale |
|---|---|---|
| `DATE FORMAT 'YYYY-MM-DD'` | *(removed)* | Teradata `FORMAT` controls display formatting at the column level. Snowflake does not support inline FORMAT on column definitions. Date display format is controlled by session parameters (`DATE_OUTPUT_FORMAT`) or explicit `TO_CHAR()` calls. |
| `(FORMAT 'ZZZ,ZZZ,ZZ9.99')` (inline in SELECT) | *(removed)* | Presentation-layer formatting. Use `TO_CHAR(col, '999,999,999.99')` at the reporting layer if needed. |
| `TRIM(col (FORMAT '9999'))` | `TRIM(TO_CHAR(col))` | Teradata FORMAT inside TRIM converted to Snowflake `TO_CHAR` for string representation of numeric values. |

**Affected files:** All 7 table DDLs (DATE columns), views `01_vw_customer_360`,
`03_vw_branch_performance`.

### 3.4 GENERATED ALWAYS AS IDENTITY

| Teradata | Snowflake | Rationale |
|---|---|---|
| `GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` | `AUTOINCREMENT START 1 INCREMENT 1` | Snowflake uses `AUTOINCREMENT` (or `IDENTITY`) syntax. Both create auto-incrementing surrogate keys. `AUTOINCREMENT` is the preferred Snowflake keyword. |

**Affected files:** `01_dim_customer` (`CUSTOMER_KEY`), `02_dim_account` (`ACCOUNT_KEY`).

---

## 4. Indexing and Distribution

### 4.1 PRIMARY INDEX / UNIQUE PRIMARY INDEX

| Teradata | Snowflake | Rationale |
|---|---|---|
| `UNIQUE PRIMARY INDEX (col)` | `PRIMARY KEY (col)` constraint | Teradata UPI determines both data distribution across AMPs and uniqueness enforcement. Snowflake PRIMARY KEY is a logical constraint (not enforced) that serves as documentation and metadata for the optimizer. |
| `PRIMARY INDEX (col1, col2)` (non-unique) | `CLUSTER BY (partition_col)` | Non-unique PI determines data distribution but not uniqueness. Snowflake has no direct equivalent; CLUSTER BY provides similar query-pruning benefits. |

**Affected files:** All 7 table DDLs.

### 4.2 Secondary Indexes (NUPI, Named Indexes)

| Teradata | Snowflake | Rationale |
|---|---|---|
| `INDEX name (col)` | *(removed; documented as comments)* | Snowflake does not support traditional B-tree secondary indexes. The original index definitions are preserved as SQL comments for reference. For high-cardinality lookup columns, consider enabling **Search Optimization Service**. |

**Affected files:** `01_dim_customer` (3 indexes), `02_dim_account` (4 indexes),
`03_dim_product` (2 indexes), `04_dim_branch` (2 indexes), `05_dim_date` (2 indexes).

---

## 5. Partitioning

### 5.1 PARTITION BY RANGE_N

| Teradata | Snowflake | Rationale |
|---|---|---|
| `PARTITION BY RANGE_N(col BETWEEN date1 AND date2 EACH INTERVAL '1' YEAR)` | `CLUSTER BY (col)` | Teradata range partitioning physically separates data into partitions for elimination. Snowflake's micro-partitioning with `CLUSTER BY` achieves similar pruning. The date column is used as the clustering key. |
| `PARTITION BY RANGE_N(... EACH INTERVAL '1' MONTH, NO RANGE)` | `CLUSTER BY (col)` | Monthly partitioning and `NO RANGE` catch-all both handled by Snowflake's automatic micro-partitioning. |

**Affected files:**
- `01_dim_customer`: `RANGE_N(ONBOARDING_DATE ... EACH '1' YEAR)` -> `CLUSTER BY (ONBOARDING_DATE)`
- `02_dim_account`: `RANGE_N(OPENING_DATE ... EACH '1' YEAR)` -> `CLUSTER BY (OPENING_DATE)`
- `06_fact_transaction`: `RANGE_N(TRANSACTION_DATE ... EACH '1' MONTH, NO RANGE)` -> `CLUSTER BY (TRANSACTION_DATE)`
- `07_fact_monthly_snapshot`: `RANGE_N(SNAPSHOT_DATE ... EACH '1' MONTH, NO RANGE)` -> `CLUSTER BY (SNAPSHOT_DATE)`

> **Note:** Small dimension tables (`DIM_PRODUCT`, `DIM_BRANCH`, `DIM_DATE`) do
> not have Teradata partitioning and do not need `CLUSTER BY` in Snowflake.

---

## 6. Statistics

### 6.1 COLLECT STATISTICS

| Teradata | Snowflake | Rationale |
|---|---|---|
| `COLLECT STATISTICS COLUMN (col) ON schema.table` | *(removed)* | Teradata requires explicit statistics collection for the optimizer. Snowflake automatically collects and maintains statistics on all columns via its metadata layer. No manual action is needed. |

**Affected files:** All 7 table DDLs (total of 22 COLLECT STATISTICS statements removed).

---

## 7. View-Level Translations

### 7.1 Structural Changes

| Teradata | Snowflake | Rationale |
|---|---|---|
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Snowflake requires `CREATE OR REPLACE VIEW` syntax. |
| `LOCKING ROW FOR ACCESS` | *(removed)* | Teradata dirty-read hint for concurrent access. Snowflake uses MVCC (Multi-Version Concurrency Control) and does not need locking hints. |
| `SEL` | `SELECT` | Teradata abbreviation; Snowflake requires full `SELECT` keyword. |

**Affected files:** All 3 view DDLs.

### 7.2 QUALIFY Clause

| Teradata | Snowflake | Decision |
|---|---|---|
| `QUALIFY ROW_NUMBER() OVER (...) = 1` | `QUALIFY ROW_NUMBER() OVER (...) = 1` | **Retained as-is.** Snowflake natively supports the `QUALIFY` clause with identical syntax and semantics. |

**Affected files:** `01_vw_customer_360`, `02_vw_regulatory_large_transactions`.

### 7.3 ZEROIFNULL / NULLIFZERO

| Teradata | Snowflake | Decision |
|---|---|---|
| `ZEROIFNULL(expr)` | `ZEROIFNULL(expr)` | **Retained as-is.** Snowflake natively supports `ZEROIFNULL`. |
| `NULLIFZERO(expr)` | `NULLIFZERO(expr)` | **Retained as-is.** Snowflake natively supports `NULLIFZERO`. |

**Affected files:** `01_vw_customer_360` (`ZEROIFNULL`), `03_vw_branch_performance` (`NULLIFZERO`).

### 7.4 CSUM (Cumulative Sum)

| Teradata | Snowflake | Rationale |
|---|---|---|
| `CSUM(SUM(expr), sort_col)` | `SUM(SUM(expr)) OVER (PARTITION BY branch, year ORDER BY sort_col ROWS UNBOUNDED PRECEDING)` | Teradata `CSUM` is an ordered analytical function that computes a running total. In Snowflake, this becomes an explicit `SUM() OVER()` window function with `ROWS UNBOUNDED PRECEDING`. The PARTITION BY includes `FLOOR(SNAPSHOT_MONTH_KEY / 100)` to extract the year, resetting the cumulative sum each calendar year for a true YTD calculation. |

**Affected files:** `03_vw_branch_performance` (line 24 in source).

### 7.5 MAVG (Moving Average)

| Teradata | Snowflake | Rationale |
|---|---|---|
| `MAVG(SUM(expr), 3, sort_col)` | `AVG(SUM(expr)) OVER (PARTITION BY branch ORDER BY sort_col ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` | Teradata `MAVG(expr, n, sort_col)` computes a moving average over `n` rows. In Snowflake, this is expressed as `AVG() OVER()` with a `ROWS BETWEEN (n-1) PRECEDING AND CURRENT ROW` frame. For a 3-month moving average, the frame is `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW`. |

**Affected files:** `03_vw_branch_performance` (line 26 in source).

### 7.6 HASHROW

| Teradata | Snowflake | Rationale |
|---|---|---|
| `HASHROW(col1, col2)` | `HASH(col1, col2)` | Teradata `HASHROW` generates a deterministic hash for one or more columns. Snowflake's `HASH()` function serves the same purpose. Note: the hash algorithms differ, so hash values will not be identical between platforms. Validation queries comparing hashes must run natively on each platform. |

**Affected files:** `02_vw_regulatory_large_transactions` (line 38 in source).

### 7.7 Date Arithmetic

| Teradata | Snowflake | Rationale |
|---|---|---|
| `(CURRENT_DATE - date_col) / 365.25` | `DATEDIFF('DAY', date_col, CURRENT_DATE) / 365.25` | Teradata allows direct date subtraction returning an interval. Snowflake's `DATEDIFF` is more explicit and portable. Wrapped in `ROUND(..., 1)` for the same decimal precision. |
| `CURRENT_DATE - 90` | `DATEADD('DAY', -90, CURRENT_DATE)` | Snowflake does not support direct integer subtraction from dates; `DATEADD` is the standard approach. |
| `ADD_MONTHS(date, n)` | `ADD_MONTHS(date, n)` | **Retained as-is.** Snowflake natively supports `ADD_MONTHS`. |

**Affected files:** `01_vw_customer_360`, `03_vw_branch_performance`.

### 7.8 RANK() OVER

| Teradata | Snowflake | Decision |
|---|---|---|
| `RANK() OVER (PARTITION BY ... ORDER BY ...)` | `RANK() OVER (PARTITION BY ... ORDER BY ...)` | **Retained as-is.** Standard SQL window function supported by both platforms. |

**Affected files:** `03_vw_branch_performance`.

---

## 8. Comment Syntax

| Teradata | Snowflake | Decision |
|---|---|---|
| `COMMENT ON TABLE schema.table IS '...'` | `COMMENT ON TABLE schema.table IS '...'` | **Retained as-is.** Identical syntax in Snowflake. |
| `COMMENT ON COLUMN schema.table.col IS '...'` | `COMMENT ON COLUMN schema.table.col IS '...'` | **Retained as-is.** Identical syntax in Snowflake. |
| `COMMENT ON VIEW schema.view IS '...'` | `COMMENT ON VIEW schema.view IS '...'` | **Retained as-is.** Identical syntax in Snowflake. |

---

## 9. Deployment Order

Tables must be created before views that reference them. The recommended
execution order follows the original file numbering:

### Tables (run first)
1. `snowflake/tables/01_dim_customer.sql`
2. `snowflake/tables/02_dim_account.sql`
3. `snowflake/tables/03_dim_product.sql`
4. `snowflake/tables/04_dim_branch.sql`
5. `snowflake/tables/05_dim_date.sql`
6. `snowflake/tables/06_fact_transaction.sql`
7. `snowflake/tables/07_fact_monthly_snapshot.sql`

### Views (run after all tables exist)
1. `snowflake/views/01_vw_customer_360.sql`
2. `snowflake/views/02_vw_regulatory_large_transactions.sql`
3. `snowflake/views/03_vw_branch_performance.sql`

---

## 10. Post-Migration Action Items

| # | Action | Priority | Notes |
|---|---|---|---|
| 1 | **Validate case-sensitivity behavior** | High | Teradata `NOT CASESPECIFIC` columns may need `COLLATE 'en-ci'` or query-level `UPPER()`/`LOWER()` in Snowflake if case-insensitive matching is required. |
| 2 | **Review AUTOINCREMENT gap behavior** | Medium | Snowflake AUTOINCREMENT may produce non-contiguous values. Confirm this is acceptable for `CUSTOMER_KEY` and `ACCOUNT_KEY`. |
| 3 | **Enable Search Optimization** | Low | For high-cardinality lookups (e.g., `CUSTOMER_ID`, `ACCOUNT_ID`), consider enabling Snowflake's Search Optimization Service as a replacement for secondary indexes. |
| 4 | **Update validation checksums** | High | `HASHROW` and `HASH` produce different values. Update `data/validation/checksum_queries.sql` to use `HASH()` for the Snowflake target. |
| 5 | **Test SET table duplicate behavior** | Medium | Tables originally defined as `SET` (which reject duplicate rows) are now standard Snowflake tables (which allow duplicates). Confirm ETL pipelines handle deduplication via `MERGE` or `QUALIFY`. |
| 6 | **Configure date/time session parameters** | Low | Set `DATE_OUTPUT_FORMAT`, `TIMESTAMP_OUTPUT_FORMAT` at the warehouse or session level if specific display formats are needed. |
| 7 | **Convert macros and procedures** | High | The AML screening macro (`dml/macros/macro_aml_screening.sql`) needs separate conversion to a Snowflake stored procedure or Snowflake Task. Not in scope for this DDL migration. |
| 8 | **Convert validation queries** | Medium | `data/validation/checksum_queries.sql` uses `HASHROW`; update to `HASH()` and adjust Teradata-specific syntax for the Snowflake target. |

---

## 11. Summary of Changes by File

### Tables

| File | Key Conversions |
|---|---|
| `01_dim_customer.sql` | SET -> standard; IDENTITY -> AUTOINCREMENT; UPI -> PK; 3 secondary indexes removed; RANGE_N yearly -> CLUSTER BY; 14 COMPRESS clauses removed; 6 NOT CASESPECIFIC removed; 4 FORMAT removed; BYTEINT -> SMALLINT; 4 COLLECT STATS removed |
| `02_dim_account.sql` | MULTISET -> standard; IDENTITY -> AUTOINCREMENT; UPI -> PK; 4 secondary indexes removed; RANGE_N yearly -> CLUSTER BY; 12 COMPRESS clauses removed; 5 NOT CASESPECIFIC removed; 2 FORMAT removed; BYTEINT -> SMALLINT; 5 COLLECT STATS removed |
| `03_dim_product.sql` | SET -> standard; UPI -> PK; 2 secondary indexes removed; 7 COMPRESS clauses removed; 3 NOT CASESPECIFIC removed; 2 FORMAT removed; BYTEINT -> SMALLINT; 2 COLLECT STATS removed |
| `04_dim_branch.sql` | SET -> standard; UPI -> PK; 2 secondary indexes removed; 6 COMPRESS clauses removed; 5 NOT CASESPECIFIC removed; 2 FORMAT removed; BYTEINT -> SMALLINT; 2 COLLECT STATS removed |
| `05_dim_date.sql` | SET -> standard; UPI -> PK; 2 secondary indexes removed; 10 COMPRESS clauses removed; 3 FORMAT removed; BYTEINT -> SMALLINT; 3 COLLECT STATS removed |
| `06_fact_transaction.sql` | MULTISET -> standard; PI -> CLUSTER BY; RANGE_N monthly + NO RANGE -> CLUSTER BY; 11 COMPRESS clauses removed; 5 NOT CASESPECIFIC removed; 4 FORMAT removed; BYTEINT -> SMALLINT; 7 COLLECT STATS removed |
| `07_fact_monthly_snapshot.sql` | MULTISET -> standard; PI -> CLUSTER BY; RANGE_N monthly + NO RANGE -> CLUSTER BY; 4 COMPRESS clauses removed; 0 NOT CASESPECIFIC; 1 FORMAT removed; SMALLINT COMPRESS simplified; 3 COLLECT STATS removed |

### Views

| File | Key Conversions |
|---|---|
| `01_vw_customer_360.sql` | REPLACE VIEW -> CREATE OR REPLACE VIEW; LOCKING removed; SEL -> SELECT; FORMAT inline removed; date arithmetic -> DATEDIFF/DATEADD; ZEROIFNULL/QUALIFY retained |
| `02_vw_regulatory_large_transactions.sql` | REPLACE VIEW -> CREATE OR REPLACE VIEW; LOCKING removed; SEL -> SELECT; inline (NOT CASESPECIFIC) removed; HASHROW -> HASH; QUALIFY retained |
| `03_vw_branch_performance.sql` | REPLACE VIEW -> CREATE OR REPLACE VIEW; LOCKING removed; SEL -> SELECT; CSUM -> SUM OVER window; MAVG -> AVG OVER window; FORMAT inline removed; TRIM(col (FORMAT)) -> TRIM(TO_CHAR(col)); NULLIFZERO/RANK/ADD_MONTHS retained |
