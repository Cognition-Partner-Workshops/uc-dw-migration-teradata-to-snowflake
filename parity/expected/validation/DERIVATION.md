# Validation queries reference — DERIVED, NOT EXECUTED

**No Teradata instance exists. The five CSVs in this directory are the expected outputs of
`data/validation/checksum_queries.sql` over the frozen seed, derived by hand under Teradata
(session mode TERA) semantics. They were not captured from a Teradata run and were not
produced by running the Snowflake ports in `snowflake/validation/`.**

## Scope and independence

- Input: the frozen seed `data/seed/frozen/` (manifest-verified, business date 2026-01-31)
  as landed by "Stand up the Snowflake schema and frozen seed". The seeded state is the
  input; no procedure, macro or BTEQ script runs before the checks.
- `parity/derive_validation.py` evaluates each query in hand-written Python over the frozen
  CSVs and the legacy DDL types. It imports only `snowflake/bank_model.py` (manifest check,
  DDL types, CSV typing — the same reader that produced `parity/expected/seed.json`). It never
  imports the Snowflake connector, never reads `snowflake/validation/*.sql` and never reads a
  harness result. `--check` proves the CSVs are reproducible; regeneration refuses to overwrite.
- The legacy file is unchanged; its SHA-256 is pinned in `parity/objects/validation.json`
  (`f44a03f2…4dad4`) and verified by the harness on every run.
- None of the five queries uses `CURRENT_DATE`/`CURRENT_TIMESTAMP`, so the 2026-01-31 pin
  does not change any value here.
- Cross-check: every grand total below is also reached through a second route — the column
  sums and counts in `parity/expected/seed.json` (the landing reference) — and they agree.

## CSV format

Pipe-delimited UTF-8, one header row in query column order, LF endings, `\N` = NULL.
Integers are exact; DECIMAL(18,2) results are written at scale 2; DATE as ISO `YYYY-MM-DD`
(Teradata `FORMAT 'YYYY-MM-DD'` is display-only and does not change the value compared).

## Teradata semantics applied

| Rule | Where it matters | Effect on the expected values |
| --- | --- | --- |
| A UNION result column takes the data type of the **first** SELECT; in TERA mode longer character values in later branches are silently truncated to that length. | Q1 (`'DIM_CUSTOMER'` → VARCHAR(12)), Q5 (`'ORPHAN_TXN_ACCOUNT'` → VARCHAR(18)) | Labels `FACT_TRANSAC`, `FACT_MONTHLY`, `ORPHAN_TXN_CUSTOME`, `ORPHAN_SNAP_ACCOUN`. The Snowflake port reproduces this with `LEFT(label, n)`. |
| `ORDER BY 1` sorts the result column as typed (after truncation). | Q1 | Rows ordered by truncated label. |
| Character comparison of NOT CASESPECIFIC columns is case-insensitive and ignores trailing pad. | Q2 `CURRENT_FLAG = 'Y'`, Q3 `TRANSACTION_TYPE = 'DEBIT'/'CREDIT'` | Seed values are all upper-case without padding, so case-insensitive and exact comparison give the same counts. |
| `SUM` of DECIMAL(n≤15, 2) returns DECIMAL(15,2); overflow is an error, not a wrap. `(DECIMAL(18,2))` then widens without rounding. | Q3, Q4 | Largest absolute monthly sum is 252,195,497.53 (Q3) and 2,678,301.71 (Q4), far below 10^13, so no overflow and the sums are exact. |
| `COUNT(DISTINCT x)` ignores NULL; `SUM(CASE … ELSE 0)` counts matches. | Q2, Q3 | No NULL keys exist in the seed. |
| `x NOT IN (subquery)` is unknown when `x` is NULL or the subquery yields any NULL. | Q5 | Dimension keys are NOT NULL and fact keys are NOT NULL, so the predicate is a plain set difference. |
| `GROUP BY` / `EXTRACT(YEAR|MONTH FROM date)` on DATE. | Q3 | Calendar year and month of `TRANSACTION_DATE`. |

## Waiver W1-hashrow (comparison-method change)

`SUM(HASHROW(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT))` cannot be reproduced:
HASHROW is Teradata's AMP-distribution hash (BYTE(4)), its algorithm is engine-internal and
Snowflake has no equivalent. Both sides therefore use the same replacement:

```
canonical = CUSTOMER_ID || 0x1F || FIRST_NAME || 0x1F || LAST_NAME || 0x1F || CUSTOMER_SEGMENT
            (NULL -> \N; integer as decimal text; strings exactly as stored: case and whitespace kept)
row_hash  = first 16 hex digits of SHA-256(UTF-8 canonical), read as an unsigned 64-bit integer
HASH_SUM  = sum of row_hash over the filtered rows (exact; fits DECIMAL(38,0))
```

