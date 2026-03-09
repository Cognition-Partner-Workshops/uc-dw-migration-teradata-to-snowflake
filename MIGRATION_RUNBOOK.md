# Teradata to Snowflake DDL Migration Runbook

This document records every translation decision made while converting the `BANKING_DW` data warehouse DDL from Teradata SQL to Snowflake SQL.

> **Scope**: 7 tables (`ddl/tables/`) and 3 views (`ddl/views/`) converted into `snowflake/ddl/tables/` and `snowflake/ddl/views/`.

---

## 1. Inventory of Converted Objects

| # | Object Type | Source File | Target File | Key Teradata Features |
|---|-------------|-------------|-------------|----------------------|
| 1 | Table | `ddl/tables/01_dim_customer.sql` | `snowflake/ddl/tables/01_dim_customer.sql` | SET, UPI, PPI, IDENTITY, COMPRESS, NOT CASESPECIFIC, FORMAT, BYTEINT |
| 2 | Table | `ddl/tables/02_dim_account.sql` | `snowflake/ddl/tables/02_dim_account.sql` | MULTISET, UPI, PPI, IDENTITY, COMPRESS, NOT CASESPECIFIC, FORMAT, BYTEINT |
| 3 | Table | `ddl/tables/03_dim_product.sql` | `snowflake/ddl/tables/03_dim_product.sql` | SET, UPI, COMPRESS, NOT CASESPECIFIC, FORMAT, BYTEINT |
| 4 | Table | `ddl/tables/04_dim_branch.sql` | `snowflake/ddl/tables/04_dim_branch.sql` | SET, UPI, COMPRESS, NOT CASESPECIFIC, FORMAT, BYTEINT |
| 5 | Table | `ddl/tables/05_dim_date.sql` | `snowflake/ddl/tables/05_dim_date.sql` | SET, UPI, COMPRESS, FORMAT, BYTEINT |
| 6 | Table | `ddl/tables/06_fact_transaction.sql` | `snowflake/ddl/tables/06_fact_transaction.sql` | MULTISET, PI, PPI (monthly), COMPRESS, NOT CASESPECIFIC, FORMAT, BYTEINT |
| 7 | Table | `ddl/tables/07_fact_monthly_snapshot.sql` | `snowflake/ddl/tables/07_fact_monthly_snapshot.sql` | MULTISET, PI, PPI (monthly), COMPRESS, FORMAT |
| 8 | View | `ddl/views/01_vw_customer_360.sql` | `snowflake/ddl/views/01_vw_customer_360.sql` | SEL, LOCKING ROW, QUALIFY, ZEROIFNULL, FORMAT, scalar subquery |
| 9 | View | `ddl/views/02_vw_regulatory_large_transactions.sql` | `snowflake/ddl/views/02_vw_regulatory_large_transactions.sql` | SEL, LOCKING ROW, QUALIFY, HASHROW, NOT CASESPECIFIC expr |
| 10 | View | `ddl/views/03_vw_branch_performance.sql` | `snowflake/ddl/views/03_vw_branch_performance.sql` | SEL, LOCKING ROW, CSUM, MAVG, NULLIFZERO, FORMAT, TRIM FORMAT |

---

## 2. Translation Decisions — Table DDL

### 2.1 SET / MULTISET Tables

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `CREATE SET TABLE` | `CREATE OR REPLACE TABLE` | Teradata SET tables reject duplicate rows at insert time. Snowflake has no SET table concept — all tables allow duplicates (MULTISET semantics). Duplicate prevention must be handled at the ETL/application layer. |
| `CREATE MULTISET TABLE` | `CREATE OR REPLACE TABLE` | Direct mapping — Snowflake default behaviour matches MULTISET. |

**Affected files**: All 7 table DDLs.

