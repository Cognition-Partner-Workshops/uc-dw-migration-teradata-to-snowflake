# Reconciliation

| Object | Status | Baseline rows | Actual rows | Matched rows |
|---|---|---:|---:|---:|
| AML_SCREENING_1 | GREEN | 1 | 1 | 1 |
| AML_SCREENING_2 | GREEN | 12 | 12 | 12 |
| AML_SCREENING_3 | GREEN | 1 | 1 | 1 |
| BTEQ_AML_SCREENING_1 | GREEN | 1 | 1 | 1 |
| BTEQ_AML_SCREENING_2 | GREEN | 12 | 12 | 12 |
| BTEQ_AML_SCREENING_3 | GREEN | 1 | 1 | 1 |
| BTEQ_BRANCH_PERFORMANCE | RED | 10 |  |  |

`BTEQ_BRANCH_PERFORMANCE`: {"baseline_rows": 10, "error": "CatalogException", "status": "RED"}

| BTEQ_LARGE_TXN_REPORT | RED | 228 |  |  |

`BTEQ_LARGE_TXN_REPORT`: {"baseline_rows": 228, "error": "CatalogException", "status": "RED"}

| CUSTOMER_TXN_HISTORY | GREEN | 227 | 227 | 227 |
| DAILY_BALANCE_CHECK_1 | GREEN | 8 | 8 | 8 |
| DAILY_BALANCE_CHECK_2 | GREEN | 1 | 1 | 1 |
| DIM_ACCOUNT | RED | 20 |  |  |

`DIM_ACCOUNT`: {"baseline_rows": 20, "error": "CatalogException", "status": "RED"}

| DIM_BRANCH | RED | 14 |  |  |

`DIM_BRANCH`: {"baseline_rows": 14, "error": "CatalogException", "status": "RED"}

| DIM_CUSTOMER | RED | 17 |  |  |

`DIM_CUSTOMER`: {"baseline_rows": 17, "error": "CatalogException", "status": "RED"}

| DIM_DATE | RED | 10958 |  |  |

`DIM_DATE`: {"baseline_rows": 10958, "error": "CatalogException", "status": "RED"}

| DIM_EXCHANGE_RATES | RED | 6 |  |  |

`DIM_EXCHANGE_RATES`: {"baseline_rows": 6, "error": "CatalogException", "status": "RED"}

| DIM_PRODUCT | RED | 10 |  |  |

`DIM_PRODUCT`: {"baseline_rows": 10, "error": "CatalogException", "status": "RED"}

| ETL_BATCH_CONTROL | RED | 2 |  |  |

`ETL_BATCH_CONTROL`: {"baseline_rows": 2, "error": "CatalogException", "status": "RED"}

| ETL_LOG | RED | 2 |  |  |

`ETL_LOG`: {"baseline_rows": 2, "error": "CatalogException", "status": "RED"}

| FACT_MONTHLY_ACCOUNT_SNAPSHOT | RED | 1920 |  |  |

`FACT_MONTHLY_ACCOUNT_SNAPSHOT`: {"baseline_rows": 1920, "error": "CatalogException", "status": "RED"}

| FACT_TRANSACTION | RED | 50009 |  |  |

`FACT_TRANSACTION`: {"baseline_rows": 50009, "error": "CatalogException", "status": "RED"}

| STG_CUSTOMER | RED | 5 |  |  |

`STG_CUSTOMER`: {"baseline_rows": 5, "error": "CatalogException", "status": "RED"}

| STG_TRANSACTIONS | RED | 11 |  |  |

`STG_TRANSACTIONS`: {"baseline_rows": 11, "error": "CatalogException", "status": "RED"}

| STG_TRANSACTION_ERRORS | RED | 2 |  |  |

`STG_TRANSACTION_ERRORS`: {"baseline_rows": 2, "error": "CatalogException", "status": "RED"}

| VW_BRANCH_PERFORMANCE | RED | 250 |  |  |

`VW_BRANCH_PERFORMANCE`: {"baseline_rows": 250, "error": "CatalogException", "status": "RED"}

| VW_CUSTOMER_360 | RED | 16 |  |  |

`VW_CUSTOMER_360`: {"baseline_rows": 16, "error": "CatalogException", "status": "RED"}

| VW_REGULATORY_LARGE_TRANSACTIONS | RED | 4939 |  |  |

`VW_REGULATORY_LARGE_TRANSACTIONS`: {"baseline_rows": 4939, "error": "CatalogException", "status": "RED"}


Full match: False
