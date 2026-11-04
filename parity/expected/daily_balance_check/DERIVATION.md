# DAILY_BALANCE_CHECK: derived failure, not a balance result

**Reference: DERIVED, NOT EXECUTED. There is no Teradata instance.**
Business date: **2026-01-31**. This reference was written and committed before
the Snowflake function. No values below were obtained from that function.

## Frozen inputs and source

- Legacy: `dml/macros/macro_daily_balance_check.sql`, SHA-256
  `688f0c5f891f1f4486b089e417be89bcb1f53237f1a16a12f570ed056c7d1128`.
- Frozen manifest SHA-256:
  `d7cc94ca5d411df98423d7004f648228f511a88f27f79339f26b41188f87b19a`.
- Inputs: 20 DIM_ACCOUNT rows, 15 DIM_CUSTOMER rows, 50,000 FACT_TRANSACTION
  rows, read directly from the manifest's pipe-delimited seed files using the
  legacy DDL types. The seed, legacy SQL and validation queries are unchanged.

## What the legacy text actually means

The file contains **two SELECT statements**, not one: a grouped balance summary
and a differently shaped, customer-level negative-balance alert. A SQL UDTF has
one fixed output schema; silently dropping the second statement or inventing a
union schema would be an additional business change.

Teradata's official documentation (consulted 2026-11-04) establishes:

1. [Evaluation Order of WHERE, GROUP BY, and QUALIFY Clauses](https://docs.teradata.com/r/Enterprise_IntelliFlex_VMware/SQL-Data-Manipulation-Language/SELECT-Statements/QUALIFY-Clause/Usage-Notes/Evaluation-Order-of-WHERE-GROUP-BY-and-QUALIFY-Clauses):
   WHERE filters the inputs, GROUP BY forms the groups, ordered analytical
   functions operate on the **grouped table**, then QUALIFY filters that result.
2. [GROUP BY and Window Functions](https://docs.teradata.com/r/Enterprise_IntelliFlex_VMware/SQL-Functions-Expressions-and-Predicates/Ordered-Analytical/Window-Aggregate-Functions/The-Window-Specification/GROUP-BY-Clause/GROUP-BY-and-Window-Functions):
   GROUP BY must include columns specified in window functions in a QUALIFY
   search condition. Grouping collapses rows, rather than leaving a hidden
   pre-aggregation account/transaction row for ROW_NUMBER to inspect.
3. [SELECT](https://docs.teradata.com/r/Enterprise_IntelliFlex_VMware/SQL-Data-Manipulation-Language/SELECT-Statements/SELECT):
   the documented ANSI clause ordering is not enforced. Therefore the conclusion
   here does **not** depend on calling the textual QUALIFY-before-GROUP-BY order
   a syntax error.
4. [Failure Response](https://docs.teradata.com/r/Enterprise_IntelliFlex_VMware/SQL-Fundamentals/SQL-Data-Handling/Failure-Response):
   in Teradata session mode a failing macro statement returns one failure
   response; it is not a successful partial result from the macro.

In statement 1, the grouping key is only `(a.ACCOUNT_TYPE, a.CURRENCY_CODE)`.
Neither `ft.ACCOUNT_KEY` (the window partition key) nor `ft.TRANSACTION_TS` (the
window ordering key) is grouped or aggregated. Therefore the analytic expression
is invalid on the grouped relation. The macro as supplied cannot produce the
claimed summary: it fails semantic validation, independently of seed values.
This is a documented-rule derivation, **not an observed Teradata error**; no exact
Teradata error number or validation phase is asserted. There is no prior installed
macro definition available to infer what an unsuccessful REPLACE might leave.

The legacy expected outcome in `failure.json` is thus **failure / no successful
relational result**, NOT a zero-row balance result. No empty summary CSV is
provided, and L1-L4 for the macro's failed result are **not applicable**. A target
that successfully returns even zero rows must fail this contract check.

## Independent frozen-seed diagnostics (not macro result parity)

These counts were enumerated from the frozen input using Python lists, joins and
timestamp buckets, before writing target SQL. They are retained separately in
`timestamp_ties.csv`; no customer names or identifiers are exported.

For summary candidates: join current ACTIVE accounts to transactions on
ACCOUNT_KEY, restricted to TRANSACTION_DATE = 2026-01-31. There are 67 joined
rows across all 20 account keys. Bucket by `(ACCOUNT_KEY, TRANSACTION_TS)`:
one bucket contains two rows, and every other bucket contains one. That bucket
is also its account's latest timestamp; its two RUNNING_BALANCE values differ.
There are no NULL timestamps in either diagnostic population.

For alert candidates: join current accounts and current customers on CUSTOMER_ID,
exclude CREDIT_CARD and LOAN accounts, restrict the date, then filter
RUNNING_BALANCE < 0 **before** applying the timestamp window (as the source does).
Only one joined row remains, in one account; there are no ties in that filtered
population. This is not proof that the account's latest unfiltered balance is
negative: filtering first excludes the competing nonnegative row at the same
latest timestamp. Moving the negative filter after ranking is another semantic
change, not a safe mechanical translation.

| Population | Eligible rows | Accounts | Tied timestamp groups | Rows in ties | Latest-tied accounts | Latest conflicting-balance accounts |
|---|---:|---:|---:|---:|---:|---:|
| summary_candidates | 67 | 20 | 1 | 2 | 1 | 1 |
| alert_candidates | 1 | 1 | 0 | 0 | 0 | 0 |

For the hypothetical *latest transaction per account, then aggregate* repair,
19 accounts have a unique winner and one has **two equally ordered candidates**.
ROW_NUMBER ordered only by TRANSACTION_TS cannot choose deterministically between
them. No transaction-ID tie-breaker, ANY_VALUE, MAX(balance), or seed change is
authorized. These diagnostic counts do not certify the hypothetical repair.

## Fail-closed target contract and business decision

The target must compile as the requested SQL UDTF but reject ordinary evaluation
with the explicit `DBC_LEGACY_GROUPING_UNRESOLVED` marker. Snowflake's numeric
conversion error is merely the SQL-only fail-closed mechanism, **not** a claim of
identical error codes or failure phase across engines. The provisional typed
summary signature does not approve a result schema or replace either legacy
result set. Numeric/date presentation FORMAT clauses must not turn values into
strings if a future approved implementation is supplied; rendering belongs in
the downstream extract. No successful extract is implemented in this ticket.

**Q-DBC-1 — decision owner: Banking reconciliation business owner (unassigned).**
Should DAILY_BALANCE_CHECK continue to reject execution as the supplied legacy
macro does, or may it be repaired to select the latest transaction per account
before aggregating? If repaired, what rule resolves equal TRANSACTION_TS with
different balances, should negative filtering happen before or after latest-row
selection, and how should the second, differently shaped alert result be exposed
to the daily load caller (a separate function or an approved combined schema)?

Until written approval, status is **AMBER / not production-ready**, even when the
fail-closed contract and the separate seed diagnostics pass. No L1-L3 balance
parity percentage is claimed and no business exception is signed.
