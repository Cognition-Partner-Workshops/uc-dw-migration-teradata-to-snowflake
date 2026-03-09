# Migration Runbook: Teradata to Snowflake

## Banking Data Warehouse (`BANKING_DW`)

---

## 1. Pre-Migration Checklist

### Snowflake Account Setup

- [ ] Snowflake account provisioned (Business Critical edition recommended for regulatory workloads)
- [ ] Network policies configured (IP allowlisting for ETL servers)
- [ ] SSO / MFA configured for user authentication

### Database and Schema Creation

```sql
CREATE DATABASE BANKING_DW;
USE DATABASE BANKING_DW;
CREATE SCHEMA PUBLIC;
```

### Warehouse Sizing

```sql
-- ETL warehouse for batch processing
CREATE WAREHOUSE ETL_WH
    WAREHOUSE_SIZE = 'MEDIUM'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    COMMENT = 'ETL batch processing warehouse';

-- Analytics warehouse for queries and reporting
CREATE WAREHOUSE ANALYTICS_WH
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 120
    AUTO_RESUME = TRUE
    COMMENT = 'Analytics and reporting queries';
```

### Role and Access Grants

```sql
-- ETL service role
CREATE ROLE ETL_ROLE;
GRANT USAGE ON DATABASE BANKING_DW TO ROLE ETL_ROLE;
GRANT USAGE ON SCHEMA BANKING_DW.PUBLIC TO ROLE ETL_ROLE;
GRANT ALL ON ALL TABLES IN SCHEMA BANKING_DW.PUBLIC TO ROLE ETL_ROLE;
GRANT ALL ON FUTURE TABLES IN SCHEMA BANKING_DW.PUBLIC TO ROLE ETL_ROLE;
GRANT USAGE ON WAREHOUSE ETL_WH TO ROLE ETL_ROLE;

-- Analyst role (read-only)
CREATE ROLE ANALYST_ROLE;
GRANT USAGE ON DATABASE BANKING_DW TO ROLE ANALYST_ROLE;
GRANT USAGE ON SCHEMA BANKING_DW.PUBLIC TO ROLE ANALYST_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA BANKING_DW.PUBLIC TO ROLE ANALYST_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA BANKING_DW.PUBLIC TO ROLE ANALYST_ROLE;
GRANT SELECT ON ALL VIEWS IN SCHEMA BANKING_DW.PUBLIC TO ROLE ANALYST_ROLE;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA BANKING_DW.PUBLIC TO ROLE ANALYST_ROLE;
GRANT USAGE ON WAREHOUSE ANALYTICS_WH TO ROLE ANALYST_ROLE;

-- Create internal stage for ETL exports
CREATE OR REPLACE STAGE BANKING_DW.ETL_EXPORT_STAGE
    COMMENT = 'Internal stage for ETL report exports';
```

---

## 2. Execution Order

### Phase A: Create Dimension Tables (run in order)

| Step | File | Object | Notes |
|------|------|--------|-------|
| A1 | `snowflake/ddl/tables/01_dim_customer.sql` | `DIM_CUSTOMER` | SCD Type 2, clustered by `ONBOARDING_DATE` |
| A2 | `snowflake/ddl/tables/02_dim_account.sql` | `DIM_ACCOUNT` | SCD Type 2, clustered by `OPENING_DATE` |
| A3 | `snowflake/ddl/tables/03_dim_product.sql` | `DIM_PRODUCT` | Small reference table, no clustering |
| A4 | `snowflake/ddl/tables/04_dim_branch.sql` | `DIM_BRANCH` | Small reference table, no clustering |
| A5 | `snowflake/ddl/tables/05_dim_date.sql` | `DIM_DATE` | Static calendar table, no clustering |

**Validation gate:** All 5 dimension tables created successfully. Verify with:
```sql
SELECT TABLE_NAME, ROW_COUNT
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'PUBLIC'
  AND TABLE_NAME LIKE 'DIM_%'
ORDER BY TABLE_NAME;
```

### Phase B: Create Fact Tables

| Step | File | Object | Notes |
|------|------|--------|-------|
| B1 | `snowflake/ddl/tables/06_fact_transaction.sql` | `FACT_TRANSACTION` | Clustered by `(TRANSACTION_DATE, ACCOUNT_KEY)` |
| B2 | `snowflake/ddl/tables/07_fact_monthly_snapshot.sql` | `FACT_MONTHLY_ACCOUNT_SNAPSHOT` | Clustered by `(SNAPSHOT_DATE, ACCOUNT_KEY)` |

**Validation gate:** Both fact tables created. Verify with:
```sql
SELECT TABLE_NAME, CLUSTERING_KEY
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'PUBLIC'
  AND TABLE_NAME LIKE 'FACT_%';
```

