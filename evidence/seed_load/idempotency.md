# Idempotency gate: GREEN — DERIVED, NOT EXECUTED reference

**Teradata expectations are independently derived from the frozen seed; no Teradata instance exists.**

Two live runs used `load_seed.py --recreate`, not a COPY no-op or dry run. Each run
replaced the marked schema, created 13 tables and three views, and used an internal-stage
PUT/COPY for every CSV, with strict field counts and abort-on-error.

| Check | Initial load | Second reset/load |
|---|---|---|
| Total landed rows | 62,960 | 62,960 |
| Manifest row counts | 13/13 match | 13/13 match |
| Original documented baseline counts | 7/7 match | 7/7 match |
| L2 column profiles | all match | all match |
| L3 keyed hashes | 100% each table | 100% each table |
| L4 mismatches | 0 | 0 |
| Live source column contract errors | 0 | 0 |
| Supplied role verified | yes | yes |
| Converted views compile/read | 3/3 | 3/3 |

All 13 table fingerprints and the frozen manifest digest are identical between runs.
Empty error/log tables have a vacuous 100% L3 match. Live view row counts agree too:
15 customer-360, 5,478 regulatory transactions and 250 branch-performance rows.
View semantic parity, procedures and macros are **not** certified by this landing gate.

Machine evidence, including per-table COPY/SELECT query IDs and full profiles:
[initial JSON](initial_load.json), [repeat JSON](repeat_load.json).
Human summaries: [initial](initial_load.md), [repeat](repeat_load.md).
Reference derivation: [DERIVATION.md](../../parity/expected/DERIVATION.md).

Offline verification: `pytest -q` (24 passed), `ruff check snowflake tests` and
`mypy snowflake` pass. Byte-for-byte generator regeneration and independent-reference
regeneration both pass. An adversarial offline value/count/duplicate-key test proves
that a mismatch stays red; no frozen data, original SQL or comparison rules were
changed in response to a Snowflake result.

DDL corrections were made before successful loads: preserve all source VARCHAR/CHAR
capacities, DECIMAL precision/scale and NOT NULL; fix the June EFFECTIVE_TO default
cast to precision zero; pre-rank the customer-360 latest snapshot instead of unsupported
correlated LIMIT. Inferred tables and synthetic personal-field substitutions were
established before the one-time freeze.
