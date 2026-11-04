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
  records the question and residual result.
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
