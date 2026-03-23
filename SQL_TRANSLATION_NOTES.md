# SQL Translation Notes: Teradata → Snowflake

This document records every translation decision made during the migration of the Banking DW from Teradata to Snowflake.

## DDL Translations

### Table-Level Changes

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `CREATE SET TABLE` | `CREATE OR REPLACE TABLE` | Snowflake has no SET/MULTISET distinction. All tables allow duplicates. If uniqueness was enforced by SET semantics, add explicit `UNIQUE` constraints. |
| `CREATE MULTISET TABLE` | `CREATE OR REPLACE TABLE` | Direct mapping — no change needed. |
| `NO FALLBACK` | Removed | Snowflake handles data redundancy automatically via its multi-cluster shared data architecture. |
| `NO BEFORE/AFTER JOURNAL` | Removed | Snowflake uses Time Travel and Fail-safe instead of journals. |
| `CHECKSUM = DEFAULT` | Removed | No Snowflake equivalent; data integrity is handled at the storage layer. |
| `DEFAULT MERGEBLOCKRATIO` | Removed | Teradata-specific storage tuning parameter with no Snowflake equivalent. |

### Column-Level Changes

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `BYTEINT` | `SMALLINT` | Snowflake does not have `BYTEINT`. `SMALLINT` is the closest equivalent. For boolean-like columns (0/1), `BOOLEAN` could also be used, but `SMALLINT` was chosen to maintain numeric compatibility with existing ETL logic. |
| `NOT CASESPECIFIC` | Removed | Snowflake is case-sensitive by default. Options considered: (1) `COLLATE 'en-ci'` on columns, (2) `UPPER()`/`LOWER()` in queries. Chose to remove and handle in application layer since case-insensitive collation affects all comparisons and may impact performance. Queries that depend on case-insensitive matching should use `ILIKE` or `LOWER()`. |
| `COMPRESS (val1, val2, ...)` | Removed | Snowflake compresses all data automatically using proprietary algorithms. Explicit compress lists are not needed and not supported. |
| `FORMAT 'YYYY-MM-DD'` on DATE | Removed | Snowflake does not support column-level `FORMAT`. Display formatting is done at query time using `TO_CHAR()`. |
| `GENERATED ALWAYS AS IDENTITY` | `AUTOINCREMENT START 1 INCREMENT 1` | Snowflake uses `AUTOINCREMENT` or `IDENTITY` syntax. Functionally equivalent. |
| `TIMESTAMP(0)` | `TIMESTAMP_NTZ` | Snowflake's `TIMESTAMP_NTZ` (no timezone) is the equivalent of Teradata's `TIMESTAMP(0)`. Precision defaults to 9 in Snowflake but values are stored efficiently. |
| `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` | `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ` | Explicit cast to `TIMESTAMP_NTZ` to match column type. |

### Index and Partitioning Changes

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `UNIQUE PRIMARY INDEX (UPI)` | `PRIMARY KEY` constraint | Snowflake PRIMARY KEY is declarative (not enforced) but documents intent. Used for documentation and BI tool metadata. |
| `PRIMARY INDEX (PI)` | Removed | Snowflake distributes data automatically across micro-partitions. No manual distribution needed. |
| Non-Unique Primary Index (NUPI) | Removed | No equivalent needed. Snowflake's pruning handles query performance. |
| Secondary Index (`INDEX idx_name (col)`) | Removed | Snowflake does not support traditional B-tree indexes. Query performance is managed via micro-partition pruning and clustering keys. |
| `PARTITION BY RANGE_N(col BETWEEN ... EACH INTERVAL)` | `CLUSTER BY (col)` | Snowflake uses automatic micro-partitioning. `CLUSTER BY` on the partition column gives Snowflake hints to co-locate data for similar pruning benefits. |
| `COLLECT STATISTICS COLUMN (col)` | Removed entirely | Snowflake collects and maintains statistics automatically. Manual collection is not needed and not supported. |

### Comments

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `COMMENT ON TABLE` | `COMMENT = '...'` in CREATE TABLE, or `COMMENT ON TABLE` | Both syntaxes work in Snowflake. Used inline `COMMENT =` for table-level, `COMMENT ON COLUMN` for column-level. |

## DML / View Translations

