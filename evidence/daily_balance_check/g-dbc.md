# daily_balance_check / g-dbc: AMBER

**Reference: DERIVED, NOT EXECUTED — expected outputs were derived by hand from the frozen seed under Teradata semantics (see parity/expected/daily_balance_check/DERIVATION.md); no Teradata instance exists.**

Business date: 2026-01-31.
Commit: `b6d7fa030c7754ebbd53cd101077fd08d43642d6`.
Seed precheck: GREEN.

| Output | Key | L1 expected/actual | L2 | L3 match % | L4 sample | Status |
|---|---|---:|---|---:|---:|---|
| legacy_failure_contract | failure contract | N/A | N/A | N/A | N/A | AMBER |
| timestamp_ties | POPULATION | 2/2 | match | 100.0% | 0 | GREEN |

## Expected execution failures

L1-L4 are **not applicable** to a failed relational result, not zero rows or a 100% match.
A matching fail-closed target contract remains **AMBER / not production-ready** pending business approval.
The target error mechanism is not an observed Teradata error code or phase.

### legacy_failure_contract

QUALIFY's window references ACCOUNT_KEY and TRANSACTION_TS outside the grouped relation; see DERIVATION.md. Exact Teradata error number and phase are not observed.

Contract matched: True. Query ID: `01c831af-030c-d2f8-0035-065b0006fc96`.
Expected target error: `{"errno": 100038, "message_contains": "DBC_LEGACY_GROUPING_UNRESOLVED", "sqlstate": "22018"}`.
Observed (sanitized): `{"errno": 100038, "sfqid": "01c831af-030c-d2f8-0035-065b0006fc96", "sqlstate": "22018", "type": "ProgrammingError"}`.


## Waivers

None.

## Open business questions

### Q-DBC-1 — open

Should DAILY_BALANCE_CHECK continue to reject execution as the supplied legacy macro does, or may it be repaired to select the latest transaction per account before aggregating? If repaired, what rule resolves equal TRANSACTION_TS with different balances, should negative filtering happen before or after latest-row selection, and how should the second, differently shaped alert result be exposed to the daily load caller (a separate function or an approved combined schema)?

Decision owner: Banking reconciliation business owner (unassigned).

## L4 samples

### legacy_failure_contract

No keyed row samples.

## How to reproduce

```sh
python -m parity run --object daily_balance_check --as-of 2026-01-31 --label g-dbc
```