### Phase C: Load Seed Data

Load dimension seed data from CSV files using internal stages:

```sql
-- Create a file format for pipe-delimited CSVs
CREATE OR REPLACE FILE FORMAT BANKING_DW.PIPE_CSV
    TYPE = 'CSV'
    FIELD_DELIMITER = '|'
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF = ('', 'NULL');

-- PUT files to internal stage (run from SnowSQL CLI)
-- PUT file://data/seed/dim_customer_sample.csv @BANKING_DW.ETL_EXPORT_STAGE/seed/;
-- PUT file://data/seed/dim_account_sample.csv @BANKING_DW.ETL_EXPORT_STAGE/seed/;
-- PUT file://data/seed/dim_product_sample.csv @BANKING_DW.ETL_EXPORT_STAGE/seed/;
-- PUT file://data/seed/dim_branch_sample.csv @BANKING_DW.ETL_EXPORT_STAGE/seed/;

-- COPY INTO dimension tables
COPY INTO BANKING_DW.DIM_CUSTOMER
    FROM @BANKING_DW.ETL_EXPORT_STAGE/seed/dim_customer_sample.csv
    FILE_FORMAT = BANKING_DW.PIPE_CSV
    ON_ERROR = 'ABORT_STATEMENT';

COPY INTO BANKING_DW.DIM_ACCOUNT
    FROM @BANKING_DW.ETL_EXPORT_STAGE/seed/dim_account_sample.csv
    FILE_FORMAT = BANKING_DW.PIPE_CSV
    ON_ERROR = 'ABORT_STATEMENT';

COPY INTO BANKING_DW.DIM_PRODUCT
    FROM @BANKING_DW.ETL_EXPORT_STAGE/seed/dim_product_sample.csv
    FILE_FORMAT = BANKING_DW.PIPE_CSV
    ON_ERROR = 'ABORT_STATEMENT';

COPY INTO BANKING_DW.DIM_BRANCH
    FROM @BANKING_DW.ETL_EXPORT_STAGE/seed/dim_branch_sample.csv
    FILE_FORMAT = BANKING_DW.PIPE_CSV
    ON_ERROR = 'ABORT_STATEMENT';
```

**Validation gate:** Verify row counts match `data/validation/expected_row_counts.csv`:

| Table | Expected Rows |
|-------|---------------|
| `DIM_CUSTOMER` | 15 |
| `DIM_ACCOUNT` | 20 |
| `DIM_PRODUCT` | 10 |
| `DIM_BRANCH` | 14 |
| `DIM_DATE` | 10,958 |
| `FACT_TRANSACTION` | ~50,000 |
| `FACT_MONTHLY_ACCOUNT_SNAPSHOT` | 1,920 |

### Phase D: Create Views (depends on tables existing)

| Step | File | Object | Notes |
|------|------|--------|-------|
| D1 | `snowflake/ddl/views/01_vw_customer_360.sql` | `VW_CUSTOMER_360` | Uses CTE for latest snapshot |
| D2 | `snowflake/ddl/views/02_vw_regulatory_large_transactions.sql` | `VW_REGULATORY_LARGE_TRANSACTIONS` | QUALIFY supported natively |
| D3 | `snowflake/ddl/views/03_vw_branch_performance.sql` | `VW_BRANCH_PERFORMANCE` | Window functions replace CSUM/MAVG |

**Validation gate:** All 3 views created. Test each returns data:
```sql
SELECT COUNT(*) FROM BANKING_DW.VW_CUSTOMER_360;
SELECT COUNT(*) FROM BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS;
SELECT COUNT(*) FROM BANKING_DW.VW_BRANCH_PERFORMANCE;
```

### Phase E: Create Stored Procedures

| Step | File | Object | Source |
|------|------|--------|--------|
| E1 | `snowflake/dml/stored_procedures/sp_customer_scd2.sql` | `SP_CUSTOMER_SCD2` | Teradata procedure |
| E2 | `snowflake/dml/stored_procedures/sp_load_daily_transactions.sql` | `SP_LOAD_DAILY_TRANSACTIONS` | Teradata procedure |
| E3 | `snowflake/dml/stored_procedures/sp_monthly_snapshot.sql` | `SP_MONTHLY_SNAPSHOT` | Teradata procedure |
| E4 | `snowflake/dml/stored_procedures/sp_aml_screening.sql` | `SP_AML_SCREENING` | Teradata macro |
| E5 | `snowflake/dml/stored_procedures/sp_customer_txn_history.sql` | `SP_CUSTOMER_TXN_HISTORY` | Teradata macro |
| E6 | `snowflake/dml/stored_procedures/sp_daily_balance_check.sql` | `SP_DAILY_BALANCE_CHECK` | Teradata macro |

