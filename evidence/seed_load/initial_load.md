# initial_load: GREEN — seed landing

**DERIVED, NOT EXECUTED: no Teradata instance exists.**

Business date: 2026-01-31. Live Snowflake PUT/COPY; independent frozen CSV reference.
Scope: 13 seed tables. Views compile/read only; procedures/macros and view semantic parity are not certified.

| Table | Frozen | Snowflake | L2 | L3 match | L4 sample |
|---|---:|---:|---|---:|---:|
| DIM_CUSTOMER | 15 | 15 | match | 100.0% | 0 |
| DIM_ACCOUNT | 20 | 20 | match | 100.0% | 0 |
| DIM_PRODUCT | 10 | 10 | match | 100.0% | 0 |
| DIM_BRANCH | 14 | 14 | match | 100.0% | 0 |
| DIM_DATE | 10958 | 10958 | match | 100.0% | 0 |
| FACT_TRANSACTION | 50000 | 50000 | match | 100.0% | 0 |
| FACT_MONTHLY_ACCOUNT_SNAPSHOT | 1920 | 1920 | match | 100.0% | 0 |
| STG_TRANSACTIONS | 11 | 11 | match | 100.0% | 0 |
| STG_CUSTOMER | 5 | 5 | match | 100.0% | 0 |
| STG_TRANSACTION_ERRORS | 0 | 0 | match | 100.0% | 0 |
| ETL_BATCH_CONTROL | 1 | 1 | match | 100.0% | 0 |
| ETL_LOG | 0 | 0 | match | 100.0% | 0 |
| DIM_EXCHANGE_RATES | 6 | 6 | match | 100.0% | 0 |

The JSON includes all column profiles, table fingerprints, query IDs, live schema metadata,
manifest digest and mismatch fingerprints. Text extrema are hashes, never customer details.
Empty error/log tables have 100% vacuous key match. See `parity/expected/DERIVATION.md` for the derivation.
Live column type/length/scale/nullability gate: 0 errors.

## Converted views

- VW_CUSTOMER_360: compiled and read (15 rows); semantic parity not evaluated.
- VW_REGULATORY_LARGE_TRANSACTIONS: compiled and read (5478 rows); semantic parity not evaluated.
- VW_BRANCH_PERFORMANCE: compiled and read (250 rows); semantic parity not evaluated.