The replacement is stricter than HASHROW on the NOT CASESPECIFIC name/segment columns (a
case-only change alters HASH_SUM), which is the conservative direction for a checksum. The
Snowflake port strips the `en-ci` collation with `COLLATE(col, '')` so the bytes hashed are
the stored values. Approver role: migration lead (comparison method only; no business value
changes). Recorded in `parity/objects/validation.json` and every evidence report.

## Q1 — row counts (`q1_row_counts.csv`)

Each value is the record count of the table's frozen CSV, equal to `manifest.json` rows:

| Label (as truncated) | Table | Rows | Why |
| --- | --- | ---: | --- |
| DIM_ACCOUNT | DIM_ACCOUNT | 20 | 20 synthetic accounts |
| DIM_BRANCH | DIM_BRANCH | 14 | 14 branches |
| DIM_CUSTOMER | DIM_CUSTOMER | 15 | 15 customers, 1001–1015 |
| DIM_DATE | DIM_DATE | 10958 | 30 years × 365 + 8 leap days (2000-01-01–2029-12-31) |
| DIM_PRODUCT | DIM_PRODUCT | 10 | 10 products |
| FACT_MONTHLY | FACT_MONTHLY_ACCOUNT_SNAPSHOT | 1920 | 96 month ends × 20 accounts |
| FACT_TRANSAC | FACT_TRANSACTION | 50000 | 49,990 transactions + 10 restatements |

## Q2 — DIM_CUSTOMER checksum (`q2_dim_customer_checksum.csv`)

- Filter `CURRENT_FLAG = 'Y'`: all 15 rows have `Y` → `ROW_COUNT = 15`.
- `CUSTOMER_ID` 1001–1015 are unique → `DISTINCT_CUSTOMERS = 15`.
- `ONBOARDING_DATE` minimum is customer 1011 (2005-02-28), maximum customer 1010
  (2026-01-15) → `MIN_ONBOARD_DATE = 2005-02-28`, `MAX_ONBOARD_DATE = 2026-01-15`.
- `IS_ACTIVE = 1` on all 15 rows → `ACTIVE_COUNT = 15` (matches the seed.json profile sum 15).
- `HASH_SUM` = sum of the 15 per-row W1 hashes below (names are synthetic and not
  reproduced; lengths shown) = **141158072122237418528**.

| CUSTOMER_ID | len(FIRST_NAME) | len(LAST_NAME) | CUSTOMER_SEGMENT | row_hash (uint64) | ONBOARDING_DATE |
| ---: | ---: | ---: | --- | ---: | --- |
| 1001 | 50 | 50 | PREMIUM | 2457203150393684433 | 2015-06-01 |
| 1002 | 10 | 8 | RETAIL | 12853793253712355357 | 2018-01-15 |
| 1003 | 10 | 8 | PREMIUM | 1956524869964862734 | 2012-09-20 |
| 1004 | 10 | 8 | RETAIL | 11210482571282095480 | 2020-03-10 |
| 1005 | 10 | 8 | RETAIL | 2080013078138845272 | 2019-07-25 |
| 1006 | 10 | 8 | PRIVATE | 4351847110947983179 | 2010-11-01 |
| 1007 | 10 | 8 | CORPORATE | 3128913953728229568 | 2008-04-15 |
| 1008 | 10 | 8 | RETAIL | 12645227870493369762 | 2024-01-08 |
| 1009 | 10 | 8 | PREMIUM | 12406536221886807765 | 2016-05-30 |
| 1010 | 11 | 9 | RETAIL | 1649364783716466366 | 2026-01-15 |
| 1011 | 11 | 9 | PREMIUM | 17952230713517511776 | 2005-02-28 |
| 1012 | 11 | 9 | RETAIL | 7711404545955175491 | 2023-09-01 |
| 1013 | 11 | 9 | CORPORATE | 17384332691397266698 | 2009-11-15 |
| 1014 | 11 | 9 | PREMIUM | 15497412890387081552 | 2014-06-20 |
| 1015 | 11 | 9 | RETAIL | 17872784416715683095 | 2021-04-05 |

## Q3 — FACT_TRANSACTION monthly aggregates (`q3_fact_transaction_aggregates.csv`)

- `TRANSACTION_DATE` spans 2024-02-01 to 2026-01-31 → 24 (year, month) groups,
  2024-02 … 2026-01, ordered by year then month.