### 2.2 Table Options (NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `NO FALLBACK` | Removed | Teradata-specific data protection feature. Snowflake provides built-in replication and Time Travel. |
| `NO BEFORE JOURNAL`, `NO AFTER JOURNAL` | Removed | Teradata journaling for crash recovery. Snowflake uses its own transactional model. |
| `CHECKSUM = DEFAULT` | Removed | Teradata disk-level checksum option. Not applicable to Snowflake. |
| `DEFAULT MERGEBLOCKRATIO` | Removed | Teradata block-merge tuning. Not applicable to Snowflake. |

**Affected files**: All 7 table DDLs.

### 2.3 Primary Index (PI) and Unique Primary Index (UPI)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `UNIQUE PRIMARY INDEX (col)` | `CONSTRAINT PK_... PRIMARY KEY (col)` | UPI enforces uniqueness and determines data distribution in Teradata. Mapped to a Snowflake PRIMARY KEY constraint. Note: Snowflake PKs are informational (not enforced), but they document intent and are used by BI tools. |
| `PRIMARY INDEX (col1, col2)` | Comment noting original PI | Non-unique PI controls data distribution only. No direct Snowflake equivalent. Documented in comments; distribution columns folded into CLUSTER BY where beneficial. |
| `INDEX name (col)` (secondary) | Comment noting original index | Snowflake does not support secondary indexes. Documented in comments with a suggestion to consider Search Optimization Service for frequently filtered columns. |

**Affected files**: All 7 table DDLs.

### 2.4 Partitioned Primary Index (PPI)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `PARTITION BY RANGE_N(col BETWEEN ... AND ... EACH INTERVAL '1' YEAR)` | `CLUSTER BY (col)` | Teradata PPI physically partitions data into ranges for partition elimination. Snowflake's micro-partitioning with CLUSTER BY achieves analogous query pruning. |
| `PARTITION BY RANGE_N(col ... EACH INTERVAL '1' MONTH, NO RANGE)` | `CLUSTER BY (date_col, key_col)` | For fact tables with monthly PPI, we cluster on the date column plus the original PI key to optimize both date-range and key-based queries. |

**Affected files**: `01_dim_customer`, `02_dim_account`, `06_fact_transaction`, `07_fact_monthly_snapshot`.

### 2.5 GENERATED ALWAYS AS IDENTITY

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` | `BIGINT NOT NULL AUTOINCREMENT START 1 INCREMENT 1` | Snowflake uses `AUTOINCREMENT` (or `IDENTITY`) keyword. Functionally equivalent auto-incrementing surrogate key. |

**Affected files**: `01_dim_customer`, `02_dim_account`.

### 2.6 COMPRESS

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COMPRESS ('val1', 'val2', ...)` | Removed | Teradata value-level compression stores frequently repeated values in the column header to save space. Snowflake applies automatic columnar compression (Zstandard, LZO, etc.) transparently. No manual COMPRESS needed. |
| `COMPRESS 0` / `COMPRESS ''` | Removed | Single-value compress for NULLs or common defaults — handled automatically by Snowflake. |

**Affected files**: All 7 table DDLs (every table had COMPRESS on at least one column).

### 2.7 NOT CASESPECIFIC

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `VARCHAR(n) NOT CASESPECIFIC` | `VARCHAR(n)` | Teradata's NOT CASESPECIFIC makes string comparisons case-insensitive for that column. Snowflake string comparisons are case-sensitive by default. We removed the clause because: (a) there is no column-level collation modifier in Snowflake DDL, and (b) the warehouse should explicitly handle case-insensitivity in queries (e.g., `UPPER()` or `ILIKE`). If case-insensitive behaviour is required globally, the database or schema collation can be set to `'en-ci'`. |
| `col (NOT CASESPECIFIC)` in views | Removed | Expression-level NOT CASESPECIFIC syntax in SELECT lists — not supported in Snowflake. |

**Affected files**: All table DDLs and `02_vw_regulatory_large_transactions`.

> **Action Item**: If case-insensitive comparisons are required, consider setting `ALTER DATABASE BANKING_DW SET DEFAULT_DDL_COLLATION = 'en-ci';` before creating tables.

