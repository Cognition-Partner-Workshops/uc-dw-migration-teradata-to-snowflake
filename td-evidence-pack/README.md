# td-evidence-pack: proof-first Teradata → Snowflake migration

The other converter POCs answer "can we convert it?". This one answers the question a bank regulator and a
cut-over board actually ask: **"prove the new platform produces the same numbers."**

It dual-runs the original Teradata logic and a converted Snowflake candidate on identical data, reconciles
every table and regulatory view, and writes a self-contained HTML **evidence pack** that maps each check
to BCBS 239 principles, hashes every input and result (SHA-256 manifest), and ends in a sign-off block.
It is converter-agnostic: point it at any folder or git branch of converted Snowflake SQL.

## Run

```bash
cd td-evidence-pack
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# Compare the three Snowflake conversions already on team branches
python -m evidence_pack run --out evidence-out \
  --candidate "april-full-conversion=git:origin/devin/1775543616-teradata-to-snowflake-migration:snowflake/ddl" \
  --candidate "june-ddl-conversion=git:origin/devin/1780460791-teradata-to-snowflake-ddl:snowflake" \
  --candidate "july-ddl-conversion=git:origin/devin/1783442262-snowflake-ddl-migration:snowflake/ddl"
open evidence-out/index.html
```

`--candidate NAME=dir:PATH` works for any converter output folder. Exit code is non-zero if any candidate
fails, so it can gate CI.

## What gets checked

| Check | How |
| --- | --- |
| Completeness | Row counts; missing / unexpected rows counted by business key (`controls.json`) |
| Accuracy | Order-independent SHA-256 fingerprint per object; per-column null, distinct and control totals |
| Report accuracy | Regulatory views reconciled row by row; critical-data-element totals by reporting category |
| Type drift | Result column type families (e.g. `DECIMAL → VARCHAR` from a `TO_CHAR` rewrite) |
| Schema conformance | Declared Teradata vs Snowflake types (scale changes, shortened VARCHARs, lost precision, dropped NOT NULL) |
| Lineage | Column-level lineage of each view computed on both sides with sqlglot (advisory) |
| Waivers | Known, approved differences (e.g. `HASHROW` → `HASH`) documented with justification and approver role |

## How the dual run works

- **Data:** dimensions from `data/seed`; facts, SCD2 history rows, restated transactions and a closed branch
  are generated from a fixed seed, so every run is bit-for-bit reproducible. No customer data.
- **Legacy side:** the original files in `ddl/` are interpreted with Teradata semantics on DuckDB
  (`evidence_pack/engines.py: TeradataEmulator`).
- **Target side:** the converted Snowflake SQL is run *as written* via sqlglot on DuckDB (`SnowflakeEmulator`).
- **Business date** is pinned (`--as-of`) on both sides so `CURRENT_DATE` logic is comparable.
- Every emulation rewrite is disclosed in the pack. Where Teradata semantics are ambiguous
  (e.g. `CSUM`/`MAVG` reset behaviour), the object is flagged for SME confirmation.

## Limits (be explicit with stakeholders)

- Both engines are emulated locally on DuckDB. This proves the converted logic is equivalent to the original
  on the same data; it does not prove Snowflake engine behaviour. The engine classes are the seam for real
  Teradata (`teradatasql`) and Snowflake (`snowflake-connector-python`) connections.
- Macros, stored procedures and BTEQ scripts are out of scope for this version.
- The pack supports, but does not by itself certify, BCBS 239 compliance.

## Develop

```bash
pytest -q
ruff check .
```
