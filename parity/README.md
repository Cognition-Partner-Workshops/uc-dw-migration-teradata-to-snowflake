# Parity harness

The top-level `parity` package runs one converted object against an independently
derived, frozen expected result. It does not execute Teradata or derive expected
values from the converted Snowflake output.

## CLI

```sh
python -m parity list
python -m parity run --object validation --as-of 2026-01-31 [--label run] [--reset-seed]
python -m parity smoke --as-of 2026-01-31 [--label smoke]
```

`run` checks the legacy source checksum, validates the frozen seed, deploys the
object's SQL prerequisites, executes its outputs, and writes machine-readable and
Markdown evidence under `evidence/<object>/<label>.*`. `--reset-seed` deliberately
resets the owned banking seed schema before verification; objects may also request
that behavior in their spec. `smoke` only verifies the 13 frozen seed tables and
reads the three views; view semantic parity is not certified.

Evidence labels accept only ASCII letters, digits, `_` and `-`. The business date
must match both `bank_model.AS_OF` and the frozen manifest.

## Object specs

Each `parity/objects/<object>.json` defines an object, title, legacy source and
SHA-256, derivation document, seed mode (`verify` or `reset`), ordered deployment
SQL paths, outputs, waivers, and business questions. Each output names its expected
pipe-delimited CSV, ordered typed columns, key columns, and exactly one execution
source: a single-SELECT `sql` file or a fully qualified `table`. An empty key (`[]`)
is for a single-row result; more than one row is a duplicate-key error.

Expected CSV headers must match spec column order. `\N` alone denotes NULL and
empty strings remain distinct. Supported column types use `bank_model.cast` and
`bank_model.canonical`. `plain: true` opts textual values into evidence; otherwise
text extrema and L4 values are SHA-256 fingerprints. Waivers document comparison
method changes but never exclude data from comparison.

## Status rules

- **Green**: row counts, all L2 profiles, and all keyed L3 hashes match.
- **Amber**: the normal comparison is red, but applying only an open question's
  `value_map` to expected values makes the residual comparison green. The report
  records the question and residual result. An explicitly derived legacy failure
  can also be amber under the strict failure contract below; it never certifies
  row parity.
- **Red**: checksum, seed precheck, schema, comparison, execution, or evidence
  validation fails; or an open question does not fully explain the residual.

L4 reports up to 20 mismatching keys and column differences. Text is hashed unless
the corresponding column is explicitly marked plain. Duplicate keys are errors and
are never silently deduplicated.

Every conversion ticket adds `parity/objects/<object>.json` and
`parity/expected/<object>/`. Expected data and the derivation document must be
created independently under legacy semantics from the frozen seed, never by
running the converted object. Record comparison-method changes as waivers and
unresolved business semantics as questions.

Exit codes: `0` green, `2` amber, `1` red or error.

## Legacy objects with no valid relational result

An output can specify `expected_failure` (a JSON path) **instead of** `expected`.
The contract must document `legacy_outcome: "failure_no_relational_result"`, a
`reason`, an open business `question` (`id`, `question`, `decision_owner`, `status`),
and a `target_error` with an exact integer `errno`, five-character `sqlstate`, and
explicit uppercase `message_contains` diagnostic token. All three must match the
target query's exception. Raw exception messages are inspected in memory but
never persisted. Unexpected success (including zero rows), a different error,
seed/checksum/deploy failure, or any unrelated output mismatch is **red**.

A matching failure is always **amber**, with L1-L4 **not applicable**: it is not
an empty successful result and cannot earn a vacuous 100% hash match. This is a
fail-closed compatibility gate, not permission to label broken conversions green.
The `columns` remain a provisional target signature, not a certified result.
Only use this mode after independently documenting why the legacy object fails;
business approval and a new derived reference are needed before implementing a
repair. Error numbers/phases need not coincide across engines and must not be
represented as observed Teradata errors.

### DAILY_BALANCE_CHECK

```sh
python -m parity run --object daily_balance_check --as-of 2026-01-31
```

The actual macro has two SELECTs, and the first is invalid after aggregation.
The SQL UDTF compiles but deliberately rejects data-producing evaluation until
Q-DBC-1 is answered; it is **not ready for daily load use**. Its typed summary
signature is provisional. The separately compared timestamp-tie diagnostics are
not balance output parity. See `expected/daily_balance_check/DERIVATION.md` for
the documented semantics, source/seed hashes, counts and business question.
No FORMAT-to-string conversion or downstream BTEQ repair is made.
