# Teradata → Snowflake DDL Migration Runbook

This runbook documents every translation decision made when converting the Teradata DDL (tables and views) in `ddl/` to Snowflake-compatible SQL in `snowflake/`.

---

## Table of Contents

1. [Scope](#scope)
2. [File Inventory](#file-inventory)
3. [Translation Decisions — Table-Level](#translation-decisions--table-level)
4. [Translation Decisions — Column-Level](#translation-decisions--column-level)
5. [Translation Decisions — Views](#translation-decisions--views)
6. [Schema and Naming](#schema-and-naming)
7. [Execution Order](#execution-order)
8. [Post-Migration Validation Checklist](#post-migration-validation-checklist)

---

## Scope

| Category | Count | Source Directory | Target Directory |
|----------|-------|------------------|------------------|
| Tables   | 7     | `ddl/tables/`     | `snowflake/tables/` |
| Views    | 3     | `ddl/views/`      | `snowflake/views/`  |

---

## File Inventory

### Tables

| # | File | Teradata Object | Type |
|---|------|----------------|------|
| 1 | `01_dim_customer.sql` | `BANKING_DW.DIM_CUSTOMER` | SET table, PPI |
| 2 | `02_dim_account.sql` | `BANKING_DW.DIM_ACCOUNT` | MULTISET table, PPI |
| 3 | `03_dim_product.sql` | `BANKING_DW.DIM_PRODUCT` | SET table |
| 4 | `04_dim_branch.sql` | `BANKING_DW.DIM_BRANCH` | SET table |
| 5 | `05_dim_date.sql` | `BANKING_DW.DIM_DATE` | SET table |
| 6 | `06_fact_transaction.sql` | `BANKING_DW.FACT_TRANSACTION` | MULTISET table, PPI |
| 7 | `07_fact_monthly_snapshot.sql` | `BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT` | MULTISET table, PPI |

### Views

| # | File | Teradata Object | Key Features |
|---|------|----------------|--------------|
| 1 | `01_vw_customer_360.sql` | `BANKING_DW.VW_CUSTOMER_360` | QUALIFY, ZEROIFNULL, FORMAT, correlated subquery |
| 2 | `02_vw_regulatory_large_transactions.sql` | `BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS` | QUALIFY, HASHROW, NOT CASESPECIFIC in SELECT |
| 3 | `03_vw_branch_performance.sql` | `BANKING_DW.VW_BRANCH_PERFORMANCE` | CSUM, MAVG, FORMAT, NULLIFZERO |

---

## Translation Decisions — Table-Level

### 1. `SET` / `MULTISET` Tables

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `CREATE SET TABLE` | `CREATE OR REPLACE TABLE` | Snowflake tables are always multiset (allow duplicates). Duplicate prevention should be enforced at the ETL/ingestion layer, not the DDL. |
| `CREATE MULTISET TABLE` | `CREATE OR REPLACE TABLE` | Direct mapping — both allow duplicates. |

**Affected files:** All 7 tables.

### 2. Physical/Storage Attributes

| Teradata Clause | Snowflake Action | Rationale |
|----------------|------------------|-----------|
| `NO FALLBACK` | Removed | Snowflake provides built-in redundancy (3× replication in standard edition). |
| `NO BEFORE JOURNAL` / `NO AFTER JOURNAL` | Removed | Snowflake uses Time Travel and Fail-safe instead of journaling. |
| `CHECKSUM = DEFAULT` | Removed | Snowflake manages data integrity automatically. |
| `DEFAULT MERGEBLOCKRATIO` | Removed | Snowflake manages block-level storage internally. |

**Affected files:** All 7 tables.

### 3. Primary Index (PI) → Clustering Keys

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `UNIQUE PRIMARY INDEX (col)` | Removed; `CLUSTER BY (col)` added where beneficial | Snowflake has no primary index concept. Clustering keys guide micro-partition pruning for large tables. |
| `PRIMARY INDEX (col1, col2)` (non-unique) | `CLUSTER BY (col1, col2)` | Same rationale. Non-unique PI maps directly to clustering key. |
| Secondary indexes (`INDEX name (cols)`) | Removed entirely | Snowflake does not support secondary indexes. Query performance relies on micro-partition pruning and clustering. |

**Clustering key decisions:**

| Table | Teradata PI | Snowflake CLUSTER BY | Rationale |
|-------|------------|---------------------|-----------|
| `DIM_CUSTOMER` | `UPI (CUSTOMER_KEY)`, PPI on `ONBOARDING_DATE` | `CLUSTER BY (ONBOARDING_DATE)` | Date-based pruning for SCD queries. |
| `DIM_ACCOUNT` | `UPI (ACCOUNT_KEY)`, PPI on `OPENING_DATE` | `CLUSTER BY (OPENING_DATE)` | Date-based pruning. |
| `DIM_PRODUCT` | `UPI (PRODUCT_ID)` | None | Small dimension table — clustering unnecessary. |
| `DIM_BRANCH` | `UPI (BRANCH_ID)` | None | Small dimension table. |
| `DIM_DATE` | `UPI (DATE_KEY)` | None | Small dimension table. |
| `FACT_TRANSACTION` | `PI (ACCOUNT_KEY, TRANSACTION_DATE)`, PPI on `TRANSACTION_DATE` | `CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)` | Date-first clustering for range scans; account for point lookups. |
| `FACT_MONTHLY_SNAPSHOT` | `PI (ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)`, PPI on `SNAPSHOT_DATE` | `CLUSTER BY (SNAPSHOT_DATE, ACCOUNT_KEY)` | Date-first for monthly partition pruning. |

### 4. Partitioned Primary Index (PPI) — `RANGE_N`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `PARTITION BY RANGE_N(col BETWEEN date AND date EACH INTERVAL '1' YEAR)` | `CLUSTER BY (col)` | Snowflake uses automatic micro-partitioning. `CLUSTER BY` provides equivalent query pruning benefits without manual range definitions. |
| `NO RANGE` catch-all partition | Removed | Snowflake handles out-of-range values automatically in micro-partitions. |

**Affected files:** `01_dim_customer`, `02_dim_account`, `06_fact_transaction`, `07_fact_monthly_snapshot`.

### 5. `COLLECT STATISTICS`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COLLECT STATISTICS COLUMN (col) ON table` | Removed entirely | Snowflake collects and maintains statistics automatically. No manual intervention required. |

**Affected files:** All 7 tables.

### 6. `COMMENT ON`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COMMENT ON TABLE schema.table IS '...'` | `COMMENT = '...'` clause on `CREATE TABLE` | Snowflake supports inline comments on tables. |
| `COMMENT ON COLUMN schema.table.col IS '...'` | `COMMENT ON COLUMN schema.table.col IS '...'` | Snowflake supports this syntax identically. |

---

## Translation Decisions — Column-Level

### 7. `BYTEINT` Data Type

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `BYTEINT` | `SMALLINT` | Snowflake does not have a `BYTEINT` type. `SMALLINT` is the closest equivalent (stores values -32768 to 32767, covering BYTEINT's -128 to 127 range). All usages in this schema are boolean flags (0/1) or small integers. |

**Affected columns:** `IS_ACTIVE`, `IS_WEEKEND`, `IS_BUSINESS_DAY`, `IS_MONTH_END`, `IS_QUARTER_END`, `IS_YEAR_END`, `IS_JOINT_ACCOUNT`, `TAX_REPORTING_FLAG`, `IS_NORWEGIAN_HOLIDAY`, `DAY_OF_WEEK`, `DAY_OF_MONTH`, `WEEK_OF_YEAR`, `ISO_WEEK`, `MONTH_NUM`, `QUARTER_NUM`, `HALF_YEAR`, `FISCAL_QUARTER`, `IS_INTERNATIONAL`, `IS_FLAGGED`, `IS_REGULATED`.

### 8. `NOT CASESPECIFIC`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `VARCHAR(n) NOT CASESPECIFIC` | `VARCHAR(n) COLLATE 'en-ci'` | Teradata `NOT CASESPECIFIC` makes comparisons case-insensitive. Snowflake is case-sensitive by default. Using `COLLATE 'en-ci'` (English, case-insensitive) preserves the original behavior for WHERE, JOIN, and ORDER BY operations. |

**Affected columns:** `FIRST_NAME`, `LAST_NAME`, `EMAIL_ADDRESS`, `ADDRESS_LINE_1`, `ADDRESS_LINE_2`, `CITY`, `STATE_PROVINCE`, `COUNTRY_CODE`, `CUSTOMER_SEGMENT`, `KYC_STATUS`, `ACCOUNT_TYPE`, `ACCOUNT_SUBTYPE`, `CURRENCY_CODE`, `ACCOUNT_STATUS`, `PRODUCT_NAME`, `PRODUCT_CATEGORY`, `PRODUCT_SUBCATEGORY`, `BRANCH_NAME`, `BRANCH_TYPE`, `REGION`, `COUNTY`, `TRANSACTION_TYPE`, `TRANSACTION_SUBTYPE`, `CHANNEL`, `TRANSACTION_CURRENCY`, `MERCHANT_NAME`, `DESCRIPTION_TEXT`.

### 9. `FORMAT` on Column Definitions

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `DATE FORMAT 'YYYY-MM-DD'` | `DATE` (no format) | Teradata `FORMAT` is a display hint stored in the data dictionary. Snowflake DATE columns have no display format; formatting is controlled by session parameter `DATE_OUTPUT_FORMAT` or `TO_CHAR()` at query time. |

**Affected columns:** All `DATE` columns (`DATE_OF_BIRTH`, `ONBOARDING_DATE`, `OPENING_DATE`, `CLOSING_DATE`, `CALENDAR_DATE`, `TRANSACTION_DATE`, `SNAPSHOT_DATE`, etc.).

### 10. `COMPRESS`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COMPRESS (val1, val2, ...)` | Removed | Teradata COMPRESS stores frequently repeated values in the column header to save space. Snowflake applies automatic columnar compression (Zstandard, LZ4, etc.) to all columns — no manual hints needed. |
| `COMPRESS ''` (empty string) | Removed | Same reasoning. |
| `COMPRESS 0` (single value) | Removed | Same reasoning. |

**Affected files:** All 7 tables (extensively used).

### 11. `GENERATED ALWAYS AS IDENTITY`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` | `BIGINT NOT NULL AUTOINCREMENT START 1 INCREMENT 1` | Snowflake uses `AUTOINCREMENT` or `IDENTITY(start, increment)` syntax. Both produce system-generated surrogate keys. |

**Affected columns:** `CUSTOMER_KEY` (DIM_CUSTOMER), `ACCOUNT_KEY` (DIM_ACCOUNT).

### 12. `TIMESTAMP` and Defaults

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `TIMESTAMP(0)` | `TIMESTAMP_NTZ` | Snowflake's `TIMESTAMP_NTZ` (no time zone) maps to Teradata's `TIMESTAMP`. Precision defaults to 9 in Snowflake; the value is functionally equivalent. |
| `TIMESTAMP(6)` | `TIMESTAMP_NTZ(6)` | Explicit 6-digit fractional seconds preserved. |
| `DEFAULT CURRENT_TIMESTAMP(0)` | `DEFAULT CURRENT_TIMESTAMP()` | Snowflake does not accept precision in `CURRENT_TIMESTAMP()`. |
| `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` | `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ` | Explicit cast to `TIMESTAMP_NTZ`. |
| `TIME(0)` | `TIME(0)` | Directly supported in Snowflake. |

---

## Translation Decisions — Views

### 13. `REPLACE VIEW` → `CREATE OR REPLACE VIEW`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `REPLACE VIEW schema.view AS` | `CREATE OR REPLACE VIEW schema.view AS` | Direct syntax mapping. |

**Affected files:** All 3 views.

### 14. `LOCKING ROW FOR ACCESS`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `LOCKING ROW FOR ACCESS` | Removed | Teradata lock hint for dirty reads. Snowflake uses MVCC (Multi-Version Concurrency Control) — readers never block writers and vice versa. No locking hints needed. |

**Affected files:** All 3 views.

### 15. `SEL` → `SELECT`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `SEL` | `SELECT` | `SEL` is Teradata shorthand. Snowflake requires the full `SELECT` keyword. |

**Affected files:** All 3 views (including nested subqueries).

### 16. `QUALIFY`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `QUALIFY ROW_NUMBER() OVER (...) = 1` | `QUALIFY ROW_NUMBER() OVER (...) = 1` | Snowflake natively supports `QUALIFY`. No change needed. |

**Affected files:** `01_vw_customer_360` (converted to `ORDER BY ... LIMIT 1` inside scalar subquery), `02_vw_regulatory_large_transactions`.

**Special case — scalar subquery:** The correlated subquery in `VW_CUSTOMER_360` used `QUALIFY` to filter to the latest snapshot row. Since `QUALIFY` cannot be used inside a scalar subquery returning a single value, this was rewritten as `ORDER BY snap.SNAPSHOT_DATE DESC LIMIT 1`.

### 17. `ZEROIFNULL` / `NULLIFZERO`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `ZEROIFNULL(expr)` | `ZEROIFNULL(expr)` | Natively supported in Snowflake. No change needed. |
| `NULLIFZERO(expr)` | `NULLIFZERO(expr)` | Natively supported in Snowflake. No change needed. |

**Affected files:** `01_vw_customer_360`, `03_vw_branch_performance`.

### 18. `FORMAT` in SELECT Expressions

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `expr (FORMAT 'ZZZ,ZZZ,ZZ9.99')` | `expr` (formatting removed) | Teradata FORMAT in SELECT is a display hint. Snowflake does not support inline FORMAT. Use `TO_CHAR(expr, '999,999,999.99')` at the presentation layer if needed. Views should return raw numeric values. |
| `TRIM(col (FORMAT '9999'))` | `CAST(col AS VARCHAR)` | Teradata formats a number as a padded string, then TRIM removes leading spaces. In Snowflake, casting to VARCHAR produces the same result. |

**Affected files:** `01_vw_customer_360`, `03_vw_branch_performance`.

### 19. `HASHROW` → `HASH`

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `HASHROW(col1, col2)` | `HASH(col1, col2)` | Teradata `HASHROW` computes a row hash for distribution/comparison. Snowflake `HASH()` provides equivalent deterministic hashing. Note: the hash algorithms differ, so hash values will not match across platforms. |

**Affected files:** `02_vw_regulatory_large_transactions`.

### 20. `(NOT CASESPECIFIC)` in SELECT

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `c.FIRST_NAME (NOT CASESPECIFIC)` | `c.FIRST_NAME` | Inline `NOT CASESPECIFIC` in SELECT overrides the column's default for that expression. Since the underlying column now uses `COLLATE 'en-ci'`, the behavior is preserved. Inline modifier removed. |

**Affected files:** `02_vw_regulatory_large_transactions`.

### 21. `CSUM` (Cumulative Sum)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `CSUM(SUM(col), order_col)` | `SUM(SUM(col)) OVER (PARTITION BY group_col ORDER BY order_col ROWS UNBOUNDED PRECEDING)` | Teradata `CSUM` is an ordered analytical function that computes running totals. Snowflake uses standard SQL window functions. The `PARTITION BY` is set to `BRANCH_ID` to match Teradata's implicit partitioning by GROUP BY columns. |

**Affected files:** `03_vw_branch_performance`.

### 22. `MAVG` (Moving Average)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `MAVG(SUM(col), 3, order_col)` | `AVG(SUM(col)) OVER (PARTITION BY group_col ORDER BY order_col ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` | Teradata `MAVG(expr, n, sort)` computes a moving average over `n` rows. In Snowflake window syntax, a 3-row moving average uses `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` (current row + 2 preceding = 3 rows). |

**Affected files:** `03_vw_branch_performance`.

### 23. Date Arithmetic

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `CURRENT_DATE - date_col` (returns integer days) | `DATEDIFF(DAY, date_col, CURRENT_DATE)` | Teradata date subtraction returns an integer. Snowflake requires `DATEDIFF`. |
| `CURRENT_DATE - 90` | `DATEADD(DAY, -90, CURRENT_DATE)` | Explicit function for date arithmetic. |
| `ADD_MONTHS(date, n)` | `DATEADD(MONTH, n, date)` | Both are valid in Snowflake; `DATEADD` is more idiomatic. |

**Affected files:** `01_vw_customer_360`, `03_vw_branch_performance`.

---

## Schema and Naming

| Aspect | Decision |
|--------|----------|
| **Database/Schema prefix** | All objects retain the `BANKING_DW.` prefix. In Snowflake, this maps to a schema within a database. Create the schema before running DDL: `CREATE SCHEMA IF NOT EXISTS BANKING_DW;` |
| **Object names** | All table and view names are preserved exactly as-is. |
| **Column names** | All column names are preserved exactly as-is. |
| **File naming** | Snowflake DDL files mirror the source file names and directory structure exactly. |

---

## Execution Order

Run the Snowflake DDL scripts in the following order (tables first, then views that depend on them):

```
-- 1. Create schema
CREATE DATABASE IF NOT EXISTS BANKING_DW_DB;
USE DATABASE BANKING_DW_DB;
CREATE SCHEMA IF NOT EXISTS BANKING_DW;
USE SCHEMA BANKING_DW;

-- 2. Dimension tables (no dependencies between them)
snowflake/tables/01_dim_customer.sql
snowflake/tables/03_dim_product.sql
snowflake/tables/04_dim_branch.sql
snowflake/tables/05_dim_date.sql

-- 3. Dimension tables with FK references
snowflake/tables/02_dim_account.sql    -- references DIM_CUSTOMER, DIM_BRANCH, DIM_PRODUCT

-- 4. Fact tables
snowflake/tables/06_fact_transaction.sql         -- references all dimensions
snowflake/tables/07_fact_monthly_snapshot.sql     -- references all dimensions

-- 5. Views (depend on tables above)
snowflake/views/01_vw_customer_360.sql           -- joins DIM_CUSTOMER, DIM_ACCOUNT, FACT_MONTHLY_ACCOUNT_SNAPSHOT, FACT_TRANSACTION
snowflake/views/02_vw_regulatory_large_transactions.sql  -- joins FACT_TRANSACTION, DIM_ACCOUNT, DIM_CUSTOMER, DIM_BRANCH
snowflake/views/03_vw_branch_performance.sql     -- joins FACT_MONTHLY_ACCOUNT_SNAPSHOT, DIM_BRANCH, DIM_DATE
```

---

## Post-Migration Validation Checklist

| # | Check | Command |
|---|-------|---------|
| 1 | All tables created successfully | `SHOW TABLES IN SCHEMA BANKING_DW;` |
| 2 | All views created successfully | `SHOW VIEWS IN SCHEMA BANKING_DW;` |
| 3 | Column counts match source | Compare `DESCRIBE TABLE` output between Teradata and Snowflake |
| 4 | Data types are correct | `SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'BANKING_DW';` |
| 5 | Row counts match after data load | Compare `SELECT COUNT(*) FROM table` on both platforms |
| 6 | Clustering keys are set | `SHOW TABLES LIKE '%FACT%' IN SCHEMA BANKING_DW;` — check `cluster_by` column |
| 7 | Comments are applied | `SELECT TABLE_NAME, COMMENT FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'BANKING_DW';` |
| 8 | Case-insensitive columns work | `SELECT * FROM DIM_CUSTOMER WHERE FIRST_NAME = 'john';` should match `'John'` |
| 9 | AUTOINCREMENT columns generate IDs | `INSERT INTO DIM_CUSTOMER (...) VALUES (...); SELECT CUSTOMER_KEY FROM DIM_CUSTOMER;` |
| 10 | Views return data correctly | `SELECT * FROM VW_CUSTOMER_360 LIMIT 10;` |
| 11 | Window functions in views work | `SELECT * FROM VW_BRANCH_PERFORMANCE LIMIT 10;` |
| 12 | Hash values are deterministic | `SELECT HASH(1, CURRENT_DATE) = HASH(1, CURRENT_DATE);` should return TRUE |

---

## Appendix: Feature Support Matrix

| Teradata Feature | Snowflake Status | Notes |
|-----------------|-----------------|-------|
| `SET` table (duplicate rejection) | Not supported | Enforce at ETL layer |
| `MULTISET` table | Default behavior | All Snowflake tables are multiset |
| Primary Index (PI) | Not applicable | Use CLUSTER BY for pruning |
| Partitioned PI (PPI) | Not applicable | Automatic micro-partitioning + CLUSTER BY |
| `COMPRESS` | Automatic | Snowflake compresses all data |
| `NOT CASESPECIFIC` | `COLLATE 'en-ci'` | Per-column collation |
| `FORMAT` (column) | Not supported | Session-level or `TO_CHAR` |
| `FORMAT` (expression) | Not supported | Use `TO_CHAR` |
| `QUALIFY` | Natively supported | Identical syntax |
| `CSUM` | Window function | `SUM() OVER (... ROWS UNBOUNDED PRECEDING)` |
| `MAVG` | Window function | `AVG() OVER (... ROWS BETWEEN n PRECEDING AND CURRENT ROW)` |
| `HASHROW` | `HASH()` | Different algorithm, values won't match |
| `ZEROIFNULL` | Natively supported | Identical syntax |
| `NULLIFZERO` | Natively supported | Identical syntax |
| `SEL` shorthand | Not supported | Use `SELECT` |
| `LOCKING ROW FOR ACCESS` | Not applicable | MVCC handles concurrency |
| `COLLECT STATISTICS` | Automatic | No manual stats collection |
| `BYTEINT` | Not supported | Use `SMALLINT` |
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Syntax difference only |
| `NO FALLBACK` / Journaling | Not applicable | Built-in redundancy + Time Travel |
