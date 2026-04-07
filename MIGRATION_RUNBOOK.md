# Teradata to Snowflake Migration Runbook

This document records every translation decision made during the conversion of the BANKING_DW data warehouse from Teradata to Snowflake.

---

## Table of Contents

1. [Migration Scope](#1-migration-scope)
2. [Converted File Inventory](#2-converted-file-inventory)
3. [DDL Translation Decisions](#3-ddl-translation-decisions)
4. [DML Translation Decisions](#4-dml-translation-decisions)
5. [Stored Procedure Translation Decisions](#5-stored-procedure-translation-decisions)
6. [Macro to Stored Procedure Conversion](#6-macro-to-stored-procedure-conversion)
7. [BTEQ Script Conversion](#7-bteq-script-conversion)
8. [Data Type Mappings](#8-data-type-mappings)
9. [Validation and Testing](#9-validation-and-testing)
10. [Deployment Execution Order](#10-deployment-execution-order)
11. [Post-Migration Checklist](#11-post-migration-checklist)
12. [Known Differences and Caveats](#12-known-differences-and-caveats)

---

## 1. Migration Scope

### Source System
- **Platform:** Teradata
- **Database:** BANKING_DW
- **Domain:** Retail Banking Analytics (Norwegian market)

### Target System
- **Platform:** Snowflake
- **Database:** BANKING_DW

### Objects Converted

| Object Type | Count | Source Directory | Target Directory |
|---|---|---|---|
| Tables (DDL) | 7 | `ddl/tables/` | `snowflake/ddl/tables/` |
| Views (DDL) | 3 | `ddl/views/` | `snowflake/ddl/views/` |
| Stored Procedures | 3 | `dml/stored_procedures/` | `snowflake/dml/stored_procedures/` |
| Macros -> Procedures | 3 | `dml/macros/` | `snowflake/dml/macros/` |
| BTEQ Scripts -> SnowSQL/Procedures | 2 | `dml/scripts/` | `snowflake/dml/scripts/` |
| Validation Queries | 1 | `data/validation/` | `snowflake/data/validation/` |

---

## 2. Converted File Inventory

### Tables
| # | Source File | Target File | Table Name |
|---|---|---|---|
| 1 | `ddl/tables/01_dim_customer.sql` | `snowflake/ddl/tables/01_dim_customer.sql` | DIM_CUSTOMER |
| 2 | `ddl/tables/02_dim_account.sql` | `snowflake/ddl/tables/02_dim_account.sql` | DIM_ACCOUNT |
| 3 | `ddl/tables/03_dim_product.sql` | `snowflake/ddl/tables/03_dim_product.sql` | DIM_PRODUCT |
| 4 | `ddl/tables/04_dim_branch.sql` | `snowflake/ddl/tables/04_dim_branch.sql` | DIM_BRANCH |
| 5 | `ddl/tables/05_dim_date.sql` | `snowflake/ddl/tables/05_dim_date.sql` | DIM_DATE |
| 6 | `ddl/tables/06_fact_transaction.sql` | `snowflake/ddl/tables/06_fact_transaction.sql` | FACT_TRANSACTION |
| 7 | `ddl/tables/07_fact_monthly_snapshot.sql` | `snowflake/ddl/tables/07_fact_monthly_snapshot.sql` | FACT_MONTHLY_ACCOUNT_SNAPSHOT |

### Views
| # | Source File | Target File | View Name |
|---|---|---|---|
| 1 | `ddl/views/01_vw_customer_360.sql` | `snowflake/ddl/views/01_vw_customer_360.sql` | VW_CUSTOMER_360 |
| 2 | `ddl/views/02_vw_regulatory_large_transactions.sql` | `snowflake/ddl/views/02_vw_regulatory_large_transactions.sql` | VW_REGULATORY_LARGE_TRANSACTIONS |
| 3 | `ddl/views/03_vw_branch_performance.sql` | `snowflake/ddl/views/03_vw_branch_performance.sql` | VW_BRANCH_PERFORMANCE |

### Stored Procedures
| # | Source File | Target File | Procedure Name |
|---|---|---|---|
| 1 | `dml/stored_procedures/sp_load_daily_transactions.sql` | `snowflake/dml/stored_procedures/sp_load_daily_transactions.sql` | SP_LOAD_DAILY_TRANSACTIONS |
| 2 | `dml/stored_procedures/sp_monthly_snapshot.sql` | `snowflake/dml/stored_procedures/sp_monthly_snapshot.sql` | SP_MONTHLY_SNAPSHOT |
| 3 | `dml/stored_procedures/sp_customer_scd2.sql` | `snowflake/dml/stored_procedures/sp_customer_scd2.sql` | SP_CUSTOMER_SCD2 |

### Macros (Converted to Stored Procedures)
| # | Source File | Target File | Original Macro -> New Procedure |
|---|---|---|---|
| 1 | `dml/macros/macro_daily_balance_check.sql` | `snowflake/dml/macros/macro_daily_balance_check.sql` | DAILY_BALANCE_CHECK (macro) -> DAILY_BALANCE_CHECK (procedure) |
| 2 | `dml/macros/macro_aml_screening.sql` | `snowflake/dml/macros/macro_aml_screening.sql` | AML_SCREENING (macro) -> AML_SCREENING (procedure) |
| 3 | `dml/macros/macro_customer_txn_history.sql` | `snowflake/dml/macros/macro_customer_txn_history.sql` | CUSTOMER_TXN_HISTORY (macro) -> CUSTOMER_TXN_HISTORY (procedure) |

### Scripts
| # | Source File | Target File |
|---|---|---|
| 1 | `dml/scripts/bteq_daily_load.btq` | `snowflake/dml/scripts/snowsql_daily_load.sql` |
| 2 | `dml/scripts/bteq_extract_report.btq` | `snowflake/dml/scripts/snowsql_extract_report.sql` |

---

## 3. DDL Translation Decisions

### 3.1 SET / MULTISET Tables

| Decision | Details |
|---|---|
| **Teradata** | `CREATE SET TABLE` (rejects duplicate rows), `CREATE MULTISET TABLE` (allows duplicates) |
| **Snowflake** | All tables are `CREATE TABLE` (equivalent to MULTISET; duplicates allowed) |
| **Action** | Removed SET/MULTISET keywords. For tables that were SET (dimensions), uniqueness is enforced via PRIMARY KEY constraints. Snowflake PKs are declarative (not enforced), so application-level dedup logic should be maintained. |
| **Affected** | All 7 tables |

### 3.2 NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO

| Decision | Details |
|---|---|
| **Teradata** | `NO FALLBACK`, `NO BEFORE JOURNAL`, `NO AFTER JOURNAL`, `CHECKSUM = DEFAULT`, `DEFAULT MERGEBLOCKRATIO` |
| **Snowflake** | No equivalent concepts. Snowflake handles data protection via Time Travel, Fail-safe, and automatic replication. |
| **Action** | Removed all five clauses entirely. |
| **Affected** | All 7 tables |

### 3.3 Primary Index (PI) and Unique Primary Index (UPI)

| Decision | Details |
|---|---|
| **Teradata** | `UNIQUE PRIMARY INDEX (col)` controls data distribution and enforces uniqueness. `PRIMARY INDEX (col1, col2)` controls distribution only. |
| **Snowflake** | No Primary Index concept. Data distribution is handled by Snowflake's micro-partitioning engine automatically. |
| **Action** | UPI columns -> `PRIMARY KEY` constraint (declarative, not enforced). Non-unique PI -> documented as comments. All PI distribution logic removed. |
| **Affected** | All 7 tables. Dimension tables had UPI; fact tables had non-unique PI. |

### 3.4 Non-Unique Secondary Indexes (NUSI / NUPI)

| Decision | Details |
|---|---|
| **Teradata** | `INDEX idx_name (col)` creates secondary indexes for query performance. |
| **Snowflake** | No user-managed indexes. Snowflake uses automatic micro-partition pruning and query optimization. |
| **Action** | Removed all secondary indexes. Documented original indexes as SQL comments for reference. Consider using `CLUSTER BY` or Search Optimization Service for critical query patterns. |
| **Affected** | All 7 tables (total of 14 secondary indexes removed) |

### 3.5 Partitioned Primary Index (PPI) / PARTITION BY RANGE_N

| Decision | Details |
|---|---|
| **Teradata** | `PARTITION BY RANGE_N(date_col BETWEEN ... AND ... EACH INTERVAL '1' MONTH)` creates range partitions for partition elimination. |
| **Snowflake** | Snowflake micro-partitions are automatic. `CLUSTER BY (col)` is the closest equivalent for controlling data organization. |
| **Action** | Replaced `PARTITION BY RANGE_N` with `CLUSTER BY (date_col)` on the same column. For fact tables, clustering includes both the date column and the primary access key. |
| **Mapping** | `RANGE_N(TRANSACTION_DATE ... EACH 1 MONTH)` -> `CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)` |
| **Affected** | DIM_CUSTOMER, DIM_ACCOUNT (yearly), FACT_TRANSACTION, FACT_MONTHLY_ACCOUNT_SNAPSHOT (monthly) |

### 3.6 COMPRESS

| Decision | Details |
|---|---|
| **Teradata** | `COMPRESS (val1, val2, ...)` and `COMPRESS val` store frequently occurring values in the column header to save space. |
| **Snowflake** | Snowflake automatically applies columnar compression (Zstandard, LZO, etc.) at the micro-partition level. No manual COMPRESS needed. |
| **Action** | Removed all COMPRESS clauses. No functional impact; Snowflake's automatic compression is typically more effective than Teradata's value-level compression. |
| **Affected** | 35+ column definitions across all 7 tables |

### 3.7 NOT CASESPECIFIC

| Decision | Details |
|---|---|
| **Teradata** | `NOT CASESPECIFIC` makes string comparisons case-insensitive for that column. |
| **Snowflake** | Snowflake strings are case-sensitive by default. |
| **Action** | Applied `COLLATE 'en-ci'` (English, case-insensitive) to all columns that had `NOT CASESPECIFIC`. This preserves the original case-insensitive comparison behavior at the storage level. Alternatively, `UPPER()`/`LOWER()` could be applied in queries, but COLLATE is cleaner and more maintainable. |
| **Affected** | ~30 VARCHAR/CHAR columns across all tables (names, types, statuses, descriptions, addresses) |

### 3.8 FORMAT on Column Definitions

| Decision | Details |
|---|---|
| **Teradata** | `DATE FORMAT 'YYYY-MM-DD'`, `DECIMAL FORMAT 'ZZZ,ZZ9.99'` controls display formatting at the column level. |
| **Snowflake** | No column-level FORMAT. Formatting is a presentation concern handled by `TO_CHAR()` in queries/views or the reporting layer. |
| **Action** | Removed all column-level FORMAT clauses. Dates are stored as native DATE type (no format needed). Decimal formatting should be applied via `TO_CHAR()` in views or reports where display formatting is required. |
| **Affected** | All DATE columns (~15), several DECIMAL/INTEGER columns in views and macros |

### 3.9 GENERATED ALWAYS AS IDENTITY

| Decision | Details |
|---|---|
| **Teradata** | `GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` |
| **Snowflake** | `AUTOINCREMENT START 1 INCREMENT 1` (or `IDENTITY(1,1)`) |
| **Action** | Replaced with Snowflake `AUTOINCREMENT` syntax. Functionally equivalent. |
| **Affected** | DIM_CUSTOMER.CUSTOMER_KEY, DIM_ACCOUNT.ACCOUNT_KEY |

### 3.10 BYTEINT Data Type

| Decision | Details |
|---|---|
| **Teradata** | `BYTEINT` is a 1-byte signed integer (-128 to 127). |
| **Snowflake** | No BYTEINT type. Smallest integer type is `SMALLINT` (but Snowflake stores all NUMBER types with the same internal representation). |
| **Action** | Replaced all `BYTEINT` with `SMALLINT`. No storage or performance impact in Snowflake since all integer types share the same underlying storage. |
| **Affected** | ~20 columns (IS_ACTIVE, IS_WEEKEND, DAY_OF_WEEK, QUARTER_NUM, flags, etc.) |

### 3.11 TIMESTAMP(0) and TIMESTAMP(6)

| Decision | Details |
|---|---|
| **Teradata** | `TIMESTAMP(0)` (no fractional seconds), `TIMESTAMP(6)` (microsecond precision) |
| **Snowflake** | `TIMESTAMP_NTZ(0)` and `TIMESTAMP_NTZ(6)` (NTZ = No Time Zone, closest to Teradata default) |
| **Action** | Mapped to `TIMESTAMP_NTZ` with matching precision. Used NTZ variant since Teradata timestamps are timezone-unaware by default. |
| **Affected** | ETL_INSERT_TS, ETL_UPDATE_TS, EFFECTIVE_FROM, EFFECTIVE_TO, TRANSACTION_TS |

### 3.12 COLLECT STATISTICS

| Decision | Details |
|---|---|
| **Teradata** | `COLLECT STATISTICS COLUMN (col) ON table` gathers column-level statistics for the optimizer. |
| **Snowflake** | Statistics are gathered and maintained automatically. No manual intervention needed. |
| **Action** | Removed all COLLECT STATISTICS statements. |
| **Affected** | All 7 tables (total of ~25 COLLECT STATISTICS statements removed) |

### 3.13 COMMENT ON TABLE / COLUMN

| Decision | Details |
|---|---|
| **Teradata** | `COMMENT ON TABLE/COLUMN ...` |
| **Snowflake** | Same syntax supported. Table-level comments can also be specified inline with `COMMENT = '...'` in CREATE TABLE. |
| **Action** | Preserved all comments. Used inline `COMMENT = '...'` for table-level comments and separate `COMMENT ON COLUMN` statements for column-level comments. |
| **Affected** | All tables and views |

---

## 4. DML Translation Decisions

### 4.1 SEL (Shorthand for SELECT)

| Decision | Details |
|---|---|
| **Teradata** | `SEL` is an accepted shorthand for `SELECT`. |
| **Snowflake** | Not supported. Must use full `SELECT` keyword. |
| **Action** | Replaced all `SEL` with `SELECT` globally. |
| **Affected** | All views, stored procedures, macros, scripts, validation queries |

### 4.2 QUALIFY Clause

| Decision | Details |
|---|---|
| **Teradata** | `QUALIFY ROW_NUMBER() OVER (...) = 1` filters on window function results. |
| **Snowflake** | `QUALIFY` is natively supported with identical syntax. |
| **Action** | No changes needed. Snowflake supports QUALIFY natively. |
| **Affected** | VW_CUSTOMER_360, VW_REGULATORY_LARGE_TRANSACTIONS, SP_CUSTOMER_SCD2, macros |

### 4.3 LOCKING ROW FOR ACCESS

| Decision | Details |
|---|---|
| **Teradata** | `LOCKING ROW FOR ACCESS` provides dirty-read isolation for views/queries. |
| **Snowflake** | Not applicable. Snowflake uses MVCC (Multi-Version Concurrency Control) and always provides consistent reads without explicit lock hints. |
| **Action** | Removed from all view definitions. |
| **Affected** | All 3 views |

### 4.4 REPLACE VIEW

| Decision | Details |
|---|---|
| **Teradata** | `REPLACE VIEW db.view_name AS ...` |
| **Snowflake** | `CREATE OR REPLACE VIEW db.view_name AS ...` |
| **Action** | Changed all `REPLACE VIEW` to `CREATE OR REPLACE VIEW`. |
| **Affected** | All 3 views |

### 4.5 ZEROIFNULL() and NULLIFZERO()

| Decision | Details |
|---|---|
| **Teradata** | `ZEROIFNULL(expr)` returns 0 if NULL; `NULLIFZERO(expr)` returns NULL if 0. |
| **Snowflake** | Both functions are natively supported with identical semantics. |
| **Action** | No changes needed. |
| **Affected** | VW_CUSTOMER_360, VW_BRANCH_PERFORMANCE, stored procedures |

### 4.6 HASHROW()

| Decision | Details |
|---|---|
| **Teradata** | `HASHROW(col1, col2, ...)` generates a hash of the row values. |
| **Snowflake** | `HASH(col1, col2, ...)` is the equivalent. Note: hash values will differ between platforms, so checksums should be compared within each platform, not cross-platform. |
| **Action** | Replaced `HASHROW(...)` with `HASH(...)`. |
| **Affected** | VW_REGULATORY_LARGE_TRANSACTIONS, validation checksum queries |

### 4.7 CSUM() (Cumulative Sum)

| Decision | Details |
|---|---|
| **Teradata** | `CSUM(expr, order_col)` is a Teradata-specific ordered analytical function for cumulative sums. |
| **Snowflake** | Use standard SQL window function: `SUM(expr) OVER (PARTITION BY ... ORDER BY order_col ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`. |
| **Action** | Rewrote `CSUM(SUM(snap.FEES_CHARGED), snap.SNAPSHOT_MONTH_KEY)` as `SUM(SUM(snap.FEES_CHARGED)) OVER (PARTITION BY b.BRANCH_ID ORDER BY snap.SNAPSHOT_MONTH_KEY ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`. |
| **Affected** | VW_BRANCH_PERFORMANCE |

### 4.8 MAVG() (Moving Average)

| Decision | Details |
|---|---|
| **Teradata** | `MAVG(expr, N, order_col)` computes a moving average over N rows. |
| **Snowflake** | Use standard SQL window function: `AVG(expr) OVER (PARTITION BY ... ORDER BY order_col ROWS BETWEEN N-1 PRECEDING AND CURRENT ROW)`. |
| **Action** | Rewrote `MAVG(SUM(volume), 3, month_key)` as `AVG(SUM(volume)) OVER (PARTITION BY b.BRANCH_ID ORDER BY snap.SNAPSHOT_MONTH_KEY ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)`. |
| **Affected** | VW_BRANCH_PERFORMANCE |

### 4.9 Inline FORMAT in SELECT

| Decision | Details |
|---|---|
| **Teradata** | `column_name (FORMAT 'ZZZ,ZZZ,ZZ9.99')` applies display formatting inline. |
| **Snowflake** | No inline FORMAT. Use `TO_CHAR(column, '999,999,999.99')` for formatted output. |
| **Action** | Removed inline FORMAT from all view/query column references. In the export scripts where formatting is needed for file output, applied `TO_CHAR()`. For views that feed dashboards, formatting is deferred to the reporting/BI layer. |
| **Affected** | All 3 views, all macros, BTEQ scripts, stored procedures |

### 4.10 Inline (NOT CASESPECIFIC) in SELECT

| Decision | Details |
|---|---|
| **Teradata** | `column_name (NOT CASESPECIFIC)` in a SELECT applies case-insensitive comparison for that expression. |
| **Snowflake** | Handled at the column definition level via `COLLATE 'en-ci'`. If the source column already has COLLATE, the behavior carries through to queries. |
| **Action** | Removed inline `(NOT CASESPECIFIC)` from SELECT statements. Case-insensitivity is enforced at the DDL level. |
| **Affected** | VW_REGULATORY_LARGE_TRANSACTIONS |

### 4.11 Date Arithmetic

| Decision | Details |
|---|---|
| **Teradata** | `CURRENT_DATE - column` returns an interval or integer days; `date - integer` subtracts days; `ADD_MONTHS(date, N)` adds months. |
| **Snowflake** | Use `DATEDIFF('day', col1, col2)` for day differences; `DATEADD('day', -N, date)` for subtraction; `ADD_MONTHS()` is supported natively; `DATEADD('month', N, date)` also works. |
| **Action** | Rewrote Teradata date arithmetic: `(CURRENT_DATE - col) / 365.25` -> `DATEDIFF('day', col, CURRENT_DATE) / 365.25`; `:date - :days` -> `DATEADD('day', -:days, :date)`; `date + 3` -> `DATEADD('day', 3, date)`. |
| **Affected** | Views, stored procedures, macros |

### 4.12 SAMPLE Clause

| Decision | Details |
|---|---|
| **Teradata** | `SAMPLE N` returns N random rows from the result set. |
| **Snowflake** | Use `LIMIT N` for a fixed row count (deterministic, based on query order) or `SAMPLE (N ROWS)` / `TABLESAMPLE` for random sampling. |
| **Action** | Replaced `SAMPLE 1000` with `LIMIT 1000` (since the query already has an ORDER BY, deterministic limiting is more appropriate than random sampling). |
| **Affected** | CUSTOMER_TXN_HISTORY macro |

---

## 5. Stored Procedure Translation Decisions

### 5.1 REPLACE PROCEDURE -> CREATE OR REPLACE PROCEDURE

| Decision | Details |
|---|---|
| **Teradata** | `REPLACE PROCEDURE db.proc(...)` |
| **Snowflake** | `CREATE OR REPLACE PROCEDURE db.proc(...) RETURNS type LANGUAGE SQL` |
| **Action** | Changed syntax. Added `RETURNS OBJECT`, `LANGUAGE SQL`, `EXECUTE AS CALLER`. |

### 5.2 OUT Parameters -> OBJECT Return

| Decision | Details |
|---|---|
| **Teradata** | `OUT p_rows INTEGER, OUT p_code INTEGER` - multiple output parameters. |
| **Snowflake** | Snowflake SQL procedures do not support OUT parameters directly. |
| **Action** | Replaced OUT parameters with a single `RETURNS OBJECT` containing key-value pairs (e.g., `OBJECT_CONSTRUCT('rows_inserted', val, 'return_code', val)`). Callers parse the returned JSON object. |

### 5.3 ACTIVITY_COUNT -> SQLROWCOUNT

| Decision | Details |
|---|---|
| **Teradata** | `ACTIVITY_COUNT` returns the number of rows affected by the last DML statement. |
| **Snowflake** | `SQLROWCOUNT` is the equivalent in Snowflake Scripting. |
| **Action** | Replaced all `ACTIVITY_COUNT` with `SQLROWCOUNT`. |

### 5.4 VOLATILE TABLE -> TEMPORARY TABLE

| Decision | Details |
|---|---|
| **Teradata** | `CREATE VOLATILE TABLE ... WITH DATA PRIMARY INDEX (...) ON COMMIT PRESERVE ROWS` |
| **Snowflake** | `CREATE OR REPLACE TEMPORARY TABLE ... AS SELECT ...` (Snowflake temp tables always preserve rows on commit; no PRIMARY INDEX) |
| **Action** | Replaced VOLATILE with TEMPORARY. Removed PRIMARY INDEX and ON COMMIT clauses. |

### 5.5 Exception Handling

| Decision | Details |
|---|---|
| **Teradata** | `DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ... END;` |
| **Snowflake** | `EXCEPTION WHEN OTHER THEN ...` block at the end of the procedure. |
| **Action** | Restructured error handling from DECLARE HANDLER to EXCEPTION block pattern. |

### 5.6 FORMAT in Procedure String Expressions

| Decision | Details |
|---|---|
| **Teradata** | `TRIM(variable (FORMAT 'Z(9)9'))`, `TRIM(p_return_code (FORMAT '-999999'))` |
| **Snowflake** | `TO_CHAR(variable)` or `TO_CHAR(variable, '999999')` |
| **Action** | Replaced all inline FORMAT with `TO_CHAR()`. |

### 5.7 Timestamp Arithmetic in Procedures

| Decision | Details |
|---|---|
| **Teradata** | `(CURRENT_TIMESTAMP(0) - v_start_ts) SECOND(4)` computes duration. |
| **Snowflake** | `TIMESTAMPDIFF('second', v_start_ts, CURRENT_TIMESTAMP())` |
| **Action** | Replaced with `TIMESTAMPDIFF` function. |

### 5.8 CAST(... AS DATE FORMAT ...) in Procedures

| Decision | Details |
|---|---|
| **Teradata** | `CAST(year_str || '-' || month_str || '-01' AS DATE FORMAT 'YYYY-MM-DD')` |
| **Snowflake** | `DATE_FROM_PARTS(year, month, 1)` or `TO_DATE(str, 'YYYY-MM-DD')` |
| **Action** | Used `DATE_FROM_PARTS()` for constructing dates from components (cleaner and avoids string manipulation). |

### 5.9 UPDATE ... FROM (Teradata Syntax)

| Decision | Details |
|---|---|
| **Teradata** | `UPDATE table FROM (subquery) src SET ... WHERE table.col = src.col` |
| **Snowflake** | Same syntax is supported: `UPDATE table SET ... FROM (subquery) src WHERE ...` |
| **Action** | Minor syntax reordering to match Snowflake convention (SET before FROM in some cases). The SP_CUSTOMER_SCD2 UPDATE...FROM pattern is compatible with Snowflake. |

---

## 6. Macro to Stored Procedure Conversion

### 6.1 General Approach

Teradata MACROs have no direct equivalent in Snowflake. The conversion strategy is:

| Aspect | Teradata Macro | Snowflake Procedure |
|---|---|---|
| Definition | `REPLACE MACRO db.name (params) AS (...)` | `CREATE OR REPLACE PROCEDURE db.name(params) RETURNS TABLE(...) LANGUAGE SQL` |
| Parameters | `:param_name` with optional defaults | Procedure parameters with defaults |
| Invocation | `EXEC macro_name(args)` | `CALL procedure_name(args)` |
| Result sets | Can return multiple result sets | Single result set (combined with UNION ALL and discriminator column) |
| Parameter refs | `:param` | `:P_PARAM` (Snowflake Scripting variable syntax) |

### 6.2 Multiple Result Sets

Teradata macros can contain multiple SELECT statements that return separate result sets. Snowflake stored procedures return a single result set.

**Solution:** Combined multiple SELECTs into a single `UNION ALL` query with a `CHECK_TYPE` or `PATTERN_TYPE` discriminator column. Consumers should filter on this column to get the specific result set they need.

### 6.3 Macro Parameter Defaults

| Teradata | Snowflake |
|---|---|
| `DEFAULT DATE` | `DEFAULT CURRENT_DATE` |
| `DEFAULT DATE - 30` | `DEFAULT DATEADD('day', -30, CURRENT_DATE)` |
| `DEFAULT 30` | `DEFAULT 30` (same) |

---

## 7. BTEQ Script Conversion

### 7.1 Conversion Strategy

BTEQ scripts were converted in two ways:

1. **bteq_daily_load.btq** -> Snowflake stored procedure (`SP_DAILY_ETL_PIPELINE`) because it requires control flow, error handling, and conditional logic that maps well to procedural code. A Snowflake Task definition is provided (commented) for scheduling.

2. **bteq_extract_report.btq** -> SnowSQL script (`snowsql_extract_report.sql`) using `COPY INTO @stage` for file exports.

### 7.2 BTEQ Command Mappings

| BTEQ Command | Snowflake Equivalent | Notes |
|---|---|---|
| `.LOGON host/user,` | SnowSQL connection profile or `--connection` flag | Configured externally |
| `.SET WIDTH N` | `!set output_format=csv` | Different paradigm |
| `.SET SEPARATOR '|'` | `!set field_delimiter='|'` | |
| `.EXPORT DATA FILE=path` | `COPY INTO @stage/path` | Uses Snowflake stages |
| `.EXPORT REPORT FILE=path` | `COPY INTO @stage/path` | Same mechanism |
| `.EXPORT RESET` | (implicit after COPY INTO completes) | |
| `.IF ACTIVITYCOUNT = 0` | `IF (v_count = 0) THEN` (in procedure) | |
| `.IF ERRORCODE <> 0` | `EXCEPTION WHEN OTHER THEN` | |
| `.LABEL name` / `.GOTO name` | Procedure control flow (`IF/ELSE`, `RETURN`) | |
| `.QUIT N` | `RETURN` with status object | Return code in JSON |
| `DATABASE dbname` | `USE DATABASE dbname; USE SCHEMA schemaname;` | |
| `EXEC macro(args)` | `CALL procedure(args)` | |

---

## 8. Data Type Mappings

| Teradata Type | Snowflake Type | Notes |
|---|---|---|
| `INTEGER` | `INTEGER` | Same |
| `BIGINT` | `BIGINT` | Same |
| `SMALLINT` | `SMALLINT` | Same |
| `BYTEINT` | `SMALLINT` | No BYTEINT in Snowflake |
| `DECIMAL(p,s)` | `DECIMAL(p,s)` | Same |
| `VARCHAR(n)` | `VARCHAR(n)` | Same |
| `CHAR(n)` | `CHAR(n)` | Same |
| `DATE` | `DATE` | FORMAT clause removed |
| `TIME(0)` | `TIME(0)` | Same |
| `TIMESTAMP(0)` | `TIMESTAMP_NTZ(0)` | NTZ for timezone-unaware |
| `TIMESTAMP(6)` | `TIMESTAMP_NTZ(6)` | NTZ for timezone-unaware |

---

## 9. Validation and Testing

### 9.1 Validation Queries

Converted validation queries are in `snowflake/data/validation/checksum_queries.sql`. These include:

1. **Row count validation** - Compare row counts per table between source and target.
2. **Column-level checksums** - Hash-based checksums on key columns (note: HASH() values will differ from HASHROW(); compare within-platform only).
3. **Aggregate checksums** - Year/month-level aggregates on fact tables.
4. **Business-level reconciliation** - Monthly balance totals.
5. **Referential integrity** - Orphaned fact records (account/customer keys not in dimensions).

### 9.2 Recommended Testing Approach

1. Deploy DDL in order (tables first, then views).
2. Load sample data from `data/seed/` CSVs.
3. Run validation queries on both source and target.
4. Compare row counts (should match exactly).
5. Compare aggregate totals (should match within rounding tolerance).
6. Execute each stored procedure with test parameters.
7. Execute each converted macro (now procedure) and verify output structure.

---

## 10. Deployment Execution Order

Execute the converted SQL files in the following order:

```
-- Phase 1: Create Tables (no dependencies)
snowflake/ddl/tables/01_dim_customer.sql
snowflake/ddl/tables/02_dim_account.sql
snowflake/ddl/tables/03_dim_product.sql
snowflake/ddl/tables/04_dim_branch.sql
snowflake/ddl/tables/05_dim_date.sql
snowflake/ddl/tables/06_fact_transaction.sql
snowflake/ddl/tables/07_fact_monthly_snapshot.sql

-- Phase 2: Create Views (depend on tables)
snowflake/ddl/views/01_vw_customer_360.sql
snowflake/ddl/views/02_vw_regulatory_large_transactions.sql
snowflake/ddl/views/03_vw_branch_performance.sql

-- Phase 3: Create Stored Procedures (depend on tables)
snowflake/dml/stored_procedures/sp_customer_scd2.sql
snowflake/dml/stored_procedures/sp_load_daily_transactions.sql
snowflake/dml/stored_procedures/sp_monthly_snapshot.sql

-- Phase 4: Create Macro-replacement Procedures (depend on tables)
snowflake/dml/macros/macro_daily_balance_check.sql
snowflake/dml/macros/macro_aml_screening.sql
snowflake/dml/macros/macro_customer_txn_history.sql

-- Phase 5: Deploy ETL Pipeline Procedure (depends on Phase 3 & 4)
snowflake/dml/scripts/snowsql_daily_load.sql

-- Phase 6: Validate
snowflake/data/validation/checksum_queries.sql
```

### Prerequisites

Before deploying, ensure the following Snowflake objects exist:

1. **Database:** `BANKING_DW`
2. **Schema:** `BANKING_DW` (or adjust fully-qualified names)
3. **Warehouse:** An appropriately-sized warehouse for ETL operations
4. **Stage:** `BANKING_DW.EXPORT_STAGE` (internal stage for file exports)
5. **Staging tables** referenced by procedures: `STG_TRANSACTIONS`, `STG_CUSTOMER`, `STG_TRANSACTION_ERRORS`, `ETL_LOG`, `ETL_BATCH_CONTROL`, `DIM_EXCHANGE_RATES`

---

## 11. Post-Migration Checklist

- [ ] All 7 tables created successfully
- [ ] All 3 views created successfully
- [ ] All 3 stored procedures created successfully
- [ ] All 3 macro-replacement procedures created successfully
- [ ] ETL pipeline procedure created successfully
- [ ] Sample data loaded from seed CSVs
- [ ] Row counts match between source and target
- [ ] Aggregate checksums match (within rounding tolerance)
- [ ] Referential integrity checks pass (zero orphans)
- [ ] Each stored procedure executes without error
- [ ] Each macro-replacement procedure returns expected result structure
- [ ] ETL pipeline procedure completes end-to-end
- [ ] Export scripts produce correctly formatted output files
- [ ] Snowflake Task created and scheduled (if automated scheduling is required)
- [ ] Query performance validated on representative data volumes

---

## 12. Known Differences and Caveats

### 12.1 Hash Value Differences
`HASHROW()` (Teradata) and `HASH()` (Snowflake) use different algorithms. Hash-based checksums will produce different values. Compare within each platform, not across platforms.

### 12.2 Primary Key Enforcement
Snowflake PRIMARY KEY constraints are **not enforced**. Unlike Teradata's UPI which physically prevents duplicate inserts, Snowflake will allow duplicate primary key values. Ensure ETL logic includes dedup where needed.

### 12.3 Case Sensitivity
Teradata `NOT CASESPECIFIC` columns have been converted to `COLLATE 'en-ci'`. This affects:
- WHERE clause comparisons (case-insensitive)
- JOIN conditions (case-insensitive)
- GROUP BY behavior (case-insensitive grouping)
- ORDER BY behavior (case-insensitive sorting)

Verify that downstream queries and reports produce expected results with case-insensitive collation.

### 12.4 TIMESTAMP Default Behavior
Teradata TIMESTAMP is timezone-unaware by default. We used `TIMESTAMP_NTZ` (No Time Zone) in Snowflake. If the Snowflake account has `TIMESTAMP_TYPE_MAPPING = 'TIMESTAMP_LTZ'`, explicitly specifying NTZ avoids surprises.

### 12.5 Auto-increment / Identity Gaps
Snowflake's AUTOINCREMENT may produce non-sequential values (gaps are possible due to internal optimization). This is generally acceptable for surrogate keys but should be documented if sequential IDs are a business requirement.

### 12.6 Multiple Result Sets from Macros
Original Teradata macros could return multiple independent result sets. The converted Snowflake procedures return a single UNION ALL result with a discriminator column. Downstream consumers (reports, applications) that expect multiple result sets must be updated to filter on the discriminator column.

### 12.7 BTEQ Flow Control
BTEQ `.LABEL`/`.GOTO` and `.IF ERRORCODE` patterns have been converted to procedural `IF/THEN/ELSE` and `EXCEPTION` blocks. The error handling semantics are slightly different: BTEQ continues to the label on error, while Snowflake procedures jump to the EXCEPTION block. Verify that error recovery behavior matches expectations.
