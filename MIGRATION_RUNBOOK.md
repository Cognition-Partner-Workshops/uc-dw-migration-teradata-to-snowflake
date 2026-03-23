# Teradata → Snowflake Migration Runbook

## Overview

This runbook documents the end-to-end migration of the **Banking DW** (Retail Banking Analytics) data warehouse from Teradata to Snowflake. It covers schema conversion, data loading, ETL migration, and validation.

## Pre-Migration Checklist

- [ ] Snowflake account provisioned with appropriate edition (Enterprise recommended for clustering)
- [ ] Snowflake warehouse created (recommend `MEDIUM` for initial load, `SMALL` for incremental)
- [ ] Network connectivity between source Teradata and Snowflake staging (or file-based extract)
- [ ] SnowSQL CLI installed on ETL server
- [ ] Service account created in Snowflake with appropriate roles

## Migration Phases

### Phase 1: Schema Deployment

**Estimated time: 15 minutes**

Deploy converted DDL in dependency order:

```bash
# 1. Create database and schema
snowsql -c my_connection -q "CREATE DATABASE IF NOT EXISTS BANKING_DW;"
snowsql -c my_connection -q "CREATE SCHEMA IF NOT EXISTS BANKING_DW.BANKING_DW;"

# 2. Deploy dimension tables (no dependencies)
snowsql -c my_connection -f snowflake/ddl/tables/01_dim_customer.sql
snowsql -c my_connection -f snowflake/ddl/tables/03_dim_product.sql
snowsql -c my_connection -f snowflake/ddl/tables/04_dim_branch.sql
snowsql -c my_connection -f snowflake/ddl/tables/05_dim_date.sql

# 3. Deploy dimension tables (with FK dependencies)
snowsql -c my_connection -f snowflake/ddl/tables/02_dim_account.sql

# 4. Deploy fact tables
snowsql -c my_connection -f snowflake/ddl/tables/06_fact_transaction.sql
snowsql -c my_connection -f snowflake/ddl/tables/07_fact_monthly_snapshot.sql

# 5. Deploy views
snowsql -c my_connection -f snowflake/ddl/views/01_vw_customer_360.sql
snowsql -c my_connection -f snowflake/ddl/views/02_vw_regulatory_large_transactions.sql
snowsql -c my_connection -f snowflake/ddl/views/03_vw_branch_performance.sql

# 6. Deploy stored procedures
snowsql -c my_connection -f snowflake/dml/stored_procedures/sp_customer_scd2.sql
snowsql -c my_connection -f snowflake/dml/stored_procedures/sp_load_daily_transactions.sql
snowsql -c my_connection -f snowflake/dml/stored_procedures/sp_monthly_snapshot.sql
snowsql -c my_connection -f snowflake/dml/stored_procedures/sp_aml_screening.sql
snowsql -c my_connection -f snowflake/dml/stored_procedures/sp_customer_txn_history.sql
snowsql -c my_connection -f snowflake/dml/stored_procedures/sp_daily_balance_check.sql
```

### Phase 2: Data Extraction from Teradata

**Estimated time: 1-4 hours (depends on data volume)**

#### Option A: File-Based Extract (Recommended for Initial Load)

Extract data from Teradata into delimited files using BTEQ or TPT:

```sql
-- Example BTEQ export for each table
.EXPORT DATA FILE=/etl/staging/dim_customer.csv;
SEL * FROM BANKING_DW.DIM_CUSTOMER;
.EXPORT RESET;
```

Repeat for each table in this order:
1. `DIM_DATE` (static, no dependencies)
2. `DIM_BRANCH` (static)
3. `DIM_PRODUCT` (static)
4. `DIM_CUSTOMER` (SCD2 — export all versions)
5. `DIM_ACCOUNT` (SCD2 — export all versions)
6. `FACT_TRANSACTION` (largest — consider monthly partitions)
7. `FACT_MONTHLY_ACCOUNT_SNAPSHOT`

For large tables (FACT_TRANSACTION), extract in monthly chunks:
```sql
.EXPORT DATA FILE=/etl/staging/fact_txn_202501.csv;
SEL * FROM BANKING_DW.FACT_TRANSACTION
WHERE TRANSACTION_DATE BETWEEN DATE '2025-01-01' AND DATE '2025-01-31';
.EXPORT RESET;
```

#### Option B: Direct Snowpipe / External Stage

If Teradata exports to S3/Azure Blob/GCS:

```sql
-- Create external stage pointing to cloud storage
CREATE OR REPLACE STAGE BANKING_DW.TD_MIGRATION_STAGE
  URL = 's3://my-bucket/teradata-exports/'
  CREDENTIALS = (AWS_KEY_ID='...' AWS_SECRET_KEY='...')
  FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"'
                 SKIP_HEADER = 1 NULL_IF = (''));
```

### Phase 3: Data Loading into Snowflake

**Estimated time: 30 minutes - 2 hours**

#### Option A: File Upload + COPY INTO (for file-based extracts)

```sql
-- Upload files to internal stage
PUT file:///etl/staging/dim_customer.csv @BANKING_DW.ETL_EXPORTS/migration/;

-- Load into tables
COPY INTO BANKING_DW.DIM_CUSTOMER
FROM @BANKING_DW.ETL_EXPORTS/migration/dim_customer.csv
FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"'
               SKIP_HEADER = 1 NULL_IF = (''))
ON_ERROR = 'CONTINUE';
```