### Query Syntax

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `SEL` (shorthand for SELECT) | `SELECT` | `SEL` is a Teradata-specific abbreviation. Snowflake requires full `SELECT` keyword. |
| `LOCKING ROW FOR ACCESS` | Removed | Snowflake uses MVCC (Multi-Version Concurrency Control) — dirty reads and lock contention are not applicable. |
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Direct equivalent in Snowflake. |
| `QUALIFY ROW_NUMBER() OVER (...)` | Kept as-is | Snowflake natively supports `QUALIFY`. No change needed. |
| `ZEROIFNULL(expr)` | Kept as-is | Natively supported in Snowflake. |
| `NULLIFZERO(expr)` | Kept as-is | Natively supported in Snowflake. |
| `HASHROW(col1, col2, ...)` | `HASH(col1, col2, ...)` | Snowflake's `HASH()` function serves the same purpose. Note: hash values will differ between platforms — checksums must be recomputed on target. |
| `SAMPLE n` | `LIMIT n` or `SAMPLE (n ROWS)` | `SAMPLE` is supported in Snowflake but syntax differs slightly. For row-limiting macros, `LIMIT` is cleaner and more standard. |
| `expr (FORMAT 'pattern')` | `TO_CHAR(expr, 'pattern')` | Inline FORMAT is Teradata-specific. Use `TO_CHAR()` for display formatting in Snowflake. |
| `col (NOT CASESPECIFIC)` in SELECT | Removed | Handle case-insensitive comparisons with `ILIKE` or `LOWER()` in WHERE clauses. |

### Date and Time Functions

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `CURRENT_DATE` | `CURRENT_DATE()` | Snowflake uses function syntax with parentheses. |
| `CURRENT_TIMESTAMP(0)` | `CURRENT_TIMESTAMP()` | Precision parameter not needed in Snowflake. |
| `ADD_MONTHS(date, n)` | `DATEADD('month', n, date)` | Snowflake's standard date arithmetic function. `ADD_MONTHS` is also supported in Snowflake but `DATEADD` is preferred for consistency. |
| `date1 - date2` (integer days) | `DATEDIFF('day', date2, date1)` | Teradata allows direct date subtraction returning integer days. Snowflake requires `DATEDIFF`. |
| `CAST(date AS DATE FORMAT 'YYYYMMDD')` | `TO_NUMBER(TO_CHAR(date, 'YYYYMMDD'))` | Convert date to integer key format. |
| `EXTRACT(YEAR FROM date)` | Kept as-is | Natively supported. |
| Teradata timestamp arithmetic (`ts + time_interval`) | `DATEADD` / `TIMEADD` / cast concatenation | Snowflake doesn't support direct timestamp + time arithmetic the same way. |

### Analytic / OLAP Functions

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `CSUM(expr, sort_col)` | `SUM(expr) OVER (ORDER BY sort_col ROWS UNBOUNDED PRECEDING)` | `CSUM` is Teradata's proprietary cumulative sum. Replaced with standard SQL window function. Added `PARTITION BY` where the original context required it. |
| `MAVG(expr, n, sort_col)` | `AVG(expr) OVER (ORDER BY sort_col ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW)` | `MAVG` is Teradata's proprietary moving average. Replaced with standard SQL window function. Note: `MAVG(x, 3, col)` uses a 3-row window, so `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW`. |
| `RANK() OVER (...)` | Kept as-is | Standard SQL, natively supported. |
| `ROW_NUMBER() OVER (...)` | Kept as-is | Standard SQL, natively supported. |

## Stored Procedure Translations

| Teradata Feature | Snowflake Translation | Rationale |
|---|---|---|
| `REPLACE PROCEDURE` | `CREATE OR REPLACE PROCEDURE` | Direct equivalent. |
| `IN/OUT` parameters | `RETURNS VARIANT` (JSON) | Snowflake SQL procedures don't support `OUT` parameters the same way. Changed to return a `VARIANT` (JSON object) with all output values using `OBJECT_CONSTRUCT()`. |
| `ACTIVITY_COUNT` | `SQLROWCOUNT` | Snowflake's equivalent for rows affected by last DML statement. |
| `SQLCODE` / `SQLSTATE` in handlers | `SQLCODE` / `SQLERRM` in `EXCEPTION WHEN OTHER` | Snowflake uses `EXCEPTION WHEN OTHER THEN` blocks instead of `DECLARE EXIT HANDLER FOR SQLEXCEPTION`. |
| `UPDATE tgt FROM (subquery) src SET ...` | `UPDATE tgt SET ... WHERE tgt.key IN (SELECT key FROM ...)` | Teradata's `UPDATE...FROM` syntax is not supported in Snowflake. Refactored to use standard subquery in WHERE clause. |

