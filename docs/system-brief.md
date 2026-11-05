# System Brief: Banking Data Warehouse (Teradata, Snowflake migration source)

*One-page brief for CTO/board. Every claim links to repo files. Lines marked **(inference)** are my reading, not something the repo states.*

## Purpose
- A **retail banking analytics data warehouse** covering customers, accounts, products, branches, transactions and month-end balances, plus regulatory reporting views ([README.md](../README.md#L22-L32)).
- The repo is the **starting point for a Teradata to Snowflake migration**. Its stated goals are inventory, conversion, a runbook and validation ([README.md](../README.md#L3), [README.md](../README.md#L56-L62)). The data is synthetic and was built for a workshop ([README.md](../README.md#L66)).
- Business functions it serves: customer 360 ([01_vw_customer_360.sql](../ddl/views/01_vw_customer_360.sql#L60)), regulatory large-transaction reporting ([02_vw_regulatory_large_transactions.sql](../ddl/views/02_vw_regulatory_large_transactions.sql#L55)), branch performance ([03_vw_branch_performance.sql](../ddl/views/03_vw_branch_performance.sql#L45)) and AML screening ([macro_aml_screening.sql](../dml/macros/macro_aml_screening.sql#L1-L5)). The users are compliance, finance and branch management **(inference)**.
- The bank is Norwegian: NOK is the base currency and the calendar uses Norwegian holidays ([02_dim_account.sql](../ddl/tables/02_dim_account.sql#L21), [05_dim_date.sql](../ddl/tables/05_dim_date.sql#L48)).

## Architecture
- **Language:** Teradata SQL only. The repo contains DDL, stored procedures, macros and BTEQ batch scripts, with no application code ([README.md](../README.md#L7-L20)).
- **Batch pipeline:** [bteq_daily_load.btq](../dml/scripts/bteq_daily_load.btq) runs these steps in order:
  1. Validates staging data.
  2. Assigns a batch ID.
  3. Runs `SP_CUSTOMER_SCD2`.
  4. Runs `SP_LOAD_DAILY_TRANSACTIONS`.
  5. Runs the balance-check macro.
  6. Writes a reconciliation report.
  
  See [L15-L99](../dml/scripts/bteq_daily_load.btq#L15-L99). Month-end figures come from [sp_monthly_snapshot.sql](../dml/stored_procedures/sp_monthly_snapshot.sql). The daily script does not call it, so it is scheduled separately **(inference)**.
- **Deployment:** an on-prem Teradata system, logged into through a service account ([bteq_daily_load.btq](../dml/scripts/bteq_daily_load.btq#L7)). Output goes to the server filesystem under `/etl/...` ([bteq_extract_report.btq](../dml/scripts/bteq_extract_report.btq#L17)). The repo has no scheduler, CI or IaC (no `.github/`).
- **Teradata lock-in:** the code depends on Teradata-only features, including PI/PPI, `COMPRESS`, `CSUM`/`MAVG`, macros and BTEQ ([teradata_features_reference.md](teradata_features_reference.md)).

## Data stores
- A **star schema** in the `BANKING_DW` database. It has 2 fact tables and 5 dimensions; customers and accounts keep full change history (SCD Type 2) ([er_diagram.md](../schemas/er_diagram.md#L67-L79)). Table DDL is in [ddl/tables/](../ddl/tables/).
- **Largest table:** `FACT_TRANSACTION`, partitioned monthly from 2018 to 2030 ([06_fact_transaction.sql](../ddl/tables/06_fact_transaction.sql#L4), [L51-L55](../ddl/tables/06_fact_transaction.sql#L51-L55)).
- **PII:** the customer table holds names, date of birth, email, phone and address ([01_dim_customer.sql](../ddl/tables/01_dim_customer.sql#L16-L27)).
- **No database-level redundancy:** all 7 tables are `NO FALLBACK` (for example [01_dim_customer.sql](../ddl/tables/01_dim_customer.sql#L7)).
- **Tables referenced but not defined in the repo:** `STG_TRANSACTIONS`, `STG_CUSTOMER`, `STG_TRANSACTION_ERRORS`, `ETL_LOG`, `ETL_BATCH_CONTROL` and `DIM_EXCHANGE_RATES` ([sp_load_daily_transactions.sql](../dml/stored_procedures/sp_load_daily_transactions.sql#L23-L50), [L107](../dml/stored_procedures/sp_load_daily_transactions.sql#L107), [sp_customer_scd2.sql](../dml/stored_procedures/sp_customer_scd2.sql#L25), [bteq_daily_load.btq](../dml/scripts/bteq_daily_load.btq#L32)).
- **Seed and validation data:** [data/seed/](../data/seed/) and [expected_row_counts.csv](../data/validation/expected_row_counts.csv).

## Integrations
- **Inbound:** staging tables loaded by daily date. The upstream core-banking source is not in the repo ([bteq_daily_load.btq](../dml/scripts/bteq_daily_load.btq#L18-L24)).
- **Outbound:** flat files. Each export uses the standard Teradata batch export (BTEQ `.EXPORT`) and writes to the server filesystem:
  - large-transaction CSV for regulatory submission
  - branch report
  - AML screening CSV

  See [bteq_extract_report.btq](../dml/scripts/bteq_extract_report.btq#L17), [L48](../dml/scripts/bteq_extract_report.btq#L48), [L69](../dml/scripts/bteq_extract_report.btq#L69). The customer-name file includes first and last names ([L23-L24](../dml/scripts/bteq_extract_report.btq#L23-L24)).
- **APIs:** none.
- **Auth:** Teradata `.LOGON` with a service-account ID. No credential value is stored in the repo; it is supplied at runtime **(inference)** ([bteq_daily_load.btq](../dml/scripts/bteq_daily_load.btq#L7)).

## Top 3 operational risks

**1. A missing FX rate can make foreign transactions invisible to regulatory reports. Severity: High**
- **What the code does:**
  - If no exchange rate exists for a day, `ZEROIFNULL` sets the NOK amount to **0**, and the record is not rejected ([sp_load_daily_transactions.sql](../dml/stored_procedures/sp_load_daily_transactions.sql#L84-L88)).
  - Regulatory and AML thresholds are tested against that NOK amount ([02_vw_regulatory_large_transactions.sql](../ddl/views/02_vw_regulatory_large_transactions.sql#L49-L51), [macro_aml_screening.sql](../dml/macros/macro_aml_screening.sql#L30)).
- **Why it matters:** large foreign transfers could be under-reported to regulators without anyone noticing.
- **Mitigation:** reject or hold any foreign-currency record that has no FX rate, and alert on that count.

**2. Daily load failures can go undetected. Severity: High**
- **What the code does:**
  - The transaction load's exit handler logs the SQL error but does not re-raise it ([sp_load_daily_transactions.sql](../dml/stored_procedures/sp_load_daily_transactions.sql#L20-L31)). The batch script probably sees the call as successful **(inference)**.
  - `SP_CUSTOMER_SCD2` always returns code 0 ([sp_customer_scd2.sql](../dml/stored_procedures/sp_customer_scd2.sql#L17)).
  - Batch IDs come from `MAX+1`, which is not concurrency-safe ([bteq_daily_load.btq](../dml/scripts/bteq_daily_load.btq#L31-L42)).
  - The extract checks its row count only after the export is closed ([bteq_extract_report.btq](../dml/scripts/bteq_extract_report.btq#L41-L43)).
- **Why it matters:** customer 360, compliance and finance reports could run on partial data that is marked "COMPLETED".
- **Mitigation:** re-raise errors, return real status codes, use an identity or sequence for batch IDs, and make the run fail when it rejects rows.

**3. The migration has no target code and no portable validation. Severity: Medium**
- **What the code does:**
  - No Snowflake SQL, runbook or translation notes exist yet; they are listed only as objectives ([README.md](../README.md#L58-L62)).
  - The checksum validation uses Teradata-only `HASHROW`, so it cannot run unchanged on Snowflake ([checksum_queries.sql](../data/validation/checksum_queries.sql#L3-L5), [L38](../data/validation/checksum_queries.sql#L38)).
  - There is no CI.
- **Why it matters:** cutover could be signed off without real evidence that the data reconciles, and the timeline and cost are not yet estimable.
- **Mitigation:** define platform-neutral reconciliation checks (counts, sums, `MD5` of key columns) and run them in CI against both platforms.