#### Option B: External Stage COPY INTO

```sql
COPY INTO BANKING_DW.DIM_CUSTOMER
FROM @BANKING_DW.TD_MIGRATION_STAGE/dim_customer/
FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"'
               SKIP_HEADER = 1 NULL_IF = (''))
ON_ERROR = 'CONTINUE';
```

#### Loading Order (respect dependencies)

| Step | Table | Approach | Notes |
|------|-------|----------|-------|
| 1 | DIM_DATE | Full load | Static dimension, ~11K rows |
| 2 | DIM_BRANCH | Full load | Small dimension, ~14 rows |
| 3 | DIM_PRODUCT | Full load | Small dimension, ~10 rows |
| 4 | DIM_CUSTOMER | Full load | SCD2, ~15 current rows + history |
| 5 | DIM_ACCOUNT | Full load | SCD2, ~20 current rows + history |
| 6 | FACT_TRANSACTION | Chunked by month | Largest table, ~50K rows |
| 7 | FACT_MONTHLY_ACCOUNT_SNAPSHOT | Full load | ~1,920 rows |

#### Seed Data Loading (for workshop)

For the workshop environment, load from CSV seed files:

```sql
-- Upload seed CSVs
PUT file://data/seed/dim_customer_sample.csv @BANKING_DW.ETL_EXPORTS/seed/;
PUT file://data/seed/dim_account_sample.csv @BANKING_DW.ETL_EXPORTS/seed/;
PUT file://data/seed/dim_branch_sample.csv @BANKING_DW.ETL_EXPORTS/seed/;
PUT file://data/seed/dim_product_sample.csv @BANKING_DW.ETL_EXPORTS/seed/;

-- Load each seed file
COPY INTO BANKING_DW.DIM_CUSTOMER FROM @BANKING_DW.ETL_EXPORTS/seed/dim_customer_sample.csv
FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"');
-- Repeat for other seed files
```

### Phase 4: Validation

**Estimated time: 30 minutes**

Run validation queries on both Teradata (source) and Snowflake (target) and compare results.

```bash
# Run Snowflake validation queries
snowsql -c my_connection -f snowflake/validation/01_row_count_validation.sql
snowsql -c my_connection -f snowflake/validation/02_checksum_validation.sql
snowsql -c my_connection -f snowflake/validation/03_business_reconciliation.sql
snowsql -c my_connection -f snowflake/validation/04_referential_integrity.sql
```

#### Validation Criteria

| Check | Pass Criteria |
|-------|--------------|
| Row counts | Source count = Target count for every table |
| Column checksums | Hash sums match within tolerance |
| Aggregate balances | Monthly totals match to the cent |
| Referential integrity | Zero orphaned foreign keys |
| Business rules | Regulatory view returns same flagged transactions |

See `data/validation/expected_row_counts.csv` for expected counts.

### Phase 5: ETL Cutover

**Estimated time: 1-2 hours**

1. **Deploy ETL stored procedures** (already done in Phase 1)
2. **Create Snowflake Tasks** for scheduled execution:

```sql
-- Daily ETL pipeline (runs at 6 AM UTC)
CREATE OR REPLACE TASK BANKING_DW.TASK_DAILY_ETL
  WAREHOUSE = 'ETL_WH'
  SCHEDULE = 'USING CRON 0 6 * * * UTC'
AS
  CALL BANKING_DW.SP_DAILY_ETL_PIPELINE();

-- Monthly reporting (runs 1st of month at 8 AM UTC)
CREATE OR REPLACE TASK BANKING_DW.TASK_MONTHLY_REPORTS
  WAREHOUSE = 'ETL_WH'
  SCHEDULE = 'USING CRON 0 8 1 * * UTC'
AS
  CALL BANKING_DW.SP_MONTHLY_SNAPSHOT(
    EXTRACT(YEAR FROM DATEADD('month', -1, CURRENT_DATE())),
    EXTRACT(MONTH FROM DATEADD('month', -1, CURRENT_DATE())),
    0  -- batch_id will be generated
  );

-- Enable tasks
ALTER TASK BANKING_DW.TASK_DAILY_ETL RESUME;
ALTER TASK BANKING_DW.TASK_MONTHLY_REPORTS RESUME;
```

3. **Disable Teradata ETL jobs** after confirming Snowflake pipeline runs successfully for 3+ days
4. **Monitor** via Snowflake query history and TASK_HISTORY table function

### Phase 6: Post-Migration Cleanup

- [ ] Archive Teradata export files
- [ ] Remove temporary stages
- [ ] Document any data discrepancies and resolutions
- [ ] Update downstream reporting tools to point to Snowflake
- [ ] Set up Snowflake resource monitors and alerts
- [ ] Review and right-size warehouse for ongoing workload

## Rollback Plan

If critical issues are found after cutover:

1. Re-enable Teradata ETL jobs
2. Point downstream consumers back to Teradata
3. Investigate and fix Snowflake issues
4. Re-run data load from Teradata exports
5. Re-validate before attempting cutover again

## Contacts

| Role | Responsibility |
|------|---------------|
| DBA / Platform | Snowflake account, warehouse sizing, access control |
| ETL Developer | Procedure testing, task scheduling, monitoring |
| Data Analyst | Business-level validation, downstream report testing |
| Project Manager | Cutover scheduling, stakeholder communication |
