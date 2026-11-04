# Frozen landing reference — DERIVED, NOT EXECUTED

**No Teradata instance exists. These are independently derived expected outputs, not captured Teradata execution.**

## Scope and independence

This ticket certifies the landing of the frozen input, not the execution of a procedure,
macro, BTEQ script or the semantic parity of a view. On an empty target, landing has the
identity transformation: each CSV record becomes one row, in original Teradata column
order, retaining its declared decimal scale and nullable attributes. `derive_expected.py`
reads only `ddl/tables/`, the frozen manifest and frozen CSVs. It imports no target SQL,
Snowflake connector or target result. The derivation was saved before the first target load.
It deliberately shares the engine-neutral serialization/profile specification with the
live collector; this is not an independent second implementation of that specification.

`seed.json` is the checked-in expected result for all 13 tables: L1 counts, L2 profiles,
L3 hashes for every declared comparison key and one ordered table fingerprint. L4 compares
against those fixed results, not against newly generated expectations. A target run never
writes this reference. Regeneration refuses to overwrite; `--check` proves reproducibility.

## Hand derivation and fixture choices

- Business date: 2026-01-31. Frozen audit timestamp: 2026-01-31 06:00:00, UTC/session NTZ.
  Legacy `CURRENT_DATE`/`CURRENT_TIMESTAMP` is interpreted at that date/timestamp in future
  derived calculations. Original legacy SQL is unchanged; converted defaults/views are pinned.
- Dimensions: 15 customers, 20 accounts, 10 products, 14 branches from the repository's
  sample structure, with deterministic synthetic personal/contact/account labels. No source
  personal names, email addresses or home addresses are recopied. One customer exercises
  the full VARCHAR capacities. Customer 1010 is onboarded 2026-01-15 to exercise new-customer AML.
- Dates: 30 calendar years × 365 + 8 leap days = 10,958 rows, 2000-01-01–2029-12-31 inclusive.
  Gregorian Easter plus fixed Norwegian holidays are generated explicitly. Fiscal year = calendar year.
- Facts: 49,990 fixed-seed transactions + 10 restatements = 50,000 rows. Restatements retain
  the transaction ID but have another batch, so the L3 key is `(TRANSACTION_ID, ETL_BATCH_ID)`.
  Last two restatements have one shared 2026-01-31 23:59 timestamp and distinct balances;
  no choice between those balances is silently made. Baseline historical facts/snapshots
  are synthetic and not constrained to customer/account lifetimes.
- Snapshots: 96 month ends (2018-02–2026-01 inclusive) × 20 accounts = 1,920 rows.
- Exchange rates: six currency pairs to NOK for 2026-01-31, at six decimal places.
- Batch control: one completed prior batch. Error and log tables start empty.
- Staging transactions: 11 rows = 3 × NOK 44,000 structuring credits + NOK 100,000 credit /
  NOK 95,000 debit on the same date + 2 × EUR 3,000 international transfers + 2 tied-time
  transactions + 2 unknown-account rejects. Nine valid, two rejects. The international
  pair totals 69,000.738 NOK before per-row money rounding, above the NOK 50,000 threshold.
- Staging customers: five natural keys: unchanged, risk/KYC/segment change, NULL address
  change and two new customers. The NULL comparison behavior and any legacy SCD defect
  must remain visible in later procedure parity; no SCD procedure is executed here.

## Canonicalization and privacy

- `\N` alone is NULL; empty strings are distinct from NULL. CSV is UTF-8, pipe-delimited,
  quoted as needed, LF endings, one header, all columns in source physical order.
- INTEGER/BIGINT/SMALLINT/BYTEINT use exact integers; DECIMAL uses Python Decimal and the
  declared source scale, never binary floating point in comparison. Date is ISO; time and
  timestamp use six fractional digits and no timezone. CHAR right-padding is removed;
  VARCHAR case and trailing whitespace are retained. String comparisons here are lossless
  byte/value landing profiles, not a certification of Teradata linguistic collation behavior.
- L2: non-NULL count, NULL count, exact distinct count, typed min/max, numeric sum and
  maximum canonical length. Text min/max are SHA-256 fingerprints to avoid personal output.
- L3: key = compact JSON array of canonical key values; row = compact JSON array in
  source column order; SHA-256 over UTF-8. Duplicate keys are errors, never deduplicated.
  The table digest is SHA-256 of the sorted `(key,row hash)` pairs. JSON NULL is unambiguous.
- L4: up to 20 mismatching keys, row fingerprints and column-by-column differences;
  string values are represented by SHA-256, numeric/date values remain typed canonical text.
  An empty table has a vacuous 100% key match, explicitly disclosed in the evidence.

The manifest binds the business date, column order, row counts and SHA-256 of every CSV.
The expected reference binds the manifest digest. Do not edit seed, source SQL, expected
results or comparison rules to conceal a mismatch. New business decisions require a new
versioned fixture, not replacement of this one.