- Per group: `TXN_COUNT` = rows; `TOTAL_AMOUNT`/`TOTAL_BASE_AMOUNT` = exact DECIMAL sums of
  `TRANSACTION_AMOUNT`/`BASE_CURRENCY_AMOUNT` (no NULL base amounts); distinct
  `ACCOUNT_KEY` / `CUSTOMER_KEY`; counts of `TRANSACTION_TYPE` = DEBIT / CREDIT; count of
  `IS_INTERNATIONAL = 1`. Restatement rows (same `TRANSACTION_ID`, other batch) are separate
  rows and are counted, exactly as the legacy query does.
- Worked example, 2024-02: 2,014 rows, TOTAL_AMOUNT 43,286,020.33, TOTAL_BASE_AMOUNT
  192,453,879.04, 20 accounts, 10 customers, 423 DEBIT, 404 CREDIT, 1,126 international.
- Every month has 20 distinct accounts and 10 distinct customers: transactions reference
  account keys 1–20 and customer keys 1–10 only.
- Totals over the 24 rows, cross-checked against `seed.json` FACT_TRANSACTION profiles (and,
  for the type counts, a whole-file count that ignores month grouping):

| Column | Sum of CSV | seed.json route |
| --- | ---: | --- |
| TXN_COUNT | 50,000 | row count 50,000 |
| TOTAL_AMOUNT | 1,034,014,842.38 | TRANSACTION_AMOUNT sum 1034014842.38 |
| TOTAL_BASE_AMOUNT | 4,723,528,919.45 | BASE_CURRENCY_AMOUNT sum 4723528919.45 |
| DEBIT_COUNT | 9,869 | whole-file count of `TRANSACTION_TYPE` = DEBIT 9,869 (CREDIT 10,034, TRANSFER 10,096, INTEREST 10,030, FEE 9,971; total 50,000) |
| CREDIT_COUNT | 10,034 | whole-file count of CREDIT 10,034 |
| INTL_COUNT | 28,610 | IS_INTERNATIONAL sum 28610 |

## Q4 — monthly balance reconciliation (`q4_monthly_balance_reconciliation.csv`)

- `SNAPSHOT_MONTH_KEY` 201802 … 202601 → 96 groups, each with `ACCOUNT_COUNT = 20`.
- Per group exact DECIMAL sums of CLOSING_BALANCE (as TOTAL_DEPOSITS; negative balances are
  included, as in the legacy query), TOTAL_DEBITS, TOTAL_CREDITS, INTEREST_EARNED (as
  TOTAL_INTEREST) and FEES_CHARGED (as TOTAL_FEES). No NULLs in these columns.
- Worked example, 201802: 2,466,095.68 / 365,107.42 / 457,364.60 / 2,815.06 / 1,509.69 / 20.
- Totals over the 96 rows, cross-checked against `seed.json` FACT_MONTHLY_ACCOUNT_SNAPSHOT:

| Column | Sum of CSV | seed.json route |
| --- | ---: | --- |
| TOTAL_DEPOSITS | 228,408,151.60 | CLOSING_BALANCE sum 228408151.60 |
| TOTAL_DEBITS | 37,951,906.36 | TOTAL_DEBITS sum 37951906.36 |
| TOTAL_CREDITS | 38,026,738.27 | TOTAL_CREDITS sum 38026738.27 |
| TOTAL_INTEREST | 288,553.00 | INTEREST_EARNED sum 288553.00 |
| TOTAL_FEES | 143,733.93 | FEES_CHARGED sum 143733.93 |
| ACCOUNT_COUNT | 1,920 | row count 1,920 |

## Q5 — orphan checks (`q5_orphan_checks.csv`)

- DIM_ACCOUNT keys = {1…20}; DIM_CUSTOMER keys = {1…15}; no NULLs on either side.
- FACT_TRANSACTION account keys ⊆ {1…20} → `ORPHAN_TXN_ACCOUNT = 0`.
- FACT_TRANSACTION customer keys = {1…10} ⊆ {1…15} → `ORPHAN_TXN_CUSTOME = 0`.
- Snapshot account keys = {1…20} → `ORPHAN_SNAP_ACCOUN = 0`.
- Rows are keyed by label; the legacy query has no ORDER BY, so row order is not compared.

## Review

Derived by the harness ticket worker from the frozen seed; per decision d-reference these
expected outputs are to be reviewed by a person in the PR. Do not edit the seed, the legacy
SQL, these CSVs or the comparison rules to make a run pass; a new business decision needs a
new versioned reference.
