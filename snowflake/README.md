# Banking warehouse — frozen Snowflake foundation

Business date **2026-01-31**, audit/load time **2026-01-31 06:00:00**. The Teradata
reference is **derived, not executed**; there is no Teradata instance.

## Inventory and provenance

The seven original tables and three views are converted under `ddl/` here from
`devin/1780460791-teradata-to-snowflake-ddl:snowflake/`. The October evidence pack on
`devin/1792160808-td-evidence-pack` supplied the starting fixed-seed generator and
the contract checks: all VARCHAR/CHAR capacities, decimal precision/scale and NOT NULL
constraints now match the original Teradata declarations. BYTEINT becomes SMALLINT;
timestamps are explicitly NTZ at source precision; NOT CASESPECIFIC uses `en-ci`.
Teradata SET uniqueness, primary indexes, physical partitioning, locking and statistics
do not translate into enforced Snowflake uniqueness. Key duplicates fail the landing gate.

| Assets | Source | Target |
|---|---|---|
| DIM_CUSTOMER, DIM_ACCOUNT, DIM_PRODUCT, DIM_BRANCH, DIM_DATE | `../ddl/tables/01*`–`05*` | `ddl/tables/01*`–`05*` |
| FACT_TRANSACTION, FACT_MONTHLY_ACCOUNT_SNAPSHOT | `../ddl/tables/06*`–`07*` | `ddl/tables/06*`–`07*` |
| Six previously missing staging/control/rate tables | `../ddl/tables/08*`–`13*` (inferred) | `ddl/tables/08*`–`13*` |
| VW_CUSTOMER_360, VW_REGULATORY_LARGE_TRANSACTIONS, VW_BRANCH_PERFORMANCE | `../ddl/views/` | `ddl/views/` |

All inferred columns and assumptions are in [`docs/inferred_ddl.md`](../docs/inferred_ddl.md).
The original seven table DDLs, views, procedures, macros, BTEQ scripts and validation
queries are unchanged. Target identity sequences start at 1,000,000: frozen surrogate
keys are explicit 1–20 and COPY does not advance a sequence; later SCD inserts must
not collide. The customer-360 latest-snapshot subquery is pre-ranked and joined instead
of using Snowflake's unsupported correlated `LIMIT`. Live compilation also exposed a
June `EFFECTIVE_TO` default precision mismatch; its cast now matches TIMESTAMP_NTZ(0).
No procedure or macro conversion is included in this foundation ticket.

## Reproduce

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r snowflake/requirements.txt
.venv/bin/python snowflake/generate_seed.py --check
.venv/bin/python snowflake/derive_expected.py --check
.venv/bin/pytest -q
.venv/bin/ruff check snowflake tests
.venv/bin/mypy snowflake
```

The generator uses seed 239 and refuses to overwrite an existing frozen directory.
`--check` regenerates in memory and compares bytes, not just row counts. Do not delete
and regenerate this frozen seed to resolve a future parity mismatch. The manifest
records CSV hashes, source seed hashes, physical columns, counts, the null token and dates.
Personal/contact/account fields are synthetic, not copied from the sample source.
The exact fixture arithmetic and serialization contract are in
[`parity/expected/DERIVATION.md`](../parity/expected/DERIVATION.md).

## Live load and reset

Provide `SFNFR_ACCOUNT`, `SFNFR_USER`, `SFNFR_ROLE`, `SFNFR_PRIVATE_KEY` through secure
environment bindings, not command-line literals or a checked-in configuration. JWT is
mandatory; the PEM is parsed in memory and never written. `SNOWFLAKE_HOST` is removed
because it may point to a different account. The supplied role is used unchanged;
secondary roles are disabled and there is no privileged-role fallback. Connection errors suppress raw text to avoid
printing credentials/account details; query ID and errno permit private diagnosis.

```sh
.venv/bin/python -u snowflake/load_seed.py --recreate --label initial_load
.venv/bin/python -u snowflake/load_seed.py --recreate --label repeat_load
# Non-mutating gate against the existing target:
.venv/bin/python -u snowflake/load_seed.py --verify-only --label verification
```

**`--recreate` destroys and recreates only `BANKING_DW.BANKING_DW`.** It refuses to replace
an existing schema unless its comment is exactly `managed-by=banking-frozen-seed:v1`.
Later ticket outputs in that schema will be erased by a deliberate seed reset.
The database `BANKING_DW` itself is not replaced. `WH_TD_BANKING` is X-Small, auto-resume,
60-second auto-suspend; an already-existing warehouse's settings are not altered.
The standalone migration uses the requested database and supplied JWT principal, not
the separate OtterWorks workload service-user/database provisioning scheme. Connections
carry `application=Devin_Demo` and a compact dev query tag with commit/run/session provenance.

The loader verifies SHA-256 before connecting, creates all 13 tables, PUTs compressed
CSVs to its internal `SEED_STAGE`, and COPYs with explicit filenames, exact field counts,
NULL token `\N` and `ON_ERROR=ABORT_STATEMENT` (no rejected rows tolerated). It checks
each COPY count, all manifest counts, all seven documented baseline counts, source
column order/type/length/scale/nullability, all L2 profiles and 100% L3 keyed hashes.
All three views are created and read. View semantic parity is explicitly not certified.
Each run writes Markdown and JSON to `evidence/seed_load/`; a failed comparison exits
nonzero, stays red and includes L4 mismatch fingerprints/column differences. Never
change the frozen input, source objects or comparison specification to make it green.

## Evidence

- [First load](../evidence/seed_load/initial_load.md) and [machine-readable report](../evidence/seed_load/initial_load.json)
- [Second destructive reset/load](../evidence/seed_load/repeat_load.md) and [machine-readable report](../evidence/seed_load/repeat_load.json)
- [Frozen derived reference](../parity/expected/seed.json)

The second load must produce the same table fingerprints without accumulating rows.
These reports certify **seed landing** only; AML/SCD2/staging patterns are inputs for
subsequent object tickets. Known ambiguous timestamp ties are retained, not silently
resolved in this ticket. No Teradata runtime or performance claim is made.
