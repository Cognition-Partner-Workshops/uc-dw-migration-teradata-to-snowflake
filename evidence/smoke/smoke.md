# smoke / smoke: GREEN

**Reference: DERIVED, NOT EXECUTED — expected outputs were derived by hand from the frozen seed under Teradata semantics (see parity/expected/DERIVATION.md); no Teradata instance exists.**

Business date: 2026-01-31.
Commit: `3b7daf5c4d41cf7c159fbd5e0e8c71b981f60fc6`.
Seed precheck: GREEN.

| Table | L1 expected/actual | L2 | L3 match % | Status |
|---|---:|---|---:|---|
| DIM_CUSTOMER | 15/15 | match | 100.0% | GREEN |
| DIM_ACCOUNT | 20/20 | match | 100.0% | GREEN |
| DIM_PRODUCT | 10/10 | match | 100.0% | GREEN |
| DIM_BRANCH | 14/14 | match | 100.0% | GREEN |
| DIM_DATE | 10958/10958 | match | 100.0% | GREEN |
| FACT_TRANSACTION | 50000/50000 | match | 100.0% | GREEN |
| FACT_MONTHLY_ACCOUNT_SNAPSHOT | 1920/1920 | match | 100.0% | GREEN |
| STG_TRANSACTIONS | 11/11 | match | 100.0% | GREEN |
| STG_CUSTOMER | 5/5 | match | 100.0% | GREEN |
| STG_TRANSACTION_ERRORS | 0/0 | match | 100.0% (vacuous) | GREEN |
| ETL_BATCH_CONTROL | 1/1 | match | 100.0% | GREEN |
| ETL_LOG | 0/0 | match | 100.0% (vacuous) | GREEN |
| DIM_EXCHANGE_RATES | 6/6 | match | 100.0% | GREEN |

## Views

| View | Rows | Scope |
|---|---:|---|
| VW_CUSTOMER_360 | 15 | read only, semantic parity not certified |
| VW_REGULATORY_LARGE_TRANSACTIONS | 5478 | read only, semantic parity not certified |
| VW_BRANCH_PERFORMANCE | 250 | read only, semantic parity not certified |

## How to reproduce

```sh
python -m parity smoke --as-of 2026-01-31 --label smoke
```

