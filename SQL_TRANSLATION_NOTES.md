# SQL Translation Notes: Teradata to Snowflake

This document records every translation decision made during the conversion of the Banking Data Warehouse (`BANKING_DW`) from Teradata to Snowflake.

---

## Table of Contents

1. [Global Translation Rules](#1-global-translation-rules)
2. [Per-File Translation Details](#2-per-file-translation-details)
3. [Key Decision Register](#3-key-decision-register)

---

## 1. Global Translation Rules

These rules were applied uniformly across all converted files.

### DDL Removals

| Teradata Construct | Action | Rationale |
|---|---|---|
| `SET` / `MULTISET` keyword | Removed | Snowflake has no SET/MULTISET distinction. All tables allow duplicates. Where SET semantics mattered (dimension tables), uniqueness is enforced via `PRIMARY KEY` constraints. |
| `NO FALLBACK` | Removed | Snowflake handles data redundancy automatically via micro-partitions and replication. |
| `NO BEFORE JOURNAL` / `NO AFTER JOURNAL` | Removed | No Snowflake equivalent. Snowflake uses Time Travel for recovery. |
| `CHECKSUM = DEFAULT` | Removed | No Snowflake equivalent. Data integrity is handled automatically. |
| `DEFAULT MERGEBLOCKRATIO` | Removed | No Snowflake equivalent. Storage optimization is automatic. |
| `COMPRESS (...)` / `COMPRESS value` | Removed | Snowflake auto-compresses all data. No action needed. Compression ratios are typically equal or better. |
| `NOT CASESPECIFIC` | Removed | Snowflake is case-sensitive by default. Added comments noting where `COLLATE 'en-ci'` or `UPPER()`/`LOWER()` may be needed for business logic (especially customer name matching, address lookups). |
| `FORMAT 'YYYY-MM-DD'` etc. | Removed | No column-level FORMAT in Snowflake. Display formatting moved to application layer or `TO_CHAR()` in views/reports. |
| `COLLECT STATISTICS` | Removed entirely | Snowflake collects statistics automatically. No manual intervention needed. |
| Secondary indexes (`NUPI`, `IDX_*`) | Removed | Snowflake does not support user-created indexes. Added comments noting these should be covered by clustering keys if performance warrants. |

### DDL Replacements

| Teradata Construct | Snowflake Replacement | Notes |
|---|---|---|
| `CREATE SET TABLE` / `CREATE MULTISET TABLE` | `CREATE TABLE` | Simple removal of SET/MULTISET keyword |
| `BYTEINT` | `SMALLINT` | Snowflake has no BYTEINT type. SMALLINT is the smallest integer type. |
| `GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` | `AUTOINCREMENT START 1 INCREMENT 1` | Snowflake identity column syntax |
| `UNIQUE PRIMARY INDEX UPI_xxx (col)` | `PRIMARY KEY (col)` | Declared as table constraint. PKs in Snowflake are not enforced but serve as documentation and are used by the optimizer. |
| `PARTITION BY RANGE_N(col BETWEEN ... EACH INTERVAL ...)` | `CLUSTER BY (col)` | Snowflake uses micro-partitioning automatically; CLUSTER BY hints improve pruning for frequently filtered columns. |
| `TIMESTAMP(0) DEFAULT CURRENT_TIMESTAMP(0)` | `TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()` | Snowflake uses `TIMESTAMP_NTZ` (no timezone) as the equivalent of Teradata's default TIMESTAMP. |
| `DEFAULT TIMESTAMP '9999-12-31 23:59:59'` | `DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ` | Explicit cast to TIMESTAMP_NTZ |

### DML Replacements

| Teradata Construct | Snowflake Replacement | Notes |
|---|---|---|
| `SEL` | `SELECT` | Teradata shorthand not supported in Snowflake |
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Standard Snowflake syntax |
| `REPLACE PROCEDURE` | `CREATE OR REPLACE PROCEDURE` | Standard Snowflake syntax |
| `REPLACE MACRO` | `CREATE OR REPLACE PROCEDURE` | Macros have no Snowflake equivalent; converted to stored procedures |
| `LOCKING ROW FOR ACCESS` | Removed | No equivalent needed. Snowflake uses MVCC for consistent reads. |
| `HASHROW(...)` | `HASH(...)` | Different hash algorithms; values will differ between platforms. |
| `CSUM(expr, order_col)` | `SUM(expr) OVER (PARTITION BY ... ORDER BY ... ROWS UNBOUNDED PRECEDING)` | Teradata cumulative sum replaced with standard window function |
| `MAVG(expr, N, order_col)` | `AVG(expr) OVER (PARTITION BY ... ORDER BY ... ROWS BETWEEN N-1 PRECEDING AND CURRENT ROW)` | Teradata moving average replaced with standard window function |
| `SAMPLE N` | `LIMIT N` | Teradata SAMPLE returns random rows; macro context suggests LIMIT (top N ordered) was intended |
| `ACTIVITY_COUNT` | `SQLROWCOUNT` | Snowflake SQL scripting equivalent for row count after DML |
| `SQLCODE` / `EXIT HANDLER FOR SQLEXCEPTION` | `EXCEPTION WHEN OTHER THEN` / `SQLERRM` | Snowflake uses TRY/CATCH-style exception blocks |
| `:param` (macro parameters) | `:PARAM` (procedure parameters) | Snowflake SQL scripting uses same colon-prefix syntax |
| `VOLATILE TABLE` | `TEMPORARY TABLE` | Snowflake equivalent for session-scoped temp tables |
| `(FORMAT '...')` in expressions | `TO_CHAR(expr, 'format')` | Display formatting in Snowflake uses TO_CHAR |
| `CAST(date AS DATE FORMAT 'YYYYMMDD') AS INTEGER` | `TO_NUMBER(TO_CHAR(date, 'YYYYMMDD'))` | Teradata-style FORMAT cast replaced with Snowflake functions |
| `(date1 - date2)` date arithmetic | `DATEDIFF('day', date2, date1)` | Snowflake requires explicit DATEDIFF function |
| `CURRENT_DATE` | `CURRENT_DATE()` | Snowflake requires parentheses |
| `DATE - N` (integer days) | `DATEADD('day', -N, date)` | Snowflake requires DATEADD for date arithmetic |

---

## 2. Per-File Translation Details

### DDL / Tables

#### `01_dim_customer.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `CREATE SET TABLE` | `CREATE TABLE` | SET removed; PK on CUSTOMER_KEY ensures uniqueness |
| `CUSTOMER_KEY BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1)` | `CUSTOMER_KEY BIGINT NOT NULL AUTOINCREMENT START 1 INCREMENT 1` | Identity syntax change |
| `FIRST_NAME VARCHAR(50) NOT CASESPECIFIC NOT NULL` | `FIRST_NAME VARCHAR(50) NOT NULL` | Case-sensitivity note added as comment |
| `GENDER CHAR(1) COMPRESS ('M', 'F', 'O')` | `GENDER CHAR(1)` | COMPRESS removed |
| `DATE_OF_BIRTH DATE FORMAT 'YYYY-MM-DD'` | `DATE_OF_BIRTH DATE` | FORMAT removed |
| `IS_ACTIVE BYTEINT DEFAULT 1 COMPRESS (0, 1)` | `IS_ACTIVE SMALLINT DEFAULT 1` | BYTEINT -> SMALLINT, COMPRESS removed |
| `UNIQUE PRIMARY INDEX UPI_CUSTOMER_KEY (CUSTOMER_KEY)` | `PRIMARY KEY (CUSTOMER_KEY)` | UPI -> PK |
| `INDEX NUPI_CUSTOMER_ID (CUSTOMER_ID)` | Removed | Comment added about clustering keys |
| `PARTITION BY RANGE_N(ONBOARDING_DATE ...)` | `CLUSTER BY (ONBOARDING_DATE)` | PPI -> clustering key |
| `COLLECT STATISTICS COLUMN (CUSTOMER_ID) ...` | Removed | Automatic in Snowflake |

#### `02_dim_account.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `CREATE MULTISET TABLE` | `CREATE TABLE` | MULTISET removed |
| `ACCOUNT_KEY ... GENERATED ALWAYS AS IDENTITY` | `ACCOUNT_KEY ... AUTOINCREMENT START 1 INCREMENT 1` | Identity syntax |
| `CREDIT_LIMIT DECIMAL(15,2) COMPRESS 0` | `CREDIT_LIMIT DECIMAL(15,2)` | Single-value COMPRESS removed |
| `IS_JOINT_ACCOUNT BYTEINT DEFAULT 0 COMPRESS (0, 1)` | `IS_JOINT_ACCOUNT SMALLINT DEFAULT 0` | BYTEINT -> SMALLINT |
| `PARTITION BY RANGE_N(OPENING_DATE ...)` | `CLUSTER BY (OPENING_DATE)` | PPI -> clustering key |

#### `03_dim_product.sql`

| Original | Snowflake | Notes |
|---|---|---|
| PI on `PRODUCT_ID` | `PRIMARY KEY (PRODUCT_ID)` | UPI -> PK |
| No clustering | No `CLUSTER BY` | Small table (~10 rows), clustering unnecessary |

#### `04_dim_branch.sql`

| Original | Snowflake | Notes |
|---|---|---|
| PI on `BRANCH_ID` | `PRIMARY KEY (BRANCH_ID)` | UPI -> PK |
| `EMPLOYEE_COUNT SMALLINT COMPRESS 0` | `EMPLOYEE_COUNT SMALLINT` | Single-value COMPRESS removed |
| No clustering | No `CLUSTER BY` | Small table (~14 rows), clustering unnecessary |

#### `05_dim_date.sql`

| Original | Snowflake | Notes |
|---|---|---|
| PI on `DATE_KEY` | `PRIMARY KEY (DATE_KEY)` | UPI -> PK |
| Multiple `BYTEINT` columns | All converted to `SMALLINT` | DAY_OF_WEEK, DAY_OF_MONTH, WEEK_OF_YEAR, etc. |
| `HOLIDAY_NAME VARCHAR(50) COMPRESS ''` | `HOLIDAY_NAME VARCHAR(50)` | Single-value COMPRESS removed |
| No clustering | No `CLUSTER BY` | Static reference table (~10,958 rows) |

#### `06_fact_transaction.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `CREATE MULTISET TABLE` | `CREATE TABLE` | MULTISET removed |
| `PRIMARY INDEX PI_FACT_TXN (ACCOUNT_KEY, TRANSACTION_DATE)` | `CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)` | Composite PI -> clustering key. Column order swapped: TRANSACTION_DATE first for better date-range pruning. |
| No explicit PK in Teradata | `PRIMARY KEY (TRANSACTION_ID)` | Added PK on TRANSACTION_ID per requirements |
| `PARTITION BY RANGE_N(TRANSACTION_DATE ... EACH INTERVAL '1' MONTH, NO RANGE)` | Handled by `CLUSTER BY` | Snowflake micro-partitions handle this automatically |
| `FLAG_REASON VARCHAR(50) COMPRESS ''` | `FLAG_REASON VARCHAR(50)` | COMPRESS removed |

#### `07_fact_monthly_snapshot.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `PRIMARY INDEX PI_MONTHLY_SNAP (ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)` | `CLUSTER BY (SNAPSHOT_DATE, ACCOUNT_KEY)` | Composite PI -> clustering key using SNAPSHOT_DATE for better date pruning |
| `DAYS_IN_OVERDRAFT SMALLINT DEFAULT 0 COMPRESS 0` | `DAYS_IN_OVERDRAFT SMALLINT DEFAULT 0` | COMPRESS removed |

---

### DDL / Views

#### `01_vw_customer_360.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `REPLACE VIEW` | `CREATE OR REPLACE VIEW` | Standard syntax |
| `LOCKING ROW FOR ACCESS` | Removed | MVCC handles concurrency |
| `SEL` (5 occurrences) | `SELECT` | Teradata shorthand |
| `(FORMAT 'ZZZ,ZZZ,ZZ9.99')` on TOTAL_BALANCE | Removed | Display formatting removed from view |
| Correlated scalar subquery with `QUALIFY ROW_NUMBER()` | CTE `latest_snapshot` with `ROW_NUMBER()` + `LEFT JOIN` | **Major rewrite**: The original correlated subquery inside SUM(CASE) with QUALIFY is not valid Snowflake syntax. Refactored as a CTE that pre-computes the latest snapshot per account, then joined. |
| `CAST((CURRENT_DATE - c.ONBOARDING_DATE) / 365.25 ...)` | `CAST(DATEDIFF('day', c.ONBOARDING_DATE, CURRENT_DATE()) / 365.25 ...)` | Date arithmetic |
| `CURRENT_DATE - 90` | `DATEADD('day', -90, CURRENT_DATE())` | Date arithmetic |

#### `02_vw_regulatory_large_transactions.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `c.FIRST_NAME (NOT CASESPECIFIC)` | `c.FIRST_NAME` | NOT CASESPECIFIC removed from SELECT |
| `c.LAST_NAME (NOT CASESPECIFIC)` | `c.LAST_NAME` | NOT CASESPECIFIC removed from SELECT |
| `HASHROW(ft.TRANSACTION_ID, ft.TRANSACTION_DATE)` | `HASH(ft.TRANSACTION_ID, ft.TRANSACTION_DATE)` | Hash function replacement |
| `QUALIFY ROW_NUMBER() OVER (...)` | Kept as-is | Snowflake supports QUALIFY natively |

#### `03_vw_branch_performance.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `TRIM(d.CALENDAR_YEAR (FORMAT '9999'))` | `TO_CHAR(d.CALENDAR_YEAR)` | FORMAT cast replaced with TO_CHAR |
| `SUM(snap.CLOSING_BALANCE) (FORMAT '...')` | `SUM(snap.CLOSING_BALANCE)` | FORMAT removed from aggregate |
| `CSUM(SUM(snap.FEES_CHARGED), snap.SNAPSHOT_MONTH_KEY)` | `SUM(SUM(snap.FEES_CHARGED)) OVER (PARTITION BY b.BRANCH_ID ORDER BY snap.SNAPSHOT_MONTH_KEY ROWS UNBOUNDED PRECEDING)` | **CSUM -> window function**: Added PARTITION BY BRANCH_ID so cumulative sum is per-branch. ROWS UNBOUNDED PRECEDING gives running total. |
| `MAVG(SUM(...), 3, snap.SNAPSHOT_MONTH_KEY)` | `AVG(SUM(...)) OVER (PARTITION BY b.BRANCH_ID ORDER BY snap.SNAPSHOT_MONTH_KEY ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` | **MAVG -> window function**: 3-month window = current row + 2 preceding. Added PARTITION BY BRANCH_ID. |
| `(FORMAT 'ZZ9.99')` on PCT_OF_REGION_DEPOSITS | Removed | Display formatting removed |
| `ADD_MONTHS(CURRENT_DATE, -24)` | `ADD_MONTHS(CURRENT_DATE(), -24)` | Added parentheses to CURRENT_DATE |

---

### DML / Macros -> Stored Procedures

#### `macro_aml_screening.sql` -> `sp_aml_screening.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `REPLACE MACRO ... AS (stmt1; stmt2; stmt3;)` | `CREATE OR REPLACE PROCEDURE ... RETURNS TABLE(...) LANGUAGE SQL` | **Multi-result-set limitation**: Teradata macros can return multiple result sets. Snowflake procedures return one. Combined all 3 patterns with UNION ALL into a single result set. Used generic DETAIL_1..DETAIL_6 columns with VARCHAR type to accommodate different pattern schemas. |
| `screening_date DATE FORMAT 'YYYY-MM-DD' DEFAULT DATE` | `SCREENING_DATE DATE DEFAULT CURRENT_DATE()` | FORMAT removed, DATE -> CURRENT_DATE() |
| `:screening_date - :lookback_days` | `DATEADD('day', -:LOOKBACK_DAYS, :SCREENING_DATE)` | Date arithmetic |
| `SUM(ft.BASE_CURRENCY_AMOUNT) (FORMAT '...')` | `CAST(SUM(ft.BASE_CURRENCY_AMOUNT) AS VARCHAR)` | FORMAT replaced with CAST for UNION ALL compatibility |
| `dr.DEBIT_DATE - cr.CREDIT_DATE` | `DATEDIFF('day', cr.CREDIT_DATE, dr.DEBIT_DATE)` | Date subtraction |
| `cr.CREDIT_DATE + 3` | `DATEADD('day', 3, cr.CREDIT_DATE)` | Date addition |

#### `macro_customer_txn_history.sql` -> `sp_customer_txn_history.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `REPLACE MACRO` | `CREATE OR REPLACE PROCEDURE ... RETURNS TABLE(...)` | Macro -> procedure |
| `start_date DATE FORMAT 'YYYY-MM-DD' DEFAULT DATE - 30` | `START_DATE DATE DEFAULT DATEADD('day', -30, CURRENT_DATE())` | Date arithmetic + FORMAT removal |
| `ft.TRANSACTION_DATE (FORMAT 'YYYY-MM-DD') AS TXN_DATE` | `ft.TRANSACTION_DATE AS TXN_DATE` | FORMAT removed |
| `ft.TRANSACTION_AMOUNT (FORMAT 'S ZZZ,ZZZ,ZZ9.99') AS AMOUNT` | `ft.TRANSACTION_AMOUNT AS AMOUNT` | FORMAT removed |
| `SAMPLE 1000` | `LIMIT 1000` | SAMPLE gives random rows; LIMIT with ORDER BY gives deterministic top-N |

#### `macro_daily_balance_check.sql` -> `sp_daily_balance_check.sql`

| Original | Snowflake | Notes |
|---|---|---|
| Two separate SELECT statements | Combined with `UNION ALL` | Same multi-result-set pattern as AML screening |
| `ft.RUNNING_BALANCE (FORMAT 'S ZZZ,ZZZ,ZZ9.99')` | `CAST(ft.RUNNING_BALANCE AS VARCHAR)` | FORMAT replaced |
| `QUALIFY ROW_NUMBER()` | Kept as-is | Natively supported |
| `ft.RUNNING_BALANCE - a.OVERDRAFT_LIMIT (FORMAT '...')` | `CAST(ft.RUNNING_BALANCE - a.OVERDRAFT_LIMIT AS VARCHAR)` | Operator precedence: removed FORMAT that could interfere |

---

### DML / Stored Procedures

#### `sp_customer_scd2.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `REPLACE PROCEDURE ... (IN p_batch_id BIGINT, OUT p_new_rows INTEGER, ...)` | `CREATE OR REPLACE PROCEDURE ... RETURNS VARCHAR` | Snowflake SQL procedures cannot have OUT parameters directly. Return status as VARCHAR. |
| `DECLARE v_current_ts TIMESTAMP(0)` | `DECLARE v_current_ts TIMESTAMP_NTZ(0)` | TIMESTAMP -> TIMESTAMP_NTZ |
| `SET v_current_ts = CURRENT_TIMESTAMP(0)` | `v_current_ts := CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)` | Snowflake assignment syntax |
| `UPDATE tgt FROM (SEL ...) src SET ... WHERE ...` | `UPDATE tgt SET ... FROM (...) src WHERE ...` | Snowflake UPDATE...FROM syntax (SET before FROM) |
| `SET p_changed = ACTIVITY_COUNT` | `v_changed := SQLROWCOUNT` | ACTIVITY_COUNT -> SQLROWCOUNT |
| `COLLECT STATISTICS` | Removed | Automatic in Snowflake |

#### `sp_load_daily_transactions.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `IN p_batch_date DATE FORMAT 'YYYY-MM-DD'` | `P_BATCH_DATE DATE` | FORMAT removed from parameter |
| `OUT p_rows_inserted INTEGER, OUT p_return_code INTEGER` | Returns VARCHAR | OUT params replaced with return string |
| `DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ... END` | `EXCEPTION WHEN OTHER THEN ...` | Teradata handler -> Snowflake exception block at end of procedure |
| `SQLCODE` | `SQLERRM` | Snowflake uses SQLERRM for error message in exception handler |
| `TRIM(p_return_code (FORMAT '-999999'))` | `TO_CHAR(...)` | FORMAT in string concatenation -> TO_CHAR |
| `CAST(CURRENT_TIMESTAMP(0) AS VARCHAR(26))` | `TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS')` | Timestamp formatting |
| `stg.TRANSACTION_DATE (TIMESTAMP(6)) + (stg.TRANSACTION_TIME - TIME '00:00:00' ...)` | `stg.TRANSACTION_DATE::TIMESTAMP_NTZ(6) + stg.TRANSACTION_TIME` | Simplified timestamp construction |
| `CAST(CAST(stg.TRANSACTION_DATE AS DATE FORMAT 'YYYYMMDD') AS INTEGER)` | `TO_NUMBER(TO_CHAR(stg.TRANSACTION_DATE, 'YYYYMMDD'))` | Date-to-integer conversion |
| `CAST((CURRENT_TIMESTAMP(0) - v_start_ts) SECOND(4) AS VARCHAR(15))` | `TO_CHAR(TIMESTAMPDIFF('SECOND', :v_start_ts, CURRENT_TIMESTAMP())) \|\| 's'` | Duration calculation |

#### `sp_monthly_snapshot.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `CREATE VOLATILE TABLE VT_TXN_AGGREGATES AS (...) WITH DATA PRIMARY INDEX (ACCOUNT_KEY) ON COMMIT PRESERVE ROWS` | `CREATE TEMPORARY TABLE IF NOT EXISTS TMP_TXN_AGGREGATES AS SELECT ...` | VOLATILE -> TEMPORARY. PRIMARY INDEX and ON COMMIT PRESERVE ROWS removed. |
| `TRIM(p_snapshot_year (FORMAT '9999')) \|\| '-' \|\| TRIM(p_snapshot_month (FORMAT '99')) \|\| '-01'` | `TO_CHAR(:P_SNAPSHOT_YEAR) \|\| '-' \|\| LPAD(TO_CHAR(:P_SNAPSHOT_MONTH), 2, '0') \|\| '-01'` | FORMAT -> TO_CHAR + LPAD for zero-padding |
| `CAST(... AS DATE FORMAT 'YYYY-MM-DD')` | `TO_DATE(..., 'YYYY-MM-DD')` | DATE FORMAT cast -> TO_DATE |
| `ADD_MONTHS(v_period_start, 1) - 1` | `DATEADD('day', -1, ADD_MONTHS(:v_period_start, 1))` | Date arithmetic |
| `(v_period_end - v_period_start + 1) (SMALLINT)` | `(DATEDIFF('day', :v_period_start, :v_period_end) + 1)::SMALLINT` | Date subtraction + cast |
| `ZEROIFNULL(agg.OVERDRAFT_DAYS) (SMALLINT)` | `ZEROIFNULL(agg.OVERDRAFT_DAYS)::SMALLINT` | Teradata cast syntax -> Snowflake :: cast |
| `MERGE INTO ... USING (...) src ON ...` | Kept same structure | MERGE is supported in Snowflake with identical syntax |
| `DROP TABLE VT_TXN_AGGREGATES` | `DROP TABLE IF EXISTS TMP_TXN_AGGREGATES` | Added IF EXISTS for safety |

---

### DML / BTEQ Scripts -> Stored Procedures

#### `bteq_daily_load.btq` -> `snowsql_daily_load.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `.LOGON TDPROD/etl_svc_acct,;` | Removed | Use SnowSQL connection config (`--connection`) or environment variables |
| `.SET WIDTH 200; .SET SEPARATOR '\|';` | Removed | SnowSQL output format configured externally |
| `.IF ACTIVITYCOUNT = 0 THEN .GOTO NOSTAGING;` | `IF (:v_staging_count = 0) THEN RETURN 'WARNING...'; END IF;` | GOTO -> IF/RETURN |
| `.IF ERRORCODE <> 0 THEN .GOTO ERRORHANDLER;` | `EXCEPTION WHEN OTHER THEN ...` | Error handling via exception blocks |
| `.GOTO / .LABEL` | IF/ELSE blocks + EXCEPTION | Restructured as procedural control flow |
| `.EXPORT REPORT FILE=...` | `COPY INTO @stage ... FILE_FORMAT = (TYPE = 'CSV')` | Export to internal stage |
| `CREATE VOLATILE TABLE VT_BATCH` | Local variable `:v_batch_id` | Simplified; no need for temp table to hold a single value |
| `EXEC BANKING_DW.DAILY_BALANCE_CHECK(...)` | `CALL BANKING_DW.SP_DAILY_BALANCE_CHECK(...)` | EXEC macro -> CALL procedure |
| `.QUIT 0` / `.QUIT 4` / `.QUIT 8` | `RETURN 'SUCCESS...'` / `RETURN 'WARNING...'` / `RETURN 'ERROR...'` | Exit codes -> return messages |
| **Entire BTEQ script** | **Single stored procedure `SP_DAILY_LOAD_PIPELINE`** | Encapsulated as self-contained procedure, schedulable via Snowflake Tasks |

#### `bteq_extract_report.btq` -> `snowsql_extract_report.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `.EXPORT DATA FILE=/etl/exports/large_txn_report_YYYYMM.csv` | `COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/reports/large_txn_report_` | File export -> stage export |
| `.EXPORT REPORT FILE=/etl/exports/branch_performance_YYYYMM.rpt` | `COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/reports/branch_performance_` | Report export -> CSV stage export |
| `TRANSACTION_ID (BIGINT, FORMAT 'Z(18)9')` | `TRANSACTION_ID` | Inline FORMAT/type casts removed |
| `TRANSACTION_AMOUNT (FORMAT 'SZZZ,ZZZ,ZZ9.99')` | `TO_CHAR(TRANSACTION_AMOUNT, '999,999,999.99')` | FORMAT -> TO_CHAR |
| `EXEC BANKING_DW.AML_SCREENING(...)` | `CALL BANKING_DW.SP_AML_SCREENING(...)` via temp table | Macro execution -> procedure call, results captured in temp table for COPY INTO |
| `.LABEL NODATA; ... .QUIT 4;` | `IF (:v_txn_count = 0) THEN RETURN 'WARNING...'; END IF;` | GOTO/LABEL -> IF block |
| `TRIM(CURRENT_TIMESTAMP(0) (FORMAT 'YYYY-MM-DDBHH:MI:SS'))` | `TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS')` | Timestamp formatting |
| **Entire BTEQ script** | **Single stored procedure `SP_EXTRACT_MONTHLY_REPORTS`** | Schedulable via Snowflake Tasks |

---

### Data / Validation

#### `checksum_queries.sql`

| Original | Snowflake | Notes |
|---|---|---|
| `SEL` (all occurrences) | `SELECT` | Teradata shorthand |
| `SUM(HASHROW(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT))` | `SUM(HASH(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT))` | HASHROW -> HASH. **Important**: Hash values will differ between platforms. Validation should compare aggregates (counts, sums, min/max dates), not individual hash values. |
| `MIN(ONBOARDING_DATE) (FORMAT 'YYYY-MM-DD')` | `MIN(ONBOARDING_DATE)` | FORMAT removed |
| `SUM(TRANSACTION_AMOUNT) (DECIMAL(18,2))` | `CAST(SUM(TRANSACTION_AMOUNT) AS DECIMAL(18,2))` | Teradata inline cast -> standard CAST |
| `SUM(snap.CLOSING_BALANCE) (DECIMAL(18,2))` | `CAST(SUM(snap.CLOSING_BALANCE) AS DECIMAL(18,2))` | Same pattern |

---

## 3. Key Decision Register

### Decision 1: SET/MULTISET -> All Tables Allow Duplicates

**Context**: Teradata SET tables reject duplicate rows at insert time. Snowflake has no SET table concept.

**Decision**: Use standard `CREATE TABLE` (allows duplicates). Added `PRIMARY KEY` constraints on surrogate keys for documentation and optimizer hints.

**Risk**: If business logic relied on SET semantics to silently deduplicate, duplicate rows could appear. Mitigated by the fact that all dimension tables use surrogate keys (CUSTOMER_KEY, ACCOUNT_KEY) with AUTOINCREMENT, which are inherently unique.

### Decision 2: Primary Index -> Clustering Key Column Selection

**Context**: Teradata PI determines data distribution across AMPs. Snowflake clustering keys influence micro-partition pruning.

**Decision**:
- Dimension tables with date-based PPI: cluster by the date column (ONBOARDING_DATE, OPENING_DATE)
- Small dimension tables: no clustering (DIM_PRODUCT, DIM_BRANCH, DIM_DATE)
- FACT_TRANSACTION: cluster by (TRANSACTION_DATE, ACCOUNT_KEY) -- date first for range pruning
- FACT_MONTHLY_SNAPSHOT: cluster by (SNAPSHOT_DATE, ACCOUNT_KEY)

**Rationale**: Date columns provide the best pruning benefit for time-range queries, which are the most common access pattern in this warehouse.

### Decision 3: COMPRESS Removal

**Context**: Teradata COMPRESS optimizes storage for frequently repeated values.

**Decision**: Remove all COMPRESS clauses. Snowflake auto-compresses all data using proprietary algorithms.

**Risk**: None. Snowflake compression is typically equal or better than Teradata COMPRESS.

### Decision 4: NOT CASESPECIFIC Handling

**Context**: Teradata NOT CASESPECIFIC makes string comparisons case-insensitive. Snowflake is case-sensitive by default.

**Decision**: Removed NOT CASESPECIFIC from all column definitions. Added comments in DDL noting where case-insensitive behavior may be needed.

**Risk**: Business logic that relied on case-insensitive matching (e.g., customer name searches, email lookups) may break. **Action required**: Review application queries and add `COLLATE 'en-ci'` at column level or `UPPER()`/`LOWER()` in WHERE clauses where needed. Key areas:
- Customer name matching in AML screening
- Email address lookups
- Address comparisons in SCD2 change detection

### Decision 5: FORMAT Removal

**Context**: Teradata supports FORMAT on column definitions and inline in SELECT for display formatting.

**Decision**: Removed all FORMAT clauses. For views and reports, used `TO_CHAR()` where formatting is essential for output.

**Risk**: Reports or downstream applications that expected pre-formatted values will receive raw data. Application layer must handle formatting.

### Decision 6: BYTEINT -> SMALLINT

**Context**: Teradata BYTEINT stores 1-byte integers (-128 to 127). Snowflake has no BYTEINT.

**Decision**: Map to SMALLINT (2 bytes, -32768 to 32767). Snowflake internally optimizes storage.

**Risk**: None. SMALLINT covers the full BYTEINT range. No data loss possible.

### Decision 7: CSUM / MAVG -> Window Functions

**Context**: Teradata CSUM and MAVG are proprietary OLAP functions.

**Decision**:
- `CSUM(SUM(col), order_col)` -> `SUM(SUM(col)) OVER (PARTITION BY group_col ORDER BY order_col ROWS UNBOUNDED PRECEDING)`
- `MAVG(SUM(col), 3, order_col)` -> `AVG(SUM(col)) OVER (PARTITION BY group_col ORDER BY order_col ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)`

**Rationale**: Standard SQL window functions provide identical semantics. Added explicit PARTITION BY clauses for correctness (Teradata CSUM/MAVG implicitly partition by GROUP BY columns in certain contexts).

### Decision 8: MACRO -> Stored Procedure

**Context**: Teradata macros are parameterized SQL blocks that can contain multiple statements, each returning a result set. Snowflake has no macro concept.

**Decision**: Convert each macro to a Snowflake stored procedure using SQL scripting. Multi-statement macros that return multiple result sets are combined with UNION ALL into a single result set.

**Risk**: Callers expecting multiple result sets (e.g., 3 separate cursors from AML screening) will receive a single combined result set. The `PATTERN_TYPE` column differentiates the results. Column schemas are unified using generic VARCHAR columns (DETAIL_1 through DETAIL_N).

### Decision 9: BTEQ -> Stored Procedure + Snowflake Tasks

**Context**: BTEQ scripts orchestrate multi-step ETL pipelines with error handling (.IF ERRORCODE), branching (.GOTO/.LABEL), and export (.EXPORT).

**Decision**: Convert each BTEQ script to a self-contained Snowflake stored procedure. Include commented-out Snowflake Task definitions for scheduling.

**Rationale**: Stored procedures provide equivalent control flow (IF/ELSE, EXCEPTION), and Snowflake Tasks provide cron-like scheduling. This approach is fully native to Snowflake and does not require external orchestration tools.

### Decision 10: ACTIVITY_COUNT -> SQLROWCOUNT

**Context**: Teradata ACTIVITY_COUNT returns the number of rows affected by the last DML statement.

**Decision**: Use Snowflake's `SQLROWCOUNT` variable in SQL scripting, which provides identical functionality.

**Risk**: None. Direct functional equivalent.

### Decision 11: VOLATILE TABLE -> TEMPORARY TABLE

**Context**: Teradata volatile tables are session-scoped temporary tables with `ON COMMIT PRESERVE ROWS`.

**Decision**: Use Snowflake `CREATE TEMPORARY TABLE`. Temporary tables in Snowflake are session-scoped by default.

**Risk**: None. Functionally equivalent.

### Decision 12: HASHROW -> HASH

**Context**: Teradata HASHROW and Snowflake HASH use different hashing algorithms.

**Decision**: Replace HASHROW with HASH in all queries.

**Risk**: Hash values will differ between platforms. **Validation should compare aggregates (row counts, sum of amounts, min/max dates), not individual hash values.** The HASH_SUM in checksum queries is useful for detecting changes within Snowflake over time, not for cross-platform comparison.
