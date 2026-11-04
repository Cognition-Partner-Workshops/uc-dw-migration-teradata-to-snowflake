# validation / g-dbc-regression: GREEN

**Reference: DERIVED, NOT EXECUTED — expected outputs were derived by hand from the frozen seed under Teradata semantics (see parity/expected/validation/DERIVATION.md); no Teradata instance exists.**

Business date: 2026-01-31.
Commit: `b6d7fa030c7754ebbd53cd101077fd08d43642d6`.
Seed precheck: GREEN.

| Output | Key | L1 expected/actual | L2 | L3 match % | L4 sample | Status |
|---|---|---:|---|---:|---:|---|
| q1_row_counts | TABLE_NAME | 7/7 | match | 100.0% | 0 | GREEN |
| q2_dim_customer_checksum | (single row) | 1/1 | match | 100.0% | 0 | GREEN |
| q3_fact_transaction_aggregates | TXN_YEAR, TXN_MONTH | 24/24 | match | 100.0% | 0 | GREEN |
| q4_monthly_balance_reconciliation | SNAPSHOT_MONTH_KEY | 96/96 | match | 100.0% | 0 | GREEN |
| q5_orphan_checks | CHECK_NAME | 3/3 | match | 100.0% | 0 | GREEN |

## Expected execution failures

None.

## Waivers

| ID | Change | Reason | Approver role |
|---|---|---|---|
| W1-hashrow | SUM(HASHROW(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT)) replaced by the sum of the first 64 bits of SHA-256 over a canonical string, computed identically in the derived reference and the Snowflake port. | HASHROW is Teradata's AMP row-distribution hash (BYTE(4)); it has no Snowflake equivalent and its values cannot be reproduced on another engine. The replacement is case- and whitespace-preserving, so it is stricter than HASHROW on NOT CASESPECIFIC columns. | Migration lead (comparison-method change; no business value involved) |

## Open business questions

None.
## L4 samples

None; all outputs are green.

## How to reproduce

```sh
python -m parity run --object validation --as-of 2026-01-31 --label g-dbc-regression
```
