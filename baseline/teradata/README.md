# Derived Teradata baseline

**derived, not executed: no Teradata instance exists**

`tools/td_baseline.py` evaluates the legacy sources in DuckDB over
`fixtures/frozen/`. The clock is 2026-01-31, with load timestamp
2026-01-31 06:00:00 and batch ID 20260131 (MAX control batch + 1).
Every invocation starts with a fresh in-memory database. Idempotence means
reproducing a complete run from frozen inputs; rerunning the original daily
INSERT on an already-loaded warehouse would append duplicate transactions.

The CSVs contain relational values with headers, comma delimiters, UTF-8,
LF newlines and the null token `\N`. Rows sort lexically by all serialized
columns for byte comparison. Result ordering is not a reconciliation condition.
`manifest.json` records column types and row counts.

## Execution and decisions

- The daily BTEQ orchestration calls SP_CUSTOMER_SCD2 before
  SP_LOAD_DAILY_TRANSACTIONS, records completion, then the fixture invokes
  SP_MONTHLY_SNAPSHOT(2026, 1, 20260131). Views and macros read the final
  post-procedure state. The monthly procedure is an additional explicit call,
  absent from the daily script.
- Each seed table has a post-run CSV, including unchanged inputs. The procedures
  write DIM_CUSTOMER, FACT_TRANSACTION, FACT_MONTHLY_ACCOUNT_SNAPSHOT,
  STG_TRANSACTION_ERRORS and ETL_LOG. Daily orchestration writes ETL_BATCH_CONTROL.
  OUT parameters are not separate relational result sets.
- Source comments mentioning MERGE do not override executable statements:
  customer SCD2 uses UPDATE then INSERT, and daily loading uses INSERT.
  No transaction deduplication or running-balance calculation is added.
- SCD2 compares exactly the listed attributes with SQL three-valued inequality.
  Only phone/email use COALESCE. A non-null address changing to null alone does
  not expire a customer. Names, date of birth and address line 2 are not tracked.
- SCD2 expiration precedes the insertion anti-join. QUALIFY partitions by
  existing.CUSTOMER_ID, including a single null partition for all brand-new
  customers. The fixture therefore inserts only customer 2026001, not 2026002.
  The baseline preserves that source defect.
- The SCD2 source puts QUALIFY before WHERE, an invalid clause order. The
  evaluator applies WHERE before window evaluation. Existing EFFECTIVE_TO ties
  use ascending existing.CUSTOMER_KEY; brand-new null ties use ascending staging
  CUSTOMER_ID. Identity allocation follows ascending CUSTOMER_ID after the
  maximum seed surrogate (16 and 17). Teradata parallel identity allocation is
  unverified, so the assigned keys are a fixture convention.
- Daily rejects retain positional staging columns followed by ERROR_REASON and
  BATCH_ID. NOT IN retains SQL null semantics. Valid rows require both a current
  account and a current customer; an account with no current customer is silently
  skipped rather than classified INVALID_ACCOUNT.
- Transaction timestamps combine date and time; DATE_KEY is YYYYMMDD.
  Missing FX becomes zero, even for non-NOK amounts. NOK amount is unchanged,
  while its exchange-rate field still comes from the left join. Amounts round
  into the declared DECIMAL(15,2); exchange rates retain six decimals.
- Omitted transaction columns use legacy defaults: IS_FLAGGED=0, RUNNING_BALANCE
  and FLAG_REASON null. Start/completion logs use the pinned clock and duration
  string 0. No SQL exception occurs in the frozen scenario; the exception log
  branch is not represented as a fabricated successful result.
- Monthly period boundaries are January 1 through January 31 inclusive.
  v_prev_snapshot_date is December 1, not December 31. The source therefore
  finds no prior month-end snapshot and uses zero opening balances.
- The monthly source references a.CUSTOMER_KEY, absent from DIM_ACCOUNT.
  The evaluator explicitly resolves the key through the already-written
  LEFT JOIN DIM_CUSTOMER c. A literal execution would fail to compile; owner
  approval of the repair is unverified.
- Monthly aggregation counts overdraft transaction rows, not distinct days.
  TRANSFER contributes to neither total debits nor total credits. Missing
  aggregates become zero; dormant days equal the inclusive period length only
  for accounts with no aggregate. The MERGE updates exactly its SET columns,
  retaining matched CUSTOMER_KEY, dimensions, CURRENCY_CODE and
  BASE_CURRENCY_CLOSING. The unmatched INSERT omits BASE_CURRENCY_CLOSING.
