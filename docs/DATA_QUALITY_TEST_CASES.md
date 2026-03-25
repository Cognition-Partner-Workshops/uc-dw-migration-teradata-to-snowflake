# Data Quality & Data Testing Test Cases

## Teradata-to-Snowflake Data Migration Project — Retail Banking Analytics

This document defines comprehensive test cases for validating data quality and data integrity during and after the migration of the Banking Data Warehouse from Teradata to Snowflake. Test cases are organized by category and include **Positive**, **Negative**, and **Edge Condition** scenarios.

---

## Table of Contents

1. [Schema & DDL Validation](#1-schema--ddl-validation)
2. [Row Count Validation](#2-row-count-validation)
3. [Data Completeness & Column-Level Validation](#3-data-completeness--column-level-validation)
4. [Data Type & Precision Validation](#4-data-type--precision-validation)
5. [Referential Integrity Validation](#5-referential-integrity-validation)
6. [SCD Type 2 Logic Validation](#6-scd-type-2-logic-validation)
7. [Business Logic & Transformation Validation](#7-business-logic--transformation-validation)
8. [Teradata-to-Snowflake Feature Translation Validation](#8-teradata-to-snowflake-feature-translation-validation)
9. [Stored Procedure & Macro Migration Validation](#9-stored-procedure--macro-migration-validation)
10. [Aggregate & Checksum Reconciliation](#10-aggregate--checksum-reconciliation)
11. [View Migration Validation](#11-view-migration-validation)
12. [ETL Pipeline & BTEQ Script Migration Validation](#12-etl-pipeline--bteq-script-migration-validation)
13. [Data Quality — Post-Migration Ongoing Checks](#13-data-quality--post-migration-ongoing-checks)
14. [Performance & Operational Validation](#14-performance--operational-validation)

---

## 1. Schema & DDL Validation

### 1.1 Table Existence

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SCH-001 | Positive | Verify all 7 tables exist in Snowflake: `DIM_CUSTOMER`, `DIM_ACCOUNT`, `DIM_PRODUCT`, `DIM_BRANCH`, `DIM_DATE`, `FACT_TRANSACTION`, `FACT_MONTHLY_ACCOUNT_SNAPSHOT` | All 7 tables are created in the target schema |
| SCH-002 | Positive | Verify all 3 views exist in Snowflake: `VW_CUSTOMER_360`, `VW_REGULATORY_LARGE_TRANSACTIONS`, `VW_BRANCH_PERFORMANCE` | All 3 views are created and queryable |
| SCH-003 | Negative | Query a table that exists only in Teradata but was excluded from migration scope | Query returns an appropriate "object does not exist" error in Snowflake |
| SCH-004 | Negative | Verify staging/temp tables (`STG_CUSTOMER`, `STG_TRANSACTIONS`, `STG_TRANSACTION_ERRORS`, `VT_TXN_AGGREGATES`, `VT_BATCH`) are NOT present as permanent tables in Snowflake | Staging and volatile tables are not migrated as permanent objects |

### 1.2 Column Completeness

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SCH-005 | Positive | Compare column count for each table between Teradata source DDL and Snowflake target | Column counts match for all 7 tables: DIM_CUSTOMER (23 cols), DIM_ACCOUNT (21 cols), DIM_PRODUCT (17 cols), DIM_BRANCH (18 cols), DIM_DATE (24 cols), FACT_TRANSACTION (29 cols), FACT_MONTHLY_ACCOUNT_SNAPSHOT (22 cols) |
| SCH-006 | Positive | Verify all column names are preserved in Snowflake (case-insensitive comparison) | All column names match between source and target |
| SCH-007 | Negative | Insert a row into a Snowflake table with a column name that does not exist in the DDL | Query fails with "invalid identifier" error |
| SCH-008 | Edge | Verify columns with Teradata-specific clauses (`COMPRESS`, `NOT CASESPECIFIC`, `FORMAT`) were created successfully without those clauses | Columns exist with appropriate Snowflake-compatible data types; Teradata-specific clauses are removed |

### 1.3 Constraint Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SCH-009 | Positive | Verify NOT NULL constraints are preserved on required columns (e.g., `CUSTOMER_ID`, `ACCOUNT_ID`, `TRANSACTION_ID`, `TRANSACTION_DATE`, `TRANSACTION_AMOUNT`) | Inserting NULL into these columns is rejected |
| SCH-010 | Positive | Verify DEFAULT values are correctly translated (e.g., `COUNTRY_CODE DEFAULT 'NOR'`, `IS_ACTIVE DEFAULT 1`, `CURRENT_FLAG DEFAULT 'Y'`, `ACCOUNT_STATUS DEFAULT 'ACTIVE'`, `KYC_STATUS DEFAULT 'PENDING'`) | Inserting a row without specifying these columns uses the correct default |
| SCH-011 | Positive | Verify IDENTITY columns (`CUSTOMER_KEY`, `ACCOUNT_KEY`) are configured as `AUTOINCREMENT` or `IDENTITY` in Snowflake | Auto-generated surrogate keys increment correctly |
| SCH-012 | Edge | Verify `EFFECTIVE_TO DEFAULT TIMESTAMP '9999-12-31 23:59:59'` is preserved for SCD2 tables (`DIM_CUSTOMER`, `DIM_ACCOUNT`) | Default timestamp value is correctly set as `9999-12-31 23:59:59` |
| SCH-013 | Edge | Verify `EXCHANGE_RATE DEFAULT 1.000000` in `FACT_TRANSACTION` is preserved | Rows inserted without an exchange rate default to `1.000000` |

---

## 2. Row Count Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| RC-001 | Positive | Compare `SELECT COUNT(*)` for `DIM_CUSTOMER` between Teradata and Snowflake | Row count matches: 15 (per expected_row_counts.csv) |
| RC-002 | Positive | Compare `SELECT COUNT(*)` for `DIM_ACCOUNT` between Teradata and Snowflake | Row count matches: 20 |
| RC-003 | Positive | Compare `SELECT COUNT(*)` for `DIM_PRODUCT` between Teradata and Snowflake | Row count matches: 10 |
| RC-004 | Positive | Compare `SELECT COUNT(*)` for `DIM_BRANCH` between Teradata and Snowflake | Row count matches: 14 |
| RC-005 | Positive | Compare `SELECT COUNT(*)` for `DIM_DATE` between Teradata and Snowflake | Row count matches: 10,958 |
| RC-006 | Positive | Compare `SELECT COUNT(*)` for `FACT_TRANSACTION` between Teradata and Snowflake | Row count matches: ~50,000 |
| RC-007 | Positive | Compare `SELECT COUNT(*)` for `FACT_MONTHLY_ACCOUNT_SNAPSHOT` between Teradata and Snowflake | Row count matches: ~1,920 |
| RC-008 | Negative | Verify that duplicate rows in SET tables (`DIM_CUSTOMER`, `DIM_PRODUCT`, `DIM_BRANCH`, `DIM_DATE`) have not been introduced in Snowflake (since Snowflake does not enforce SET table semantics) | `SELECT COUNT(*) = SELECT COUNT(DISTINCT <primary_key>)` for each SET-origin table |
| RC-009 | Edge | Run row count on `FACT_TRANSACTION` partitioned by `TRANSACTION_DATE` month and compare Teradata vs Snowflake per-partition counts | Monthly partition counts match within tolerance |
| RC-010 | Edge | Compare row count for `DIM_CUSTOMER WHERE CURRENT_FLAG = 'Y'` vs `CURRENT_FLAG = 'N'` between source and target | Active vs expired record counts match |

---

## 3. Data Completeness & Column-Level Validation

### 3.1 DIM_CUSTOMER

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-001 | Positive | Verify all 15 `CUSTOMER_ID` values (1001-1015) from seed data are present in Snowflake | All 15 customer IDs are found |
| DC-002 | Positive | Verify `FIRST_NAME` and `LAST_NAME` values match source (e.g., CUSTOMER_ID=1001: 'Erik', 'Hansen') | All name values match exactly |
| DC-003 | Positive | Verify `GENDER` column only contains values from the COMPRESS list: 'M', 'F', 'O' | `SELECT DISTINCT GENDER` returns only valid values |
| DC-004 | Positive | Verify `CUSTOMER_SEGMENT` only contains: 'RETAIL', 'PREMIUM', 'PRIVATE', 'CORPORATE' | No invalid segment values exist |
| DC-005 | Positive | Verify `KYC_STATUS` only contains: 'VERIFIED', 'PENDING', 'REVIEW', 'EXPIRED' | All values are within the valid set |
| DC-006 | Positive | Verify `CREDIT_RATING` only contains: 'AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC' | All values are valid credit ratings |
| DC-007 | Negative | Verify no `CUSTOMER_ID` is NULL | `SELECT COUNT(*) WHERE CUSTOMER_ID IS NULL` returns 0 |
| DC-008 | Negative | Verify no `FIRST_NAME` or `LAST_NAME` is NULL | Count of NULL names is 0 |
| DC-009 | Negative | Verify `RISK_SCORE` is within valid range (0.00 to 100.00 based on DECIMAL(5,2)) | No risk scores outside 0-999.99; business range 0-100 expected |
| DC-010 | Edge | Verify `DATE_OF_BIRTH` for the oldest customer (CUSTOMER_ID=1011, DOB=1960-06-05) migrated correctly | Date value matches exactly |
| DC-011 | Edge | Verify `ADDRESS_LINE_2` with empty string values (COMPRESS '') and actual values ('Leilighet 3B', 'PB 201', 'Rom 405') migrated correctly | Empty strings are either NULL or empty string; non-empty values are preserved |
| DC-012 | Edge | Verify `ONBOARDING_DATE` for the newest customer (CUSTOMER_ID=1008, date=2024-01-08) is correctly migrated | Date value matches |
| DC-013 | Edge | Verify `MARITAL_STATUS` values ('S', 'M', 'D', 'W') are all present with correct distributions | All marital status values are present per source |

### 3.2 DIM_ACCOUNT

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-014 | Positive | Verify all 20 account records from seed data are present | All 20 ACCOUNT_ID values (ACCT-NO-100001 through ACCT-NO-100020) exist |
| DC-015 | Positive | Verify `ACCOUNT_TYPE` distribution matches source: CHECKING(9), SAVINGS(4), CREDIT_CARD(2), MORTGAGE(1), LOAN(1), INVESTMENT(1), DEPOSIT(1), and no other types exist | Type distribution matches |
| DC-016 | Positive | Verify `CURRENCY_CODE` values: 19 accounts in NOK, 1 in EUR (ACCT-NO-100012) | Currency distribution matches |
| DC-017 | Negative | Verify no `ACCOUNT_ID` is NULL and no `CUSTOMER_ID` is NULL | Zero NULL counts for both columns |
| DC-018 | Negative | Verify no `OPENING_DATE` is NULL (NOT NULL constraint) | Zero NULL opening dates |
| DC-019 | Edge | Verify `INTEREST_RATE` precision: e.g., 19.9000 for credit cards, 3.8500 for mortgage, 0.0100 for checking | DECIMAL(7,4) precision is maintained in Snowflake |
| DC-020 | Edge | Verify `CREDIT_LIMIT` of 0.00 (COMPRESS 0) and actual values (50000.00, 100000.00) migrated correctly | Zero and non-zero credit limits are correct |
| DC-021 | Edge | Verify `OVERDRAFT_LIMIT` values including high value (500000.00 for business checking ACCT-NO-100014) | Large decimal values are preserved |
| DC-022 | Edge | Verify the joint account flag: `IS_JOINT_ACCOUNT = 1` for ACCT-NO-100007 (mortgage), `0` for all others | Flag values are correct |

### 3.3 DIM_PRODUCT

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-023 | Positive | Verify all 10 products from seed data are present with correct `PRODUCT_CODE` values | All product codes match: CHK-STD, SAV-STD, SAV-PRM, SAV-EUR, CC-STD, MTG-FIX, INV-FND, CHK-BIZ, LON-BIZ, DEP-TRM |
| DC-024 | Positive | Verify `PRODUCT_CATEGORY` values match: DEPOSITS(6), CARDS(1), LENDING(2), INVESTMENT(1) | Category distribution is correct |
| DC-025 | Negative | Verify no `PRODUCT_NAME` is NULL | Zero NULL product names |
| DC-026 | Edge | Verify `MIN_BALANCE` of 50000.00 for DEP-TRM (term deposit) and 0.00 for checking products | Minimum balance values are preserved exactly |
| DC-027 | Edge | Verify `BASE_INTEREST_RATE` of 0.0000 for INV-FND (investment fund) migrated correctly (not NULL, but zero) | Zero interest rate is preserved as 0.0000, not NULL |

### 3.4 DIM_BRANCH

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-028 | Positive | Verify all 14 branches from seed data are present across 5 Norwegian regions: OSTLANDET(4), VESTLANDET(4), TRONDELAG(2), NORD-NORGE(2), SORLANDET(2) | Regional distribution matches |
| DC-029 | Positive | Verify `BRANCH_TYPE` values match: FULL_SERVICE(12), DIGITAL(1), KIOSK(1) | Type distribution matches |
| DC-030 | Negative | Verify no `BRANCH_NAME` is NULL | Zero NULL branch names |
| DC-031 | Edge | Verify `LATITUDE` and `LONGITUDE` precision for DECIMAL(10,7) — e.g., Oslo Sentrum: 59.9139000, 10.7522000 | 7-decimal-place precision is preserved |
| DC-032 | Edge | Verify `EMPLOYEE_COUNT` values including 0 (COMPRESS 0) and actual values (5 to 45) | All employee counts are correctly migrated |

### 3.5 DIM_DATE

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-033 | Positive | Verify `DATE_KEY` is in YYYYMMDD format and matches `CALENDAR_DATE` | All 10,958 rows have consistent DATE_KEY-to-CALENDAR_DATE mapping |
| DC-034 | Positive | Verify `DAY_OF_WEEK` range is 1-7 (Monday=1, Sunday=7) | All values are within 1-7 |
| DC-035 | Positive | Verify `IS_WEEKEND = 1` only when `DAY_OF_WEEK IN (6, 7)` | Weekend flag is logically consistent |
| DC-036 | Negative | Verify no gaps in date range from 2000-01-01 to 2029-12-31 | `COUNT(DISTINCT CALENDAR_DATE) = DATEDIFF(day, '2000-01-01', '2029-12-31') + 1` |
| DC-037 | Edge | Verify `IS_NORWEGIAN_HOLIDAY` flag for known dates (e.g., May 17 = Syttende Mai, Dec 25 = Christmas) | Holiday flags are set correctly for known Norwegian holidays |
| DC-038 | Edge | Verify `IS_BUSINESS_DAY = 0` when `IS_WEEKEND = 1 OR IS_NORWEGIAN_HOLIDAY = 1` | Business day flag is logically consistent |
| DC-039 | Edge | Verify leap year dates exist (e.g., 2000-02-29, 2004-02-29, 2024-02-29) and Feb 29 is absent in non-leap years | Leap year handling is correct |
| DC-040 | Edge | Verify `IS_MONTH_END`, `IS_QUARTER_END`, `IS_YEAR_END` flags are mutually consistent | Year-end dates are also quarter-end and month-end |
| DC-041 | Edge | Verify `PRIOR_DAY_DATE` and `NEXT_DAY_DATE` are exactly 1 day offset from `CALENDAR_DATE` | Date arithmetic is correct for all rows |
| DC-042 | Edge | Verify `SAME_DAY_PREV_YEAR` handles leap year correctly (e.g., 2024-02-29 previous year should be 2023-02-28 or NULL) | Prior-year lookup handles edge dates |

### 3.6 FACT_TRANSACTION

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-043 | Positive | Verify `TRANSACTION_TYPE` only contains valid values: 'DEBIT', 'CREDIT', 'TRANSFER', 'FEE', 'INTEREST', 'REVERSAL', 'ADJUSTMENT' | No invalid transaction types |
| DC-044 | Positive | Verify `CHANNEL` only contains valid values: 'BRANCH', 'ATM', 'ONLINE', 'MOBILE', 'POS', 'API' | No invalid channel values |
| DC-045 | Positive | Verify `TRANSACTION_CURRENCY` only contains valid values: 'NOK', 'EUR', 'USD', 'GBP', 'SEK', 'DKK' | No invalid currency codes |
| DC-046 | Negative | Verify `TRANSACTION_AMOUNT` is never NULL (NOT NULL constraint) | Zero NULL transaction amounts |
| DC-047 | Negative | Verify no `TRANSACTION_ID` duplicates exist | `COUNT(DISTINCT TRANSACTION_ID) = COUNT(*)` |
| DC-048 | Negative | Verify `TRANSACTION_DATE` is not in the future (relative to the data load date) | No transaction dates beyond the expected data cutoff |
| DC-049 | Edge | Verify `EXCHANGE_RATE` values: 1.000000 for NOK transactions, variable for non-NOK | NOK transactions have exchange rate of 1.0; non-NOK have rate > 0 |
| DC-050 | Edge | Verify `IS_INTERNATIONAL = 1` when `TRANSACTION_CURRENCY <> 'NOK'` and `IS_INTERNATIONAL = 0` when `TRANSACTION_CURRENCY = 'NOK'` | International flag aligns with currency code |
| DC-051 | Edge | Verify `TRANSACTION_TS` with microsecond precision (TIMESTAMP(6)) is preserved | Timestamp precision is maintained |
| DC-052 | Edge | Verify `MERCHANT_CATEGORY` codes are 4-character MCC codes (VARCHAR(4)) | MCC code length is correct |
| DC-053 | Edge | Verify `POSTING_DATE` and `VALUE_DATE` can differ from `TRANSACTION_DATE` (common in banking) | Dates can differ; no artificial constraint |

### 3.7 FACT_MONTHLY_ACCOUNT_SNAPSHOT

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DC-054 | Positive | Verify `SNAPSHOT_MONTH_KEY` is in YYYYMM format and is consistent with `SNAPSHOT_DATE` | Month key matches the year-month of snapshot date |
| DC-055 | Positive | Verify `OPENING_BALANCE` and `CLOSING_BALANCE` are NOT NULL | Zero NULL balance values |
| DC-056 | Negative | Verify no duplicate rows for the same `(ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)` combination | Composite uniqueness is maintained |
| DC-057 | Edge | Verify `CLOSING_BALANCE` can be negative (overdraft accounts) | Negative balances are permitted and migrated correctly |
| DC-058 | Edge | Verify `DAYS_IN_OVERDRAFT` and `DAYS_DORMANT` values are non-negative and within the month's day count (0-31) | Values are logically valid |
| DC-059 | Edge | Verify `MINIMUM_BALANCE <= AVERAGE_BALANCE <= MAXIMUM_BALANCE` for each snapshot row | Balance ordering is logically consistent |

---

## 4. Data Type & Precision Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DT-001 | Positive | Verify `INTEGER` columns (e.g., `CUSTOMER_ID`, `BRANCH_ID`, `PRODUCT_ID`) are `NUMBER(38,0)` or `INTEGER` in Snowflake | Data types map correctly |
| DT-002 | Positive | Verify `BIGINT` columns (e.g., `CUSTOMER_KEY`, `ACCOUNT_KEY`, `TRANSACTION_ID`) are `NUMBER(38,0)` or `BIGINT` in Snowflake | Data types map correctly |
| DT-003 | Positive | Verify `DECIMAL(15,2)` columns (e.g., `TRANSACTION_AMOUNT`, `CLOSING_BALANCE`, `CREDIT_LIMIT`) maintain 2-digit decimal precision | Sample: 50000.00 remains 50000.00, not 50000 or 50000.0 |
| DT-004 | Positive | Verify `DECIMAL(7,4)` columns (e.g., `INTEREST_RATE`) maintain 4-digit decimal precision | Sample: 19.9000 remains 19.9000 |
| DT-005 | Positive | Verify `DECIMAL(12,6)` columns (e.g., `EXCHANGE_RATE`) maintain 6-digit decimal precision | Sample: 1.000000 remains 1.000000 |
| DT-006 | Positive | Verify `DECIMAL(10,7)` columns (e.g., `LATITUDE`, `LONGITUDE`) maintain 7-digit decimal precision | Sample: 59.9139000 remains 59.9139000 |
| DT-007 | Positive | Verify `DATE` columns (e.g., `ONBOARDING_DATE`, `TRANSACTION_DATE`) are `DATE` type in Snowflake | Date values do not include time components |
| DT-008 | Positive | Verify `TIMESTAMP(0)` columns (e.g., `EFFECTIVE_FROM`, `ETL_INSERT_TS`) are `TIMESTAMP_NTZ(0)` or similar in Snowflake | Second-level precision is preserved |
| DT-009 | Positive | Verify `TIMESTAMP(6)` column (`TRANSACTION_TS`) preserves microsecond precision | Microsecond-level precision is preserved |
| DT-010 | Positive | Verify `CHAR(n)` columns (e.g., `GENDER CHAR(1)`, `COUNTRY_CODE CHAR(3)`, `QUARTER_NAME CHAR(2)`) are fixed-width or VARCHAR in Snowflake | Character data is preserved correctly |
| DT-011 | Positive | Verify `VARCHAR(n)` max lengths are preserved (e.g., `DESCRIPTION_TEXT VARCHAR(200)`, `EMAIL_ADDRESS VARCHAR(100)`) | Maximum length constraints are correctly mapped |
| DT-012 | Negative | Attempt to insert a `DECIMAL(15,2)` value with more than 2 decimal places (e.g., 100.999) | Value is either rounded or rejected per Snowflake behavior |
| DT-013 | Negative | Attempt to insert a `VARCHAR(20)` value exceeding 20 characters | Insert is rejected or value is truncated per Snowflake settings |
| DT-014 | Edge | Verify `BYTEINT` columns (e.g., `IS_ACTIVE`, `IS_WEEKEND`, `DAY_OF_WEEK`) are mapped to `TINYINT` or `NUMBER` in Snowflake | BYTEINT values (0/1 flags, 1-7 ranges) are preserved |
| DT-015 | Edge | Verify `SMALLINT` columns (e.g., `EMPLOYEE_COUNT`, `DAYS_IN_OVERDRAFT`, `DAY_OF_YEAR`) are correctly typed | SMALLINT range values are preserved |
| DT-016 | Edge | Verify `TIME(0)` column (`TRANSACTION_TIME`) is preserved in Snowflake | Time values (hours, minutes, seconds) are intact |

---

## 5. Referential Integrity Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| RI-001 | Positive | Verify every `CUSTOMER_KEY` in `FACT_TRANSACTION` exists in `DIM_CUSTOMER` | Zero orphaned transactions by customer key |
| RI-002 | Positive | Verify every `ACCOUNT_KEY` in `FACT_TRANSACTION` exists in `DIM_ACCOUNT` | Zero orphaned transactions by account key |
| RI-003 | Positive | Verify every `PRODUCT_ID` in `FACT_TRANSACTION` exists in `DIM_PRODUCT` | Zero orphaned transactions by product |
| RI-004 | Positive | Verify every `DATE_KEY` in `FACT_TRANSACTION` exists in `DIM_DATE` | Zero orphaned transactions by date |
| RI-005 | Positive | Verify every `ACCOUNT_KEY` in `FACT_MONTHLY_ACCOUNT_SNAPSHOT` exists in `DIM_ACCOUNT` | Zero orphaned snapshots by account |
| RI-006 | Positive | Verify every `CUSTOMER_KEY` in `FACT_MONTHLY_ACCOUNT_SNAPSHOT` exists in `DIM_CUSTOMER` | Zero orphaned snapshots by customer |
| RI-007 | Positive | Verify every `CUSTOMER_ID` in `DIM_ACCOUNT` exists in `DIM_CUSTOMER` | All accounts reference valid customers |
| RI-008 | Positive | Verify every `BRANCH_ID` (non-NULL) in `DIM_ACCOUNT` exists in `DIM_BRANCH` | All account branches reference valid branches |
| RI-009 | Positive | Verify every `PRODUCT_ID` in `DIM_ACCOUNT` exists in `DIM_PRODUCT` | All account products reference valid products |
| RI-010 | Negative | Count orphaned `BRANCH_ID` values in `FACT_TRANSACTION` that do not exist in `DIM_BRANCH` | Zero orphaned records (or document expected NULL BRANCH_ID rows for digital channels) |
| RI-011 | Negative | Run `checksum_queries.sql` cross-table referential integrity checks (Section 5) on Snowflake | `ORPHAN_TXN_ACCOUNT`, `ORPHAN_TXN_CUSTOMER`, `ORPHAN_SNAP_ACCOUNT` all return 0 |
| RI-012 | Edge | Verify `BRANCH_ID` in `FACT_TRANSACTION` can be NULL (for digital/API transactions) without violating integrity | NULL BRANCH_ID is allowed and does not create false orphan counts |
| RI-013 | Edge | Verify `RELATIONSHIP_MGR_ID` in `DIM_ACCOUNT` with value 0 (COMPRESS 0) or NULL does not create false integrity violations | Zero/NULL manager IDs are handled gracefully |

---

## 6. SCD Type 2 Logic Validation

### 6.1 DIM_CUSTOMER SCD2

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SCD-001 | Positive | Verify each `CUSTOMER_ID` has exactly one row with `CURRENT_FLAG = 'Y'` | `COUNT(*) WHERE CURRENT_FLAG = 'Y' GROUP BY CUSTOMER_ID` all return 1 |
| SCD-002 | Positive | Verify `EFFECTIVE_TO = '9999-12-31 23:59:59'` for all rows with `CURRENT_FLAG = 'Y'` | All current records have the far-future end date |
| SCD-003 | Positive | Verify `EFFECTIVE_FROM < EFFECTIVE_TO` for all rows | No invalid date ranges |
| SCD-004 | Positive | Verify expired rows (`CURRENT_FLAG = 'N'`) have `EFFECTIVE_TO < '9999-12-31 23:59:59'` | All expired rows have a real end timestamp |
| SCD-005 | Negative | Verify no `CUSTOMER_ID` has zero rows with `CURRENT_FLAG = 'Y'` (every customer must have a current version) | All customer IDs have at least one current record |
| SCD-006 | Negative | Verify no `CUSTOMER_ID` has more than one row with `CURRENT_FLAG = 'Y'` (no duplicate current records) | Max 1 current record per customer |
| SCD-007 | Edge | Verify SCD2 tracked fields from `SP_CUSTOMER_SCD2` trigger versioning: `CUSTOMER_SEGMENT`, `RISK_SCORE`, `CREDIT_RATING`, `KYC_STATUS`, `ADDRESS_LINE_1`, `CITY`, `STATE_PROVINCE`, `POSTAL_CODE`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `MARITAL_STATUS` | Changes to these fields create new versions in Snowflake |
| SCD-008 | Edge | Verify non-SCD fields (`FIRST_NAME`, `LAST_NAME`, `DATE_OF_BIRTH`, `GENDER`) do NOT trigger new versions | Changes to these fields do not create new rows |
| SCD-009 | Edge | Verify `CUSTOMER_KEY` (surrogate key) is unique across all versions of all customers | `COUNT(DISTINCT CUSTOMER_KEY) = COUNT(*)` |
| SCD-010 | Edge | Verify historical timeline has no gaps: for each CUSTOMER_ID, the `EFFECTIVE_TO` of version N equals the `EFFECTIVE_FROM` of version N+1 | SCD2 timeline is continuous |

### 6.2 DIM_ACCOUNT SCD2

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SCD-011 | Positive | Verify each `ACCOUNT_ID` has exactly one row with `CURRENT_FLAG = 'Y'` | One current version per account |
| SCD-012 | Positive | Verify `EFFECTIVE_FROM < EFFECTIVE_TO` for all account rows | No invalid date ranges |
| SCD-013 | Negative | Verify no `ACCOUNT_ID` has duplicate current records | Max 1 current record per account |
| SCD-014 | Edge | Verify `CLOSING_DATE` is NULL for ACTIVE accounts and populated for CLOSED accounts | Status-date consistency is maintained |
| SCD-015 | Edge | Verify `ACCOUNT_KEY` (surrogate key) is unique across all versions | Surrogate key uniqueness holds |

---

## 7. Business Logic & Transformation Validation

### 7.1 Transaction Amount & Currency Conversion

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| BL-001 | Positive | Verify `BASE_CURRENCY_AMOUNT = TRANSACTION_AMOUNT` when `TRANSACTION_CURRENCY = 'NOK'` | NOK transactions have equal amounts |
| BL-002 | Positive | Verify `BASE_CURRENCY_AMOUNT = TRANSACTION_AMOUNT * EXCHANGE_RATE` for non-NOK transactions | Currency conversion formula is correct within rounding tolerance |
| BL-003 | Negative | Verify no transactions have `EXCHANGE_RATE = 0` (would cause zero base amount) | Zero exchange rates do not exist (ZEROIFNULL should prevent this) |
| BL-004 | Negative | Verify no transactions have NULL `BASE_CURRENCY_AMOUNT` when `TRANSACTION_CURRENCY <> 'NOK'` | All foreign currency transactions have a converted amount |
| BL-005 | Edge | Verify `ZEROIFNULL(fx.EXCHANGE_RATE)` behavior: when no exchange rate exists, the rate defaults to 0, making `BASE_CURRENCY_AMOUNT = 0` | Edge case is documented; investigate if this is desired behavior |
| BL-006 | Edge | Verify transaction amount sign conventions: DEBITs and FEEs can be negative, CREDITs are positive | Sign conventions are consistent |

### 7.2 Monthly Snapshot Calculations

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| BL-007 | Positive | Verify `CLOSING_BALANCE = OPENING_BALANCE + TOTAL_CREDITS - TOTAL_DEBITS` for each snapshot row | Balance formula is mathematically correct |
| BL-008 | Positive | Verify `OPENING_BALANCE` for month M equals `CLOSING_BALANCE` of month M-1 for the same account | Balance continuity across months |
| BL-009 | Positive | Verify `DEBIT_COUNT + CREDIT_COUNT` matches the actual transaction count for the account in that month | Transaction counts reconcile with `FACT_TRANSACTION` |
| BL-010 | Negative | Verify no snapshots exist for accounts with `ACCOUNT_STATUS = 'CLOSED'` or `'FROZEN'` (only ACTIVE/DORMANT are included per SP_MONTHLY_SNAPSHOT logic) | Excluded statuses are correctly filtered |
| BL-011 | Edge | Verify `DAYS_DORMANT = (period_end - period_start + 1)` when there are no transactions for an account in a month | Dormancy calculation is correct for inactive-but-open accounts |
| BL-012 | Edge | Verify `DAYS_IN_OVERDRAFT` counts days where `RUNNING_BALANCE < 0` | Overdraft day count matches negative-balance transaction days |
| BL-013 | Edge | Verify `MINIMUM_BALANCE <= AVERAGE_BALANCE <= MAXIMUM_BALANCE` | Statistical consistency holds |

### 7.3 Regulatory Reporting Thresholds

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| BL-014 | Positive | Verify `VW_REGULATORY_LARGE_TRANSACTIONS` includes transactions where `BASE_CURRENCY_AMOUNT >= 100000` with category `THRESHOLD_EXCEEDED` | Domestic threshold is correctly applied |
| BL-015 | Positive | Verify international transactions with `BASE_CURRENCY_AMOUNT >= 25000` are categorized as `INTL_THRESHOLD` | International threshold is correctly applied |
| BL-016 | Positive | Verify flagged transactions (`IS_FLAGGED = 1`) are categorized as `FLAGGED_SUSPICIOUS` | Flagged transactions appear in regulatory view |
| BL-017 | Negative | Verify transactions below all thresholds and not flagged are excluded from the view | Sub-threshold, non-flagged transactions are not in the view |
| BL-018 | Edge | Verify boundary: transaction with `BASE_CURRENCY_AMOUNT = 99999.99` (just below 100000 threshold) is NOT in `THRESHOLD_EXCEEDED` | Boundary is correctly exclusive at 99999.99 |
| BL-019 | Edge | Verify boundary: transaction with `BASE_CURRENCY_AMOUNT = 100000.00` (exactly at threshold) IS in `THRESHOLD_EXCEEDED` | Boundary is correctly inclusive at 100000.00 |
| BL-020 | Edge | Verify international boundary: `IS_INTERNATIONAL = 1 AND BASE_CURRENCY_AMOUNT = 24999.99` is NOT categorized as `INTL_THRESHOLD` | International boundary is correctly exclusive |
| BL-021 | Edge | Verify international boundary: `IS_INTERNATIONAL = 1 AND BASE_CURRENCY_AMOUNT = 25000.00` IS categorized as `INTL_THRESHOLD` | International boundary is correctly inclusive |

### 7.4 AML Screening Logic

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| BL-022 | Positive | Verify STRUCTURING pattern detects customers with >= 3 transactions between 80%-100% of threshold in the lookback period | Pattern detection works correctly |
| BL-023 | Positive | Verify RAPID_MOVEMENT pattern detects large credits followed by debits within 3 days | Temporal proximity detection works |
| BL-024 | Positive | Verify NEW_CUSTOMER_INTL pattern detects customers onboarded within 90 days with high international activity | New-customer screening works |
| BL-025 | Negative | Verify customers with < 3 structuring transactions are NOT flagged | Below-threshold pattern count is excluded |
| BL-026 | Edge | Verify STRUCTURING detection at boundary: 3 transactions at exactly 80% of threshold (`amount_threshold * 0.8`) | Lower boundary is correctly inclusive |
| BL-027 | Edge | Verify RAPID_MOVEMENT: debit on day 4 after credit (beyond 3-day window) is NOT detected | Temporal window boundary is correct |

---

## 8. Teradata-to-Snowflake Feature Translation Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| TF-001 | Positive | Verify `SEL` shorthand is converted to `SELECT` in all migrated views and procedures | All queries use standard `SELECT` syntax |
| TF-002 | Positive | Verify `QUALIFY ROW_NUMBER()` works correctly in Snowflake (natively supported) | QUALIFY clause produces identical results |
| TF-003 | Positive | Verify `ZEROIFNULL()` functions produce identical results in Snowflake | NULL-to-zero conversion matches Teradata behavior |
| TF-004 | Positive | Verify `NULLIFZERO()` functions produce identical results in Snowflake | Zero-to-NULL conversion matches Teradata behavior |
| TF-005 | Positive | Verify `ADD_MONTHS()` function produces identical results in Snowflake | Date arithmetic matches |
| TF-006 | Positive | Verify `EXTRACT(YEAR/MONTH FROM ...)` works identically in Snowflake | Date part extraction matches |
| TF-007 | Positive | Verify `MERGE INTO` statements in stored procedures work in Snowflake | MERGE semantics (WHEN MATCHED / WHEN NOT MATCHED) produce identical results |
| TF-008 | Negative | Verify `HASHROW()` is replaced with `HASH()` in Snowflake and produces consistent (though not identical) hash values | Hash function replacement is implemented; hash values are internally consistent |
| TF-009 | Negative | Verify `CSUM()` in `VW_BRANCH_PERFORMANCE` is replaced with `SUM() OVER (ORDER BY ...)` window function | Cumulative sum results match Teradata output |
| TF-010 | Negative | Verify `MAVG()` in `VW_BRANCH_PERFORMANCE` is replaced with `AVG() OVER (ORDER BY ... ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` | 3-month moving average results match |
| TF-011 | Negative | Verify `LOCKING ROW FOR ACCESS` is removed from all views (no Snowflake equivalent) | Views compile without locking clauses |
| TF-012 | Negative | Verify `FORMAT` specifications on columns (e.g., `(FORMAT 'YYYY-MM-DD')`, `(FORMAT 'ZZZ,ZZZ,ZZ9.99')`) are removed or converted to `TO_CHAR()` | No Teradata FORMAT syntax remains |
| TF-013 | Edge | Verify `NOT CASESPECIFIC` columns behave correctly in Snowflake — Snowflake is case-sensitive by default, so `COLLATE 'en-ci'` or `UPPER()`/`LOWER()` must be used where case-insensitive matching was expected | Case-insensitive comparisons produce equivalent results (e.g., 'oslo' matches 'Oslo' if NOT CASESPECIFIC was used) |
| TF-014 | Edge | Verify `VOLATILE TABLE` in `SP_MONTHLY_SNAPSHOT` is converted to `CREATE TEMPORARY TABLE` in Snowflake | Temporary table is created, used, and dropped within the procedure |
| TF-015 | Edge | Verify `ACTIVITY_COUNT` is replaced with `SQLROWCOUNT` or equivalent result scanning in Snowflake procedures | Row count tracking works correctly |
| TF-016 | Edge | Verify `SAMPLE 1000` in `CUSTOMER_TXN_HISTORY` macro is converted to `SAMPLE 1000 ROWS` or `LIMIT 1000` | Row limiting produces a 1000-row maximum result set |
| TF-017 | Edge | Verify Teradata `MACRO` objects are converted to Snowflake stored procedures (since Snowflake has no macro support) | All 3 macros are functional as stored procedures |
| TF-018 | Edge | Verify `COMPRESS` values from Teradata are removed and do not affect data storage or retrieval in Snowflake | Compression is handled automatically by Snowflake |
| TF-019 | Edge | Verify `SET TABLE` semantics — duplicate prevention that was automatic in Teradata must be handled via constraints or ETL logic in Snowflake | Duplicate-free data is maintained for dimension tables |

---

## 9. Stored Procedure & Macro Migration Validation

### 9.1 SP_CUSTOMER_SCD2

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SP-001 | Positive | Execute the migrated SCD2 procedure with a new customer in staging — verify a new row is inserted with `CURRENT_FLAG = 'Y'` | New customer row is created with correct defaults |
| SP-002 | Positive | Execute the SCD2 procedure with a changed `CUSTOMER_SEGMENT` in staging — verify the old row is expired (`CURRENT_FLAG = 'N'`, `EFFECTIVE_TO` set) and a new row is inserted | SCD2 versioning works correctly |
| SP-003 | Positive | Verify `p_new_rows` and `p_changed` output parameters return correct counts | Row counts match actual inserts/updates |
| SP-004 | Negative | Execute the SCD2 procedure with staging data that has no changes from the current dimension — verify no new rows are created | Zero new versions when data is unchanged |
| SP-005 | Negative | Execute the SCD2 procedure with an empty staging table — verify no errors and zero counts | Procedure handles empty input gracefully |
| SP-006 | Edge | Execute the SCD2 procedure with NULL values in nullable SCD-tracked fields (`PHONE_NUMBER`, `EMAIL_ADDRESS`) — verify `COALESCE(..., '')` comparison logic works | NULL-to-empty-string comparison prevents false change detection |
| SP-007 | Edge | Execute the SCD2 procedure with a customer that has multiple expired versions — verify `ONBOARDING_DATE` is carried from the earliest version | Original onboarding date is preserved across versions |

### 9.2 SP_LOAD_DAILY_TRANSACTIONS

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SP-008 | Positive | Execute with valid staging data — verify rows are inserted into `FACT_TRANSACTION` with correct surrogate key lookups (`ACCOUNT_KEY`, `CUSTOMER_KEY`) | Dimension key resolution works correctly |
| SP-009 | Positive | Verify `DATE_KEY` is correctly calculated as `CAST(TRANSACTION_DATE AS INTEGER)` in YYYYMMDD format | Date key derivation is correct |
| SP-010 | Positive | Verify currency conversion: non-NOK transactions have `BASE_CURRENCY_AMOUNT = AMOUNT * EXCHANGE_RATE` | FX conversion logic works |
| SP-011 | Negative | Execute with staging rows referencing an `ACCOUNT_ID` that does not exist in `DIM_ACCOUNT` — verify rows are routed to `STG_TRANSACTION_ERRORS` with `ERROR_REASON = 'INVALID_ACCOUNT'` | Error routing works correctly |
| SP-012 | Negative | Verify `p_rows_rejected` count matches the number of error-routed rows | Rejection count is accurate |
| SP-013 | Negative | Trigger the `EXIT HANDLER FOR SQLEXCEPTION` — verify error is logged to `ETL_LOG` with `LOG_LEVEL = 'ERROR'` | Exception handling and logging work |
| SP-014 | Edge | Execute with staging data for a currency where no exchange rate exists in `DIM_EXCHANGE_RATES` — verify `ZEROIFNULL(fx.EXCHANGE_RATE)` returns 0 | Missing exchange rate defaults to zero |
| SP-015 | Edge | Verify `IS_INTERNATIONAL` flag is set to 1 when `CURRENCY_CODE <> 'NOK'` and 0 otherwise | International flag derivation is correct |

### 9.3 SP_MONTHLY_SNAPSHOT

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SP-016 | Positive | Execute for a month with transaction activity — verify snapshot rows are created with correct aggregates | Aggregated balances match underlying transactions |
| SP-017 | Positive | Verify MERGE logic: re-running for the same month updates existing rows rather than duplicating | Idempotent execution produces correct results |
| SP-018 | Negative | Execute for a future month with no transactions — verify accounts with ACTIVE/DORMANT status still get snapshot rows with zero activity | Dormant snapshots are created with zero totals |
| SP-019 | Edge | Verify `OPENING_BALANCE` for the first-ever snapshot month (no prior month exists) defaults to 0 via `ZEROIFNULL(prev.CLOSING_BALANCE)` | First month opening balance is zero |
| SP-020 | Edge | Verify volatile/temporary table `VT_TXN_AGGREGATES` is created and dropped within the procedure | No persistent temp tables remain after execution |

### 9.4 Macro Migrations

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| SP-021 | Positive | Execute migrated `AML_SCREENING` with default parameters — verify all 3 patterns (STRUCTURING, RAPID_MOVEMENT, NEW_CUSTOMER_INTL) return results | All screening patterns are functional |
| SP-022 | Positive | Execute migrated `CUSTOMER_TXN_HISTORY` with a valid `cust_id` — verify transaction history is returned | Customer history retrieval works |
| SP-023 | Positive | Execute migrated `DAILY_BALANCE_CHECK` — verify BALANCE_SUMMARY and NEGATIVE_BALANCE_ALERT result sets are returned | Balance checking is functional |
| SP-024 | Negative | Execute `CUSTOMER_TXN_HISTORY` with a non-existent `cust_id` — verify empty result set (no error) | Graceful handling of missing customer |
| SP-025 | Edge | Execute `AML_SCREENING` with `amount_threshold = 0` — verify behavior with zero threshold | Edge threshold is handled without errors |
| SP-026 | Edge | Execute `DAILY_BALANCE_CHECK` for a non-business day (weekend) — verify behavior | Query runs without errors even if no transactions exist for the date |

---

## 10. Aggregate & Checksum Reconciliation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| AGG-001 | Positive | Run `checksum_queries.sql` Section 1 (row count per table) on both Teradata and Snowflake — compare results | All 7 table row counts match |
| AGG-002 | Positive | Run `checksum_queries.sql` Section 2 (DIM_CUSTOMER column checksum) — compare `DISTINCT_CUSTOMERS`, `MIN_ONBOARD_DATE`, `MAX_ONBOARD_DATE`, `ACTIVE_COUNT` | All aggregate values match |
| AGG-003 | Positive | Run `checksum_queries.sql` Section 3 (FACT_TRANSACTION monthly aggregates) — compare `TXN_COUNT`, `TOTAL_AMOUNT`, `TOTAL_BASE_AMOUNT`, `DISTINCT_ACCOUNTS`, `DEBIT_COUNT`, `CREDIT_COUNT`, `INTL_COUNT` per year-month | All monthly aggregates match within tolerance |
| AGG-004 | Positive | Run `checksum_queries.sql` Section 4 (monthly balance reconciliation) — compare `TOTAL_DEPOSITS`, `TOTAL_DEBITS`, `TOTAL_CREDITS`, `TOTAL_INTEREST`, `TOTAL_FEES`, `ACCOUNT_COUNT` per month | All monthly balance aggregates match |
| AGG-005 | Positive | Run `checksum_queries.sql` Section 5 (referential integrity) — verify all orphan counts are 0 | Zero orphaned records across all checks |
| AGG-006 | Negative | Intentionally insert an orphan transaction in Snowflake (with a non-existent ACCOUNT_KEY) and verify the referential integrity check catches it | Orphan count increments by 1 |
| AGG-007 | Edge | Compare `SUM(TRANSACTION_AMOUNT)` with `DECIMAL(18,2)` precision between Teradata and Snowflake to detect floating-point drift | Sums match to the penny (within 0.01 tolerance for very large aggregates) |
| AGG-008 | Edge | Verify `HASH_SUM` in checksum query Section 2 — note that `HASHROW()` and `HASH()` produce different values, so use alternative reconciliation (e.g., column-level SUM/MIN/MAX) | Hash values are not directly comparable; alternative checksums are used |

---

## 11. View Migration Validation

### 11.1 VW_CUSTOMER_360

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| VW-001 | Positive | Query `VW_CUSTOMER_360` in Snowflake — verify `FULL_NAME` concatenation (`FIRST_NAME || ' ' || LAST_NAME`) works | Full name is correctly constructed |
| VW-002 | Positive | Verify `TENURE_YEARS` calculation: `(CURRENT_DATE - ONBOARDING_DATE) / 365.25` matches expected values | Tenure calculation produces reasonable values |
| VW-003 | Positive | Verify `TOTAL_ACCOUNTS` and `ACTIVE_ACCOUNTS` counts match `DIM_ACCOUNT` data for each customer | Account counts are accurate |
| VW-004 | Negative | Verify only customers with `CURRENT_FLAG = 'Y' AND IS_ACTIVE = 1` appear in the view | Expired and inactive customers are excluded |
| VW-005 | Edge | Verify `ZEROIFNULL()` returns 0 (not NULL) for customers with no accounts or no recent transactions | Zero-filling works correctly for customers without activity |
| VW-006 | Edge | Verify `TXN_COUNT_LAST_90_DAYS` and `TXN_AMOUNT_LAST_90_DAYS` use a rolling 90-day window from CURRENT_DATE | Rolling window calculation is correct |

### 11.2 VW_REGULATORY_LARGE_TRANSACTIONS

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| VW-007 | Positive | Query the view and verify `REPORTING_CATEGORY` values match the CASE logic | Categories are correctly assigned |
| VW-008 | Positive | Verify `QUALIFY ROW_NUMBER() OVER (PARTITION BY TRANSACTION_ID ORDER BY ETL_BATCH_ID DESC) = 1` deduplicates correctly | Only the latest batch version of each transaction appears |
| VW-009 | Negative | Verify `HASHROW()` replacement with `HASH()` produces consistent `ROW_HASH` values within Snowflake | Hash function is internally consistent |
| VW-010 | Edge | Verify a transaction that meets both domestic (>=100000) and international (>=25000) thresholds is categorized as `THRESHOLD_EXCEEDED` (the first CASE WHEN match) | CASE priority is correct |

### 11.3 VW_BRANCH_PERFORMANCE

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| VW-011 | Positive | Verify `ACCOUNTS_SERVICED` and `CUSTOMERS_SERVICED` use `COUNT(DISTINCT ...)` correctly | Distinct counts match underlying data |
| VW-012 | Positive | Verify `REGION_DEPOSIT_RANK` correctly ranks branches within each region by total closing balance | Rankings are correct and consistent |
| VW-013 | Positive | Verify `CUMULATIVE_FEES_YTD` (replacement for `CSUM()`) produces correct cumulative sums | Cumulative totals are mathematically correct |
| VW-014 | Positive | Verify `MOVING_AVG_VOLUME_3M` (replacement for `MAVG()`) produces correct 3-month moving averages | Moving averages match manual calculations |
| VW-015 | Negative | Verify view excludes branches where `IS_ACTIVE = 0` | Inactive branches are filtered out |
| VW-016 | Negative | Verify view only includes data from the last 24 months (`ADD_MONTHS(CURRENT_DATE, -24)`) | Older data is excluded |
| VW-017 | Edge | Verify `PCT_OF_REGION_DEPOSITS` uses `NULLIFZERO()` to avoid division by zero when a region has no deposits | No division-by-zero errors |
| VW-018 | Edge | Verify `MONTH_LABEL` formatting: month name concatenated with year (e.g., 'January 2025') handles `TRIM()` of the year correctly | Month label is cleanly formatted without extra spaces |

---

## 12. ETL Pipeline & BTEQ Script Migration Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| ETL-001 | Positive | Verify the daily load orchestration (BTEQ replacement) executes steps in correct order: staging check -> batch ID generation -> SCD2 update -> transaction load -> balance check -> reconciliation report -> batch completion | All pipeline steps execute in sequence |
| ETL-002 | Positive | Verify `ETL_BATCH_CONTROL` table records batch completions with `BATCH_STATUS = 'COMPLETED'`, correct timestamps | Batch audit trail is maintained |
| ETL-003 | Positive | Verify reconciliation report shows `STAGED_ROWS = LOADED_ROWS + ERROR_ROWS` | Row reconciliation balances |
| ETL-004 | Negative | Simulate empty staging data — verify pipeline exits gracefully with a warning (equivalent of `.QUIT 4`) | No-data condition is handled without error |
| ETL-005 | Negative | Simulate a SQL error mid-pipeline — verify `ETL_BATCH_CONTROL` records `BATCH_STATUS = 'FAILED'` and error is logged | Error handling and audit logging work correctly |
| ETL-006 | Edge | Verify `.EXPORT` functionality is replaced with `COPY INTO @stage` or SnowSQL spool for report generation | Reports are exported in the expected format |
| ETL-007 | Edge | Verify `.LOGON` / `.QUIT` connection handling is replaced with SnowSQL connection management | Connection lifecycle is properly managed |
| ETL-008 | Edge | Verify `ETL_LOG` entries include procedure name, batch ID, log level (INFO/ERROR), and timestamps | Logging granularity is maintained post-migration |

---

## 13. Data Quality — Post-Migration Ongoing Checks

These test cases are designed for continuous data quality monitoring after the migration is complete.

### 13.1 Completeness Checks

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-001 | Positive | Daily: Verify `FACT_TRANSACTION` has rows for the current business day after each ETL run | Transaction count > 0 for each business day |
| DQ-002 | Positive | Monthly: Verify `FACT_MONTHLY_ACCOUNT_SNAPSHOT` has one row per active account for each month-end | Row count = count of active/dormant accounts |
| DQ-003 | Negative | Verify no NULL values in mandatory columns: `TRANSACTION_ID`, `TRANSACTION_DATE`, `TRANSACTION_AMOUNT`, `ACCOUNT_KEY`, `CUSTOMER_KEY` in new data loaded post-migration | Zero NULLs in mandatory columns |
| DQ-004 | Negative | Verify no data is loaded for future dates (`TRANSACTION_DATE > CURRENT_DATE`) | Zero future-dated transactions |
| DQ-005 | Edge | Verify data completeness on Norwegian public holidays when banks may be closed — some channels (ONLINE, MOBILE, API) may still generate transactions | Transaction count may be lower but non-zero for digital channels |

### 13.2 Accuracy Checks

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-006 | Positive | Verify `RUNNING_BALANCE` in `FACT_TRANSACTION` is consistent with prior balance +/- transaction amount for each account's transaction sequence | Balance chain is mathematically consistent |
| DQ-007 | Positive | Verify `RISK_SCORE` values in `DIM_CUSTOMER` remain within the valid range (0.00 - 100.00) | No out-of-range risk scores |
| DQ-008 | Positive | Verify `INTEREST_RATE` in `DIM_ACCOUNT` is non-negative | No negative interest rates |
| DQ-009 | Negative | Verify no CHECKING accounts have `CREDIT_LIMIT > 0` (credit limits apply to credit cards and credit products only) | CHECKING accounts have zero credit limits |
| DQ-010 | Edge | Verify `EXCHANGE_RATE` for NOK-to-NOK is exactly 1.000000 (not approximately 1) | Exact value, no floating-point drift |

### 13.3 Consistency Checks

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-011 | Positive | Verify `DIM_CUSTOMER.CUSTOMER_SEGMENT` values in Snowflake match the source system segments | No new/unexpected segment values appear |
| DQ-012 | Positive | Verify `DIM_ACCOUNT.ACCOUNT_STATUS` transitions are valid: ACTIVE -> DORMANT -> CLOSED, ACTIVE -> FROZEN -> ACTIVE, ACTIVE -> SUSPENDED | No invalid status transitions in SCD2 history |
| DQ-013 | Positive | Verify `DIM_BRANCH.REGION` values match the 5 Norwegian regions: OSTLANDET, VESTLANDET, SORLANDET, TRONDELAG, NORD-NORGE | No invalid region values |
| DQ-014 | Negative | Verify no `DIM_CUSTOMER` records have `ONBOARDING_DATE > CURRENT_DATE` | No future onboarding dates |
| DQ-015 | Negative | Verify no `DIM_ACCOUNT` records have `OPENING_DATE > CLOSING_DATE` | Account open date is always before or equal to close date |
| DQ-016 | Edge | Verify `DIM_DATE.FISCAL_YEAR` and `FISCAL_QUARTER` are consistent with the organization's fiscal calendar (which may differ from calendar year) | Fiscal alignment is correct |

### 13.4 Timeliness Checks

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-017 | Positive | Verify `ETL_INSERT_TS` on newly loaded rows is within the expected batch window (e.g., within 2 hours of batch start) | ETL timestamps are reasonable |
| DQ-018 | Positive | Verify `MAX(TRANSACTION_DATE)` in `FACT_TRANSACTION` is within 1 business day of CURRENT_DATE after daily ETL | Data freshness meets SLA |
| DQ-019 | Negative | Alert if `MAX(TRANSACTION_DATE)` is more than 2 business days behind CURRENT_DATE | Stale data triggers an alert |
| DQ-020 | Edge | Verify batch processing after Norwegian holidays correctly handles multi-day staging data (e.g., transactions from Friday-Monday loaded on Tuesday) | Multi-day batch loads process correctly |

### 13.5 Uniqueness Checks

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-021 | Positive | Verify `TRANSACTION_ID` uniqueness in `FACT_TRANSACTION` post each daily load | No duplicate transaction IDs |
| DQ-022 | Positive | Verify `(ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)` uniqueness in `FACT_MONTHLY_ACCOUNT_SNAPSHOT` post each monthly load | No duplicate snapshot records |
| DQ-023 | Positive | Verify `CUSTOMER_KEY` uniqueness in `DIM_CUSTOMER` | Surrogate keys are unique |
| DQ-024 | Positive | Verify `ACCOUNT_KEY` uniqueness in `DIM_ACCOUNT` | Surrogate keys are unique |
| DQ-025 | Negative | Verify `DIM_DATE.DATE_KEY` uniqueness (since Snowflake does not enforce SET table duplicate rejection) | No duplicate date keys |
| DQ-026 | Negative | Verify `DIM_PRODUCT.PRODUCT_ID` uniqueness | No duplicate product IDs |
| DQ-027 | Negative | Verify `DIM_BRANCH.BRANCH_ID` uniqueness | No duplicate branch IDs |

### 13.6 Validity Checks

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-028 | Positive | Verify `EMAIL_ADDRESS` format follows a valid pattern (contains '@' and '.') | All non-NULL email addresses are valid format |
| DQ-029 | Positive | Verify `PHONE_NUMBER` format follows Norwegian pattern (starts with '+47') | All non-NULL phone numbers follow expected format |
| DQ-030 | Positive | Verify `COUNTRY_CODE` values are valid ISO 3166-1 alpha-3 codes (all should be 'NOR' per seed data) | Only valid country codes exist |
| DQ-031 | Positive | Verify `CURRENCY_CODE` values are valid ISO 4217 codes: NOK, EUR, USD, GBP, SEK, DKK | Only valid currency codes exist |
| DQ-032 | Negative | Verify `POSTAL_CODE` is not empty for Norwegian addresses | No empty postal codes for NOR records |
| DQ-033 | Negative | Verify `DATE_OF_BIRTH` is not in the future and results in age >= 18 for banking customers | All customers are at least 18 years old |
| DQ-034 | Edge | Verify `BRANCH_CODE` follows the 6-character pattern (e.g., 'OSL001', 'BER001', 'TRD002') | All branch codes are 6 characters |
| DQ-035 | Edge | Verify `PRODUCT_CODE` format follows the pattern 'XXX-YYY' (e.g., 'CHK-STD', 'SAV-PRM') | All product codes follow the expected format |

### 13.7 Cross-System Reconciliation (Post-Migration Ongoing)

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| DQ-036 | Positive | Daily: Compare `SUM(TRANSACTION_AMOUNT)` in Snowflake vs source system for the latest batch | Sums match within 0.01 tolerance |
| DQ-037 | Positive | Monthly: Compare `SUM(CLOSING_BALANCE)` across all accounts in Snowflake vs source | Total deposits match |
| DQ-038 | Positive | Quarterly: Run full table row counts across all 7 tables and compare with source | All row counts match |
| DQ-039 | Negative | Verify no data loss: `COUNT(*)` in Snowflake >= `COUNT(*)` in Teradata source for each table (account for any expected growth) | No data loss detected |
| DQ-040 | Edge | Reconcile `FACT_TRANSACTION` amounts by `TRANSACTION_TYPE` and `CHANNEL` — compare multi-dimensional aggregates | Dimensional breakdown matches source |

---

## 14. Performance & Operational Validation

| TC ID | Type | Test Case | Expected Result |
|-------|------|-----------|-----------------|
| PF-001 | Positive | Verify `FACT_TRANSACTION` query performance with date range filter (`WHERE TRANSACTION_DATE BETWEEN ...`) leverages Snowflake micro-partition pruning (equivalent to Teradata PPI partition elimination) | Query scans only relevant partitions; performance is acceptable |
| PF-002 | Positive | Verify `CLUSTER BY (TRANSACTION_DATE)` or equivalent is applied to `FACT_TRANSACTION` for optimal pruning | Clustering key is configured on the date column |
| PF-003 | Positive | Verify `VW_CUSTOMER_360` query completes within acceptable response time (< 30 seconds for full result set) | View performance is acceptable |
| PF-004 | Positive | Verify `VW_BRANCH_PERFORMANCE` with its window functions (`RANK`, cumulative sum, moving average) completes within acceptable time | Complex analytics view performs adequately |
| PF-005 | Negative | Run a full table scan on `FACT_TRANSACTION` without a date filter — verify it still completes (no timeout) but is slower than filtered query | Full scan completes but is measurably slower |
| PF-006 | Edge | Verify `SP_MONTHLY_SNAPSHOT` with temporary table creation and MERGE statement completes for all active accounts within the ETL batch window | Snapshot procedure meets time SLA |
| PF-007 | Edge | Verify concurrent ETL execution: running the daily transaction load while querying `VW_REGULATORY_LARGE_TRANSACTIONS` does not cause blocking | Snowflake's multi-version concurrency handles concurrent access |
| PF-008 | Edge | Verify Snowflake `COMMENT ON TABLE/COLUMN` metadata is preserved and queryable via `INFORMATION_SCHEMA` | Table and column comments are accessible |

---

## Appendix A: Test Case Summary

| Category | Positive | Negative | Edge | Total |
|----------|----------|----------|------|-------|
| Schema & DDL Validation | 6 | 3 | 4 | 13 |
| Row Count Validation | 7 | 1 | 2 | 10 |
| Data Completeness & Column-Level | 24 | 8 | 27 | 59 |
| Data Type & Precision | 11 | 2 | 3 | 16 |
| Referential Integrity | 9 | 2 | 2 | 13 |
| SCD Type 2 Logic | 6 | 3 | 6 | 15 |
| Business Logic & Transformation | 11 | 5 | 11 | 27 |
| Teradata Feature Translation | 7 | 5 | 7 | 19 |
| Stored Procedure & Macro Migration | 10 | 5 | 11 | 26 |
| Aggregate & Checksum Reconciliation | 5 | 1 | 2 | 8 |
| View Migration | 8 | 4 | 6 | 18 |
| ETL Pipeline & BTEQ Migration | 3 | 2 | 3 | 8 |
| Data Quality — Post-Migration | 20 | 10 | 10 | 40 |
| Performance & Operational | 4 | 1 | 3 | 8 |
| **TOTAL** | **131** | **52** | **97** | **280** |

## Appendix B: Validation SQL Templates (Snowflake)

### Row Count Comparison Template
```sql
-- Run on Snowflake after migration
SELECT 'DIM_CUSTOMER' AS TABLE_NAME, COUNT(*) AS ROW_COUNT FROM BANKING_DW.DIM_CUSTOMER
UNION ALL
SELECT 'DIM_ACCOUNT', COUNT(*) FROM BANKING_DW.DIM_ACCOUNT
UNION ALL
SELECT 'DIM_PRODUCT', COUNT(*) FROM BANKING_DW.DIM_PRODUCT
UNION ALL
SELECT 'DIM_BRANCH', COUNT(*) FROM BANKING_DW.DIM_BRANCH
UNION ALL
SELECT 'DIM_DATE', COUNT(*) FROM BANKING_DW.DIM_DATE
UNION ALL
SELECT 'FACT_TRANSACTION', COUNT(*) FROM BANKING_DW.FACT_TRANSACTION
UNION ALL
SELECT 'FACT_MONTHLY_SNAPSHOT', COUNT(*) FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT
ORDER BY 1;
```

### Referential Integrity Check Template
```sql
-- Orphaned fact records
SELECT 'ORPHAN_TXN_ACCOUNT' AS CHECK_NAME, COUNT(*) AS ORPHAN_COUNT
FROM BANKING_DW.FACT_TRANSACTION ft
WHERE ft.ACCOUNT_KEY NOT IN (SELECT ACCOUNT_KEY FROM BANKING_DW.DIM_ACCOUNT)
UNION ALL
SELECT 'ORPHAN_TXN_CUSTOMER', COUNT(*)
FROM BANKING_DW.FACT_TRANSACTION ft
WHERE ft.CUSTOMER_KEY NOT IN (SELECT CUSTOMER_KEY FROM BANKING_DW.DIM_CUSTOMER)
UNION ALL
SELECT 'ORPHAN_SNAP_ACCOUNT', COUNT(*)
FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
WHERE snap.ACCOUNT_KEY NOT IN (SELECT ACCOUNT_KEY FROM BANKING_DW.DIM_ACCOUNT);
```

### SCD2 Integrity Check Template
```sql
-- Verify exactly one current record per customer
SELECT CUSTOMER_ID, COUNT(*) AS CURRENT_VERSIONS
FROM BANKING_DW.DIM_CUSTOMER
WHERE CURRENT_FLAG = 'Y'
GROUP BY CUSTOMER_ID
HAVING COUNT(*) <> 1;
-- Expected: Zero rows returned

-- Verify no timeline gaps
SELECT a.CUSTOMER_ID, a.EFFECTIVE_TO, b.EFFECTIVE_FROM,
       TIMESTAMPDIFF(SECOND, a.EFFECTIVE_TO, b.EFFECTIVE_FROM) AS GAP_SECONDS
FROM BANKING_DW.DIM_CUSTOMER a
JOIN BANKING_DW.DIM_CUSTOMER b
  ON a.CUSTOMER_ID = b.CUSTOMER_ID
 AND a.EFFECTIVE_TO = b.EFFECTIVE_FROM
 AND a.CUSTOMER_KEY <> b.CUSTOMER_KEY
WHERE TIMESTAMPDIFF(SECOND, a.EFFECTIVE_TO, b.EFFECTIVE_FROM) <> 0;
-- Expected: Zero rows returned
```

### Data Quality Monitoring Template
```sql
-- Daily completeness check
SELECT
    CURRENT_DATE AS CHECK_DATE,
    (SELECT COUNT(*) FROM BANKING_DW.FACT_TRANSACTION
     WHERE TRANSACTION_DATE = CURRENT_DATE) AS TODAY_TXN_COUNT,
    (SELECT MAX(TRANSACTION_DATE) FROM BANKING_DW.FACT_TRANSACTION) AS MAX_TXN_DATE,
    (SELECT COUNT(*) FROM BANKING_DW.FACT_TRANSACTION
     WHERE TRANSACTION_AMOUNT IS NULL) AS NULL_AMOUNT_COUNT,
    (SELECT COUNT(*) FROM BANKING_DW.FACT_TRANSACTION ft
     WHERE ft.ACCOUNT_KEY NOT IN
       (SELECT ACCOUNT_KEY FROM BANKING_DW.DIM_ACCOUNT)) AS ORPHAN_ACCOUNT_COUNT;
```