**Validation gate:** All 6 procedures created. Verify with:
```sql
SHOW PROCEDURES IN SCHEMA BANKING_DW.PUBLIC;
```

### Phase F: Set Up Orchestration (Snowflake Tasks replace BTEQ scripts)

| Step | File | Object | Replaces |
|------|------|--------|----------|
| F1 | `snowflake/dml/scripts/snowsql_daily_load.sql` | `SP_DAILY_LOAD_PIPELINE` | `bteq_daily_load.btq` |
| F2 | `snowflake/dml/scripts/snowsql_extract_report.sql` | `SP_EXTRACT_MONTHLY_REPORTS` | `bteq_extract_report.btq` |

After creating the procedures, optionally enable the Snowflake Tasks (commented out at the bottom of each script):
- `TASK_DAILY_LOAD` — runs daily at 06:00 Oslo time
- `TASK_MONTHLY_REPORTS` — runs 1st of each month at 08:00 Oslo time

**Validation gate:** Pipeline procedures created and callable.

### Phase G: Run Validation Suite

Execute the validation checksum queries to compare Teradata source vs Snowflake target:

```sql
-- Run all validation queries from:
-- snowflake/data/validation/checksum_queries.sql
```

Compare results against Teradata output for:
1. Row counts per table
2. Column-level checksums (note: HASH values will differ; compare aggregates)
3. Transaction amount aggregates by year/month
4. Monthly balance reconciliation totals
5. Referential integrity (all orphan counts should be 0)

---

## 3. Data Loading Approach

### Initial Migration (bulk load)

1. **Extract from Teradata**: Use TPT (Teradata Parallel Transporter) or BTEQ to export data to CSV/Parquet files
2. **Stage in Snowflake**: Use `PUT` to upload files to an internal stage, or load directly from cloud storage (S3/Azure Blob/GCS)
3. **Load with COPY INTO**: Use `COPY INTO` with appropriate file formats

```sql
-- Example for large fact table loading
COPY INTO BANKING_DW.FACT_TRANSACTION
    FROM @BANKING_DW.ETL_EXPORT_STAGE/fact_transaction/
    FILE_FORMAT = (TYPE = 'PARQUET')
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;
```

### Ongoing Loads

- **Snowpipe**: For near-real-time continuous ingestion from cloud storage
- **External stages**: For scheduled batch loads from S3/Azure Blob/GCS
- **Snowflake Tasks**: For scheduled ETL orchestration (replaces BTEQ cron jobs)

---

## 4. Rollback Strategy

1. **Parallel run**: Keep Teradata operational during the migration validation period
2. **Snowflake objects are recreatable**: All DDL/DML scripts are idempotent (`CREATE OR REPLACE`)
3. **Drop and recreate**: If a migration phase fails, drop the affected objects and re-run:
   ```sql
   -- Example: re-run Phase A
   DROP TABLE IF EXISTS BANKING_DW.DIM_CUSTOMER;
   DROP TABLE IF EXISTS BANKING_DW.DIM_ACCOUNT;
   -- ... then re-execute Phase A scripts
   ```
4. **Time Travel**: Snowflake Time Travel (up to 90 days on Enterprise edition) enables undoing accidental data changes:
   ```sql
   -- Restore table to state before a bad load
   CREATE OR REPLACE TABLE BANKING_DW.FACT_TRANSACTION
       CLONE BANKING_DW.FACT_TRANSACTION AT(OFFSET => -3600);
   ```

---

## 5. Validation Gates

Each phase **must pass validation** before proceeding to the next:

| Phase | Validation | Pass Criteria |
|-------|-----------|---------------|
| A | Dimension tables exist | 5 tables in `INFORMATION_SCHEMA.TABLES` |
| B | Fact tables exist with clustering | 2 tables with correct `CLUSTERING_KEY` |
| C | Seed data loaded | Row counts match `expected_row_counts.csv` |
| D | Views return data | All 3 views return `COUNT(*) > 0` |
| E | Procedures created | 6 procedures in `SHOW PROCEDURES` |
| F | Pipeline procedures callable | `SP_DAILY_LOAD_PIPELINE` and `SP_EXTRACT_MONTHLY_REPORTS` created |
| G | Checksum validation passes | Row counts match, aggregates match, 0 orphans |

---

## 6. Post-Migration Steps

1. **Performance tuning**: Monitor query performance and adjust clustering keys as needed
2. **Access control**: Review and finalize role-based access
3. **Monitoring**: Set up Snowflake alerts for failed tasks and resource usage
4. **Documentation**: Update data dictionary and lineage documentation
5. **Decommission Teradata**: Only after successful parallel run and sign-off from stakeholders