- CUSTOMER_360 uses the latest snapshot per account, current active customers,
  and the unbounded-above date predicate CURRENT_DATE-90. PRIMARY_CHANNEL is
  lexical MAX, not a frequency mode. ZEROIFNULL becomes COALESCE(value, 0).
  Tenure uses days / 365.25 rounded to DECIMAL(5,1).
- The regulatory view applies its WHERE thresholds before QUALIFY and keeps the
  highest ETL_BATCH_ID per TRANSACTION_ID. Equal batches use descending date,
  ascending account key; any remaining all-equal peer is immaterial to this seed.
- Native HASHROW is proprietary and unavailable in DuckDB. ROW_HASH uses
  lowercase MD5 hex of decimal TRANSACTION_ID, a pipe, and ISO date as an explicit
  derived surrogate. **ROW_HASH is not a verified Teradata hash.** Native hash
  compatibility remains unresolved; a green fixture report proves the documented
  derived contract only, not native HASHROW equivalence or real licence release.
- Branch CSUM and MAVG have no branch partition or year reset in the source.
  The evaluator uses a global ordered row window (month, ascending BRANCH_ID),
  cumulative fees across all included rows and a three-row volume mean, including
  partial windows. The YTD and 3M column names do not justify changing the SQL
  into per-branch, year-reset windows. Equal-month peer order is unspecified by
  the source; BRANCH_ID is the deterministic fixture tie-breaker.
- Branch date filtering uses CURRENT_DATE minus 24 calendar months before
  aggregation. Regional RANK keeps ties; percentage divides by the region/month
  total with zero denominators becoming null.
- DAILY_BALANCE_CHECK produces separate summary and alert CSVs. The summary
  source combines aggregate GROUP BY with window references to ungrouped fact
  columns and puts QUALIFY before GROUP BY. The evaluator selects the last fact
  per account first, then groups, matching the stated account-summary intent.
  Latest timestamp ties use descending TRANSACTION_ID then ETL_BATCH_ID.
- Negative alerts filter negative balances before QUALIFY, so an account can
  alert even when another later balance is positive. The seeded 23:59 timestamp
  tie is resolved by descending transaction ID/batch for the summary, while the
  alert retains its negative peer. No overdraft-limit predicate is invented.
- AML_SCREENING runs with date 2026-01-31, lookback 30 days, threshold 50000.
  Structuring uses the inclusive 80%-100% interval and at least three rows.
  Rapid movement retains every qualifying credit/debit pair within 0-3 days,
  including duplicate relational rows; direction is determined by transaction
  type rather than the sign. New-customer screening uses onboarding within
  90 days and the sum threshold.
- CUSTOMER_TXN_HISTORY runs for customer 1010 with the default 30-day interval
  and ALL types. SAMPLE 1000 is random in Teradata, not TOP 1000. The frozen
  result has 227 rows, so all qualify; LIMIT 1000 is equivalent only for this
  fixture. Larger inputs require an agreed sampling contract.
- BTEQ extract CSVs represent the selected relational values rather than binary
  DATA exports, padded CHAR fields, report headings or numeric FORMAT strings.
  BTEQ_LARGE_TXN_REPORT covers December 31 through January 31 inclusive.
  BTEQ_BRANCH_PERFORMANCE selects December 2025 and preserves display aliases.
  BTEQ_AML_SCREENING_1 through _3 retain all macro result sets.
- The first extract is nonempty, so the BTEQ NODATA branch is not taken.
  Empty-first-extract behavior would skip the remaining exports and return 4;
  no success banner or BTEQ control command is treated as a data table.
- NOT CASESPECIFIC comparisons use the frozen uppercase category values.
  General Teradata collation, trailing CHAR padding, SET duplicate elimination,
  timestamp timezones, native hash encoding and production identity allocation
  have not been verified against a Teradata engine. Statistics, locks, journals,
  physical indexes and compression do not affect these relational fixture rows.

## Reproduction

`python tools/generate_seed.py --check` checks immutable inputs, and
`python tools/td_baseline.py --check` regenerates all derived outputs in memory
and compares bytes. Generation into a new directory uses `--output PATH`;
neither command overwrites accepted CSVs. The seed reuses the deterministic
generator with random seed 239 from the frozen-input branch; inferred staging
contracts remain Teradata syntax under `fixtures/ddl/` and are explained in
`fixtures/inferred_ddl.md`. The seven seed table counts match
`data/validation/expected_row_counts.csv`; post-procedure counts differ by design.