### 2.8 FORMAT Clause

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `DATE FORMAT 'YYYY-MM-DD'` | `DATE` | Teradata FORMAT controls display formatting at the column level. Snowflake dates have no intrinsic display format — formatting is done at query time with `TO_CHAR()`. The default Snowflake date output is `YYYY-MM-DD` anyway. |
| `expr (FORMAT 'ZZZ,ZZZ,ZZ9.99')` in views | Removed | Inline display formatting in SELECT list. Use `TO_CHAR(expr, '999,999,999.99')` at presentation layer if needed. |
| `TRIM(col (FORMAT '9999'))` in views | `TO_CHAR(col, '9999')` | Teradata pattern of formatting a number and trimming it. Converted to Snowflake's `TO_CHAR()`. |

**Affected files**: All table DDLs, `01_vw_customer_360`, `03_vw_branch_performance`.

### 2.9 BYTEINT Data Type

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `BYTEINT` | `SMALLINT` | Teradata BYTEINT is a 1-byte integer (-128 to 127). Snowflake does not have BYTEINT. `SMALLINT` (synonym for `NUMBER(38,0)` in Snowflake, but semantically a small integer) is the closest standard SQL type. All BYTEINT columns in the source hold values 0/1 (flags) or small numbers (day of week, quarter, etc.). |

**Affected files**: `01_dim_customer`, `02_dim_account`, `03_dim_product`, `04_dim_branch`, `05_dim_date`, `06_fact_transaction`.

### 2.10 TIMESTAMP Defaults

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `TIMESTAMP(0) DEFAULT CURRENT_TIMESTAMP(0)` | `TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)` | Teradata TIMESTAMP is timezone-naive by default. Mapped to Snowflake `TIMESTAMP_NTZ` (No Time Zone) for consistency. The cast ensures the default matches the declared precision. |
| `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` | `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ(0)` | Snowflake string literal cast to TIMESTAMP_NTZ for the SCD Type 2 end-date sentinel. |

**Affected files**: All table DDLs with ETL timestamp or SCD columns.