## Macro → Stored Procedure Conversions

Teradata macros have no direct Snowflake equivalent. Each macro was converted to a `RETURNS TABLE` stored procedure:

| Original Macro | Snowflake Procedure | Key Changes |
|---|---|---|
| `BANKING_DW.AML_SCREENING` | `BANKING_DW.SP_AML_SCREENING` | Multi-statement macro combined into single `UNION ALL` query. Macro parameters converted to procedure parameters. `EXEC MACRO` calls replaced with `CALL PROCEDURE`. |
| `BANKING_DW.CUSTOMER_TXN_HISTORY` | `BANKING_DW.SP_CUSTOMER_TXN_HISTORY` | `SAMPLE 1000` replaced with `LIMIT 1000`. |
| `BANKING_DW.DAILY_BALANCE_CHECK` | `BANKING_DW.SP_DAILY_BALANCE_CHECK` | Multi-statement macro combined into single `UNION ALL` query with compatible column structure. |

## BTEQ → SnowSQL Script Conversions

| BTEQ Feature | Snowflake Translation | Rationale |
|---|---|---|
| `.LOGON host/user,password` | SnowSQL connection (`snowsql -c connection_name`) | Credentials managed via SnowSQL config file or environment variables. |
| `.SET WIDTH n` | `!set output_format=csv` | SnowSQL uses different output formatting. |
| `.SET SEPARATOR '\|'` | CSV file format | Handled at the `COPY INTO` or `FILE_FORMAT` level. |
| `.IF ACTIVITYCOUNT = 0 THEN .GOTO label` | Procedural `IF` in stored procedure | Wrapped BTEQ scripts into stored procedures for proper flow control. |
| `.IF ERRORCODE <> 0 THEN .GOTO label` | `EXCEPTION WHEN OTHER` | Error handling via SQL scripting exception blocks. |
| `.EXPORT DATA FILE=path` | `COPY INTO @stage` | Snowflake exports to named stages (internal or external). |
| `.EXPORT REPORT FILE=path` | `COPY INTO @stage` with formatting | Same mechanism, formatting done in query with `TO_CHAR()`. |
| `.LABEL name` / `.GOTO name` | Removed (procedural flow) | Replaced with structured `IF/ELSE` and `EXCEPTION` blocks. |
| `.QUIT n` (return code) | `RETURN OBJECT_CONSTRUCT('exit_code', n)` | Return codes captured in procedure return value. |
| `CREATE VOLATILE TABLE ... WITH DATA ON COMMIT PRESERVE ROWS` | `CREATE OR REPLACE TEMPORARY TABLE` | Snowflake temporary tables persist for the session and don't need `ON COMMIT PRESERVE ROWS`. |

## Known Differences and Caveats

1. **Hash values will differ**: `HASHROW()` (Teradata) and `HASH()` (Snowflake) use different algorithms. Checksum validation must re-compute hashes on target rather than comparing cross-platform.

2. **Case sensitivity**: Teradata's `NOT CASESPECIFIC` columns match case-insensitively by default. Snowflake is case-sensitive. Queries relying on case-insensitive matching must be updated to use `ILIKE`, `LOWER()`, or `COLLATE 'en-ci'`.

3. **Identity column values**: `AUTOINCREMENT` values in Snowflake will not match Teradata's `GENERATED ALWAYS AS IDENTITY` values. Surrogate keys will be reassigned during migration. Foreign key references (ACCOUNT_KEY, CUSTOMER_KEY) must be remapped.

4. **Timestamp precision**: Teradata `TIMESTAMP(0)` truncates to seconds. Snowflake `TIMESTAMP_NTZ` defaults to nanosecond precision. Values will match but type metadata differs.

5. **NULL handling in comparisons**: Teradata and Snowflake handle NULLs identically in most cases, but `COMPRESS ''` columns in Teradata may have stored empty strings where Snowflake might have NULLs. Validate with `COUNT(col)` vs `COUNT(*)`.

6. **Decimal precision in aggregates**: Teradata's `(DECIMAL(18,2))` cast in aggregates is replaced by Snowflake's automatic precision handling. Results should match but verify with aggregate checksum queries.
