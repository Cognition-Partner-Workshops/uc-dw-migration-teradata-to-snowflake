---
name: warehouse-exit
description: Regenerate the frozen Teradata fixture, land isolated inputs, reconcile migrated target rows and gate synthetic licence retirement.
---

# Warehouse exit mechanics

Legacy sources are under ddl/tables, ddl/views, dml/stored_procedures,
dml/macros and dml/scripts. Keep ddl/, dml/ and schemas/ unchanged.
Install the pinned dependencies with python -m pip install -r requirements.txt.

Run python tools/generate_seed.py --check and python tools/td_baseline.py --check.
Frozen inputs are under fixtures/frozen; inferred Teradata staging declarations
are under fixtures/ddl. baseline/teradata/README.md records derived semantics
and unresolved native-engine assumptions. The baseline was derived, not executed.
Never edit accepted seed or baseline files to make a target diff green.

Choose an uppercase alphanumeric/underscore token. Preview
python tools/sf_landing.py --token TOKEN --dry-run before requesting a live load.
Live authentication reads SNOWFLAKE_NFR_ACCOUNT, SNOWFLAKE_NFR_USER and
SNOWFLAKE_NFR_PRIVATE_KEY (PEM text) from the environment, with optional
SNOWFLAKE_NFR_ROLE and SNOWFLAKE_NFR_WAREHOUSE. The connector removes
SNOWFLAKE_HOST and parses the key in memory. Keep credentials out of files and logs.
The loader creates TOKEN_DB.TD_SOURCE, TOKEN_DB.TD_BASELINE and an empty
TOKEN_DB.TD_TARGET with TOKEN_WH. --expires sets the run comment.
For a deliberate repeat load, use --reload; --tables accepts qualified names
such as TD_SOURCE.STG_CUSTOMER and TD_BASELINE.DIM_CUSTOMER.

Write converted dbt models under dbt/teradata/ and build into TOKEN_DB.TD_TARGET.
The prerequisite fixture contains no converted Snowflake/dbt legacy models.
Preserve every baseline object's name, columns and result-set grain in the target.
Run python tools/reconcile.py --snowflake TOKEN_DB.TD_TARGET --report reports/teradata.md.
The default keys are tools/keys/teradata_keys.json. Local comparison uses
--duckdb PATH --schema main instead of --snowflake.
Reconciliation writes Markdown and JSON and exits nonzero for any mismatch.

Run python tools/licence_status.py --report reports/teradata.json
--output reports/licence.md. The synthetic ledger under licence/ledger.csv
marks a line RETIRED only when every covered object is green; absent objects
block retirement. A green derived fixture report does not establish native
HASHROW compatibility or authorize release of an actual vendor contract.

Preview python tools/sf_teardown.py --token TOKEN --dry-run, then run the same
command without --dry-run after the live exercise. Teardown suspends the exact
TOKEN_WH, sets retention to zero, drops TOKEN_DB and TOKEN_WH, and lists remaining
objects matching the token in either name or comment. Review any leftovers.
Run pytest -q and ruff check . for offline tool tests.
