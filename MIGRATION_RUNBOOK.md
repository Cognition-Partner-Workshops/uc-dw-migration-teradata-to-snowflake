# Teradata-to-Snowflake DDL Migration Runbook

This document records every translation decision made while converting the `BANKING_DW` Teradata DDL to Snowflake-compatible SQL. The converted files are in `snowflake/ddl/` and mirror the original `ddl/` directory structure.

---

## Table of Contents

1. [Scope](#scope)
2. [Directory Layout](#directory-layout)
3. [Global Translation Rules](#global-translation-rules)
4. [Table-Level Translations](#table-level-translations)
5. [View-Level Translations](#view-level-translations)
6. [Feature-by-Feature Reference](#feature-by-feature-reference)
7. [Post-Migration Validation Checklist](#post-migration-validation-checklist)

---

## Scope

| Category | Count | Source Path | Target Path |
|----------|-------|-------------|-------------|
| Tables | 7 | `ddl/tables/` | `snowflake/ddl/tables/` |
| Views | 3 | `ddl/views/` | `snowflake/ddl/views/` |

All objects belong to the `BANKING_DW` database/schema.

---

## Directory Layout

```
snowflake/
└── ddl/
    ├── tables/
    │   ├── 01_dim_customer.sql
    │   ├── 02_dim_account.sql
    │   ├── 03_dim_product.sql
    │   ├── 04_dim_branch.sql
    │   ├── 05_dim_date.sql
    │   ├── 06_fact_transaction.sql
    │   └── 07_fact_monthly_snapshot.sql
    └── views/
        ├── 01_vw_customer_360.sql
        ├── 02_vw_regulatory_large_transactions.sql
        └── 03_vw_branch_performance.sql
```

---

## Global Translation Rules

These rules apply across **all** converted files.

### 1. Table Type Keywords (`SET` / `MULTISET`)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `CREATE SET TABLE` | `CREATE OR REPLACE TABLE` | Snowflake has no SET/MULTISET distinction. All Snowflake tables allow duplicate rows. If duplicate prevention is required, enforce it via `PRIMARY KEY` or `UNIQUE` constraints. |
| `CREATE MULTISET TABLE` | `CREATE OR REPLACE TABLE` | Direct mapping; MULTISET already allows duplicates. |

### 2. Physical/Storage Attributes (Removed Entirely)

The following Teradata-specific physical attributes have no Snowflake equivalent and are removed without replacement:

| Attribute | Reason for Removal |
|-----------|--------------------|
| `NO FALLBACK` | Snowflake handles data redundancy and availability automatically via its micro-partition architecture. |
| `NO BEFORE JOURNAL` / `NO AFTER JOURNAL` | Snowflake uses Time Travel and Fail-safe instead of journaling. |
| `CHECKSUM = DEFAULT` | Snowflake performs internal integrity checks automatically. |
| `DEFAULT MERGEBLOCKRATIO` | Snowflake manages block merging internally via micro-partitions. |

### 3. `COMPRESS` Clauses (Removed)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COMPRESS (val1, val2, ...)` | *(removed)* | Snowflake automatically compresses all data. Column-level COMPRESS hints are unnecessary. |
| `COMPRESS ''` / `COMPRESS 0` | *(removed)* | Single-value compress for NULLs or common defaults is handled automatically. |

### 4. `NOT CASESPECIFIC` (Case-Insensitive Comparisons)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `VARCHAR(n) NOT CASESPECIFIC` | `VARCHAR(n) COLLATE 'en-ci'` | Snowflake is case-sensitive by default. `COLLATE 'en-ci'` provides case-insensitive comparisons at the column level, preserving the original Teradata behavior. |
| `col (NOT CASESPECIFIC)` in SELECT | Removed; relies on base table collation | Column-level cast in views removed since the underlying table columns already have `COLLATE 'en-ci'`. |

### 5. `FORMAT` Clauses

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `DATE FORMAT 'YYYY-MM-DD'` | `DATE` | Snowflake stores DATE natively; display formatting is a presentation-layer concern. Use `TO_CHAR(col, 'YYYY-MM-DD')` in queries if needed. |
| `(FORMAT 'ZZZ,ZZZ,ZZ9.99')` in SELECT | *(removed)* | No inline FORMAT in Snowflake. Use `TO_CHAR(col, '999,999,999.99')` in the reporting/presentation layer. |
| `TRIM(col (FORMAT '9999'))` | `CAST(col AS VARCHAR)` | The FORMAT cast was used to convert a numeric to a string with a format mask; replaced with a simple CAST. |

### 6. `BYTEINT` Data Type

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `BYTEINT` | `SMALLINT` | Snowflake does not support `BYTEINT`. `SMALLINT` is the closest small-integer type. `BOOLEAN` was considered for 0/1 flag columns but `SMALLINT` was chosen to preserve the original numeric semantics and avoid breaking downstream `CASE WHEN col = 1` logic. |

### 7. `GENERATED ALWAYS AS IDENTITY`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` | `AUTOINCREMENT START 1 INCREMENT 1` | Snowflake uses `AUTOINCREMENT` (or `IDENTITY`) syntax. Functionally equivalent. |

### 8. `TIMESTAMP` Defaults

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `TIMESTAMP(0) DEFAULT CURRENT_TIMESTAMP(0)` | `TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)` | Snowflake's default timestamp type is `TIMESTAMP_NTZ` (no time zone). The cast ensures precision matching. |
| `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` | `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ(0)` | Literal timestamp cast to the correct Snowflake type. |

### 9. `COLLECT STATISTICS` (Removed)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COLLECT STATISTICS COLUMN (col) ON table` | *(removed entirely)* | Snowflake automatically collects and maintains statistics. No manual intervention needed. |
| `COLLECT STATISTICS COLUMN (PARTITION) ON table` | *(removed)* | Partition-level statistics have no Snowflake equivalent. |

### 10. `COMMENT ON`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COMMENT ON TABLE ... IS '...'` | `COMMENT = '...'` on CREATE TABLE | Snowflake supports inline table comments. |
| `COMMENT ON COLUMN ... IS '...'` | `COMMENT ON COLUMN ... IS '...'` | Same syntax; fully compatible. |
| `COMMENT ON VIEW ... IS '...'` | `COMMENT ON VIEW ... IS '...'` | Same syntax; fully compatible. |

---

## Table-Level Translations

### Indexing and Partitioning

#### Primary Index -> Primary Key / Cluster By

| Teradata Construct | Snowflake Equivalent | Files Affected |
|--------------------|---------------------|----------------|
| `UNIQUE PRIMARY INDEX (col)` | `PRIMARY KEY (col)` constraint | `01_dim_customer`, `02_dim_account`, `03_dim_product`, `04_dim_branch`, `05_dim_date` |
| `PRIMARY INDEX (col1, col2)` (non-unique) | *(removed; no PK declared)* | `06_fact_transaction`, `07_fact_monthly_snapshot` |

**Decision:** For dimension tables with a `UNIQUE PRIMARY INDEX`, we declare a `PRIMARY KEY` constraint. Snowflake does not enforce PK uniqueness, but declaring it documents intent and aids BI tools. For fact tables with non-unique `PRIMARY INDEX`, no PK is declared since fact tables typically do not have a natural unique key.

#### Secondary Indexes

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `INDEX name (cols)` | *(removed)* | Snowflake does not support user-defined secondary indexes. Query performance is managed via micro-partitioning and clustering. |

#### Partitioned Primary Index (PPI)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `PARTITION BY RANGE_N(col BETWEEN date AND date EACH INTERVAL '1' YEAR)` | `CLUSTER BY (col)` | Snowflake uses automatic micro-partitioning. `CLUSTER BY` on the date column approximates partition elimination behavior. |
| `PARTITION BY RANGE_N(... EACH INTERVAL '1' MONTH, NO RANGE)` | `CLUSTER BY (col)` | The `NO RANGE` catch-all partition and monthly granularity are handled automatically by Snowflake's clustering. |

### Per-Table Notes

| File | Table | Teradata-Specific Features Converted |
|------|-------|--------------------------------------|
| `01_dim_customer.sql` | `DIM_CUSTOMER` | SET TABLE, UPI, NUPI, secondary indexes, PPI (yearly on ONBOARDING_DATE), IDENTITY, 8 COMPRESS clauses, 6 NOT CASESPECIFIC columns, 3 DATE FORMAT columns, BYTEINT, COLLECT STATISTICS x4 |
| `02_dim_account.sql` | `DIM_ACCOUNT` | MULTISET TABLE, UPI, NUPI, secondary indexes, PPI (yearly on OPENING_DATE), IDENTITY, 10 COMPRESS clauses, 4 NOT CASESPECIFIC columns, 2 DATE FORMAT columns, BYTEINT x2, COLLECT STATISTICS x5 |
| `03_dim_product.sql` | `DIM_PRODUCT` | SET TABLE, UPI, secondary indexes, 5 COMPRESS clauses, 3 NOT CASESPECIFIC columns, 2 DATE FORMAT columns, BYTEINT x2, COLLECT STATISTICS x2 |
| `04_dim_branch.sql` | `DIM_BRANCH` | SET TABLE, UPI, secondary indexes, 3 COMPRESS clauses, 6 NOT CASESPECIFIC columns, 2 DATE FORMAT columns, BYTEINT, SMALLINT COMPRESS, COLLECT STATISTICS x2 |
| `05_dim_date.sql` | `DIM_DATE` | SET TABLE, UPI, secondary indexes, 9 COMPRESS clauses, 3 DATE FORMAT columns, BYTEINT x14, COLLECT STATISTICS x3 |
| `06_fact_transaction.sql` | `FACT_TRANSACTION` | MULTISET TABLE, non-unique PI (composite), PPI (monthly on TRANSACTION_DATE with NO RANGE), 9 COMPRESS clauses, 5 NOT CASESPECIFIC columns, 3 DATE FORMAT columns, BYTEINT x2, COLLECT STATISTICS x7 (incl. PARTITION) |
| `07_fact_monthly_snapshot.sql` | `FACT_MONTHLY_ACCOUNT_SNAPSHOT` | MULTISET TABLE, non-unique PI (composite), PPI (monthly on SNAPSHOT_DATE with NO RANGE), 3 COMPRESS clauses, 1 DATE FORMAT column, COLLECT STATISTICS x3 (incl. PARTITION) |

---

## View-Level Translations

### View Syntax

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Standard Snowflake DDL syntax. |
| `LOCKING ROW FOR ACCESS` | *(removed)* | Snowflake's MVCC architecture provides consistent reads without explicit lock hints. |
| `SEL` | `SELECT` | `SEL` is a Teradata shorthand; Snowflake requires the full `SELECT` keyword. |

### Per-View Notes

#### `01_vw_customer_360.sql` — VW_CUSTOMER_360

| Feature | Teradata Original | Snowflake Conversion | Notes |
|---------|-------------------|----------------------|-------|
| `ZEROIFNULL()` | `ZEROIFNULL(expr)` | `ZEROIFNULL(expr)` | Natively supported in Snowflake — no change needed. |
| Inline `FORMAT` | `expr (FORMAT 'ZZZ,ZZZ,ZZ9.99')` | *(removed)* | Display formatting moved to presentation layer. |
| Date arithmetic | `(CURRENT_DATE - col) / 365.25` | `DATEDIFF('day', col, CURRENT_DATE) / 365.25` | Snowflake does not support direct date subtraction yielding an integer; `DATEDIFF` is used instead. |
| Date filter | `col >= CURRENT_DATE - 90` | `col >= DATEADD('day', -90, CURRENT_DATE)` | Snowflake requires `DATEADD` for date arithmetic in filters. |
| Correlated subquery with `QUALIFY` | Inline scalar `SEL ... QUALIFY ROW_NUMBER()=1` | Rewritten as a derived table with `QUALIFY` | The Teradata correlated scalar subquery pattern is not directly portable. Rewritten as a pre-aggregated derived table joined via `LEFT JOIN`. |

#### `02_vw_regulatory_large_transactions.sql` — VW_REGULATORY_LARGE_TRANSACTIONS

| Feature | Teradata Original | Snowflake Conversion | Notes |
|---------|-------------------|----------------------|-------|
| `HASHROW()` | `HASHROW(col1, col2)` | `HASH(col1, col2)` | `HASHROW` is Teradata-specific. Snowflake's `HASH()` provides equivalent row-hashing functionality. Note: hash values will differ between platforms. |
| Column-level `NOT CASESPECIFIC` | `c.FIRST_NAME (NOT CASESPECIFIC)` | `c.FIRST_NAME` | The inline cast is removed; case-insensitivity is handled by the `COLLATE 'en-ci'` on the base table column. |
| `QUALIFY` | `QUALIFY ROW_NUMBER() OVER (...) = 1` | `QUALIFY ROW_NUMBER() OVER (...) = 1` | Snowflake natively supports `QUALIFY` — no change needed. |

#### `03_vw_branch_performance.sql` — VW_BRANCH_PERFORMANCE

| Feature | Teradata Original | Snowflake Conversion | Notes |
|---------|-------------------|----------------------|-------|
| `CSUM()` | `CSUM(SUM(col), order_col)` | `SUM(SUM(col)) OVER (PARTITION BY branch ORDER BY order_col ROWS UNBOUNDED PRECEDING)` | Teradata's `CSUM` is a cumulative sum ordered aggregate. Converted to standard SQL `SUM() OVER()` window function with `ROWS UNBOUNDED PRECEDING`. Added `PARTITION BY b.BRANCH_ID` to scope accumulation per branch. |
| `MAVG()` | `MAVG(SUM(col), 3, order_col)` | `AVG(SUM(col)) OVER (PARTITION BY branch ORDER BY order_col ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` | Teradata's `MAVG(expr, n, order)` computes a moving average over the last `n` rows. Converted to `AVG() OVER (ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW)`. Added `PARTITION BY b.BRANCH_ID`. |
| `NULLIFZERO()` | `NULLIFZERO(expr)` | `NULLIFZERO(expr)` | Natively supported in Snowflake — no change needed. |
| `TRIM(col (FORMAT '9999'))` | Numeric-to-string with format | `CAST(col AS VARCHAR)` | The FORMAT mask inside TRIM was used to convert a number to a formatted string. Replaced with a simple CAST. |
| Inline `FORMAT` on aggregates | `SUM(col) (FORMAT 'ZZZ,...')` | *(removed)* | Display formatting deferred to presentation layer. |
| `ADD_MONTHS()` | `ADD_MONTHS(CURRENT_DATE, -24)` | `DATEADD('month', -24, CURRENT_DATE)` | Both are supported in Snowflake, but `DATEADD` is the idiomatic Snowflake function. `ADD_MONTHS` would also work. |

---

## Feature-by-Feature Reference

Summary of all Teradata-specific features encountered and their disposition:

| # | Teradata Feature | Disposition | Snowflake Equivalent |
|---|-----------------|-------------|----------------------|
| 1 | `SET TABLE` | Removed | `CREATE OR REPLACE TABLE` |
| 2 | `MULTISET TABLE` | Removed | `CREATE OR REPLACE TABLE` |
| 3 | `NO FALLBACK` | Removed | N/A (automatic) |
| 4 | `NO BEFORE/AFTER JOURNAL` | Removed | N/A (Time Travel) |
| 5 | `CHECKSUM = DEFAULT` | Removed | N/A (automatic) |
| 6 | `DEFAULT MERGEBLOCKRATIO` | Removed | N/A (automatic) |
| 7 | `PRIMARY INDEX` (non-unique) | Removed | N/A |
| 8 | `UNIQUE PRIMARY INDEX` | Replaced | `PRIMARY KEY` constraint |
| 9 | `INDEX name (cols)` (secondary) | Removed | N/A |
| 10 | `PARTITION BY RANGE_N` | Replaced | `CLUSTER BY (col)` |
| 11 | `NO RANGE` (catch-all partition) | Removed | N/A (automatic) |
| 12 | `COMPRESS` | Removed | N/A (automatic) |
| 13 | `NOT CASESPECIFIC` | Replaced | `COLLATE 'en-ci'` |
| 14 | `FORMAT` (column-level) | Removed | Use `TO_CHAR()` in queries |
| 15 | `FORMAT` (inline in SELECT) | Removed | Use `TO_CHAR()` in queries |
| 16 | `BYTEINT` | Replaced | `SMALLINT` |
| 17 | `GENERATED ALWAYS AS IDENTITY` | Replaced | `AUTOINCREMENT` |
| 18 | `COLLECT STATISTICS` | Removed | N/A (automatic) |
| 19 | `REPLACE VIEW` | Replaced | `CREATE OR REPLACE VIEW` |
| 20 | `LOCKING ROW FOR ACCESS` | Removed | N/A (MVCC) |
| 21 | `SEL` | Replaced | `SELECT` |
| 22 | `QUALIFY` | Retained | Natively supported |
| 23 | `ZEROIFNULL()` | Retained | Natively supported |
| 24 | `NULLIFZERO()` | Retained | Natively supported |
| 25 | `HASHROW()` | Replaced | `HASH()` |
| 26 | `CSUM()` | Replaced | `SUM() OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING)` |
| 27 | `MAVG()` | Replaced | `AVG() OVER (ORDER BY ... ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW)` |
| 28 | `CURRENT_DATE - col` (date math) | Replaced | `DATEDIFF('day', col, CURRENT_DATE)` |
| 29 | `ADD_MONTHS()` | Replaced | `DATEADD('month', n, date)` |
| 30 | `COMMENT ON TABLE/COLUMN/VIEW` | Retained | Supported with same or inline syntax |

---

## Post-Migration Validation Checklist

After deploying the Snowflake DDL, validate the migration with these checks:

- [ ] **Schema verification**: All 7 tables and 3 views are created successfully in Snowflake
- [ ] **Column counts**: Each table has the same number of columns as the Teradata source
- [ ] **Data type mapping**: Verify column data types match expectations (especially `SMALLINT` for former `BYTEINT` columns)
- [ ] **Default values**: Confirm defaults are applied correctly (e.g., `'NOR'`, `'PENDING'`, `0`, `1`)
- [ ] **Identity columns**: Verify `AUTOINCREMENT` works for `CUSTOMER_KEY` and `ACCOUNT_KEY`
- [ ] **Case-insensitive behavior**: Test that `COLLATE 'en-ci'` columns perform case-insensitive comparisons (e.g., `WHERE CITY = 'oslo'` matches `'Oslo'`)
- [ ] **Clustering**: Verify `CLUSTER BY` is set on date-partitioned tables
- [ ] **View compilation**: All 3 views compile without errors
- [ ] **QUALIFY in views**: Verify `QUALIFY` filters work correctly in `VW_CUSTOMER_360` and `VW_REGULATORY_LARGE_TRANSACTIONS`
- [ ] **Window functions**: Validate `CUMULATIVE_FEES_YTD` and `MOVING_AVG_VOLUME_3M` in `VW_BRANCH_PERFORMANCE` produce correct results
- [ ] **HASH() output**: Note that `HASH()` values will differ from Teradata `HASHROW()` — update any downstream hash comparisons
- [ ] **Row count validation**: After data load, compare row counts between Teradata and Snowflake using queries in `data/validation/`
- [ ] **Comments**: Verify table and column comments are applied