### 2.11 COLLECT STATISTICS

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COLLECT STATISTICS COLUMN (col) ON table;` | Removed entirely | Teradata requires manual statistics collection for the optimizer. Snowflake automatically maintains metadata and micro-partition statistics. No manual action needed. |

**Affected files**: All 7 table DDLs.

### 2.12 COMMENT ON

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `COMMENT ON TABLE schema.table IS '...'` | `COMMENT = '...'` on the CREATE TABLE | Snowflake supports inline COMMENT on CREATE TABLE/VIEW. |
| `COMMENT ON COLUMN schema.table.col IS '...'` | `ALTER TABLE ... ALTER COLUMN ... COMMENT '...'` | Column-level comments require ALTER TABLE in Snowflake. Placed after the CREATE TABLE statement. |
| `COMMENT ON VIEW schema.view IS '...'` | `COMMENT = '...'` on the CREATE VIEW | Inline comment on view creation. |

**Affected files**: All DDL files.

---

## 3. Translation Decisions — View DDL

### 3.1 REPLACE VIEW / LOCKING / SEL

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Standard Snowflake syntax. |
| `LOCKING ROW FOR ACCESS` | Removed | Teradata dirty-read locking hint. Snowflake uses MVCC — reads never block writes and vice versa. No equivalent needed. |
| `SEL` | `SELECT` | Teradata abbreviation. Snowflake requires the full `SELECT` keyword. |

**Affected files**: All 3 view DDLs.

### 3.2 QUALIFY Clause

| Teradata | Snowflake | Decision |
|----------|-----------|----------|
| `QUALIFY ROW_NUMBER() OVER (...) = 1` | Kept as-is | Snowflake natively supports `QUALIFY`. No change needed. |

**Affected files**: `01_vw_customer_360`, `02_vw_regulatory_large_transactions`.

### 3.3 ZEROIFNULL / NULLIFZERO

| Teradata | Snowflake | Decision |
|----------|-----------|----------|
| `ZEROIFNULL(expr)` | Kept as-is | Snowflake natively supports `ZEROIFNULL`. |
| `NULLIFZERO(expr)` | Kept as-is | Snowflake natively supports `NULLIFZERO`. |

**Affected files**: `01_vw_customer_360`, `03_vw_branch_performance`.

### 3.4 HASHROW

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `HASHROW(col1, col2)` | `HASH(col1, col2)` | Teradata's `HASHROW` produces a row-level hash. Snowflake's `HASH()` is the equivalent function. Note: The hash algorithms differ so hash values will NOT match between platforms. Validation queries should compare Snowflake-side hashes against each other, not cross-platform. |

**Affected files**: `02_vw_regulatory_large_transactions`.

### 3.5 CSUM (Cumulative Sum)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `CSUM(expr, order_col)` | `SUM(expr) OVER (PARTITION BY partition_col ORDER BY order_col ROWS UNBOUNDED PRECEDING)` | Teradata's CSUM is a proprietary ordered-analytical function. Converted to the standard SQL window function `SUM() OVER (... ROWS UNBOUNDED PRECEDING)`. Added `PARTITION BY b.BRANCH_ID` to ensure cumulative totals reset per branch (matching the original GROUP BY intent). |

**Affected files**: `03_vw_branch_performance`.

### 3.6 MAVG (Moving Average)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `MAVG(expr, 3, order_col)` | `AVG(expr) OVER (PARTITION BY partition_col ORDER BY order_col ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` | Teradata's MAVG computes a moving average over _n_ rows. `MAVG(expr, 3, ...)` uses the current row plus 2 preceding = 3-row window. Converted to standard SQL `AVG() OVER (ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)`. Added `PARTITION BY b.BRANCH_ID` to reset per branch. |

**Affected files**: `03_vw_branch_performance`.

### 3.7 Date Arithmetic

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| `(CURRENT_DATE - col) / 365.25` | `DATEDIFF('day', col, CURRENT_DATE()) / 365.25` | Teradata date subtraction yields an integer (days). Snowflake requires explicit `DATEDIFF`. |
| `CURRENT_DATE - 90` | `DATEADD('day', -90, CURRENT_DATE())` | Teradata allows direct integer subtraction from dates. Snowflake uses `DATEADD`. |
| `ADD_MONTHS(CURRENT_DATE, -24)` | `ADD_MONTHS(CURRENT_DATE(), -24)` | Both platforms support `ADD_MONTHS`. Added parentheses to `CURRENT_DATE()` for Snowflake. |

**Affected files**: `01_vw_customer_360`, `03_vw_branch_performance`.

### 3.8 Scalar Subquery Rewrite (VW_CUSTOMER_360)

| Teradata | Snowflake | Rationale |
|----------|-----------|-----------|
| Correlated scalar subquery inside `SUM(CASE WHEN ... THEN (SEL ... QUALIFY ...) END)` | Rewritten as LEFT JOIN to a derived table with `QUALIFY ROW_NUMBER()` | The original Teradata view used a correlated scalar subquery inside a CASE expression to fetch the latest snapshot balance per account. This pattern is inefficient and not well-supported in Snowflake. Rewritten as a pre-filtered derived table (`latest_snap`) joined to the accounts, which is more readable and performant. |

**Affected files**: `01_vw_customer_360`.

---

## 4. Features with No Direct Equivalent — Recommendations

| Feature | Recommendation |
|---------|---------------|
| **Secondary Indexes** | Use Snowflake Search Optimization Service for point-lookup columns (e.g., `CUSTOMER_ID`, `ACCOUNT_ID`). Enable with `ALTER TABLE ... ADD SEARCH OPTIMIZATION ON EQUALITY(col)`. |
| **SET Table Duplicate Rejection** | Add `INSERT ... SELECT DISTINCT` or `MERGE` logic in ETL pipelines to prevent duplicates. Alternatively, use Snowflake streams + tasks for deduplication. |
| **COLLECT STATISTICS** | No action. Snowflake automatically collects and maintains statistics. Monitor query performance and adjust clustering keys if needed. |
| **NOT CASESPECIFIC** | If case-insensitive comparisons are required globally, set `DEFAULT_DDL_COLLATION = 'en-ci'` at the database or schema level before table creation. Otherwise, use `ILIKE` or `UPPER()`/`LOWER()` in query predicates. |
| **FORMAT (display)** | Apply formatting at the reporting/BI layer using `TO_CHAR()` or tool-specific formatting options. |

---

## 5. Execution Order

Tables should be created in numeric order to respect implicit dependencies:

```
1.  01_dim_customer.sql
2.  02_dim_account.sql
3.  03_dim_product.sql
4.  04_dim_branch.sql
5.  05_dim_date.sql
6.  06_fact_transaction.sql
7.  07_fact_monthly_snapshot.sql
8.  01_vw_customer_360.sql       (depends on DIM_CUSTOMER, DIM_ACCOUNT, FACT_MONTHLY_ACCOUNT_SNAPSHOT, FACT_TRANSACTION)
9.  02_vw_regulatory_large_transactions.sql  (depends on FACT_TRANSACTION, DIM_ACCOUNT, DIM_CUSTOMER, DIM_BRANCH)
10. 03_vw_branch_performance.sql (depends on FACT_MONTHLY_ACCOUNT_SNAPSHOT, DIM_BRANCH, DIM_DATE)
```

### Pre-requisites

Before executing the DDL scripts:

1. Create the target database and schema:
   ```sql
   CREATE DATABASE IF NOT EXISTS BANKING_DW;
   CREATE SCHEMA IF NOT EXISTS BANKING_DW.BANKING_DW;
   -- Or use: USE DATABASE BANKING_DW; USE SCHEMA PUBLIC;
   ```
2. (Optional) Set case-insensitive collation if needed:
   ```sql
   ALTER DATABASE BANKING_DW SET DEFAULT_DDL_COLLATION = 'en-ci';
   ```

---

## 6. Validation Checklist

After deploying the Snowflake DDL:

- [ ] All 7 tables created successfully (`SHOW TABLES IN SCHEMA BANKING_DW`)
- [ ] All 3 views created successfully (`SHOW VIEWS IN SCHEMA BANKING_DW`)
- [ ] Primary key constraints exist on dimension tables (`SHOW PRIMARY KEYS IN SCHEMA BANKING_DW`)
- [ ] AUTOINCREMENT columns generate sequential IDs on insert
- [ ] Clustering keys are set on partitioned tables (`SHOW TABLES` — check `cluster_by` column)
- [ ] Table and column comments are populated (`SELECT * FROM INFORMATION_SCHEMA.TABLES`)
- [ ] Seed data loads successfully from `data/seed/` CSV files
- [ ] Row counts match `data/validation/expected_row_counts.csv` after data load
- [ ] Views compile and return results without errors
- [ ] Cross-platform validation queries from `data/validation/checksum_queries.sql` adapted for Snowflake (replace `HASHROW` with `HASH`)

---

## 7. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| SET table semantics lost — duplicate rows could be inserted | Medium | Add MERGE/dedup logic in ETL; add unique constraints where business rules require it |
| NOT CASESPECIFIC removal changes comparison behaviour | High | Audit all WHERE clauses and JOIN conditions for case sensitivity; set database collation to `en-ci` if needed |
| HASH values differ between HASHROW (Teradata) and HASH (Snowflake) | Low | Use Snowflake HASH values only for intra-Snowflake validation, not cross-platform comparison |
| AUTOINCREMENT may produce gaps under concurrent loads | Low | Surrogate keys do not need to be contiguous; this is expected Snowflake behaviour |
| Primary key constraints are not enforced in Snowflake | Medium | Rely on ETL logic for uniqueness; PK constraints serve as documentation and BI tool hints |
| Clustering key choices may need tuning | Low | Monitor query profiles after data load; adjust CLUSTER BY columns based on actual query patterns |
