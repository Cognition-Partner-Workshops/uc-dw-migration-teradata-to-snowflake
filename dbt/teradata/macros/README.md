# Teradata macro dbt-duckdb conversion

The project converts the three Teradata macros and the three AML BTEQ result
sets into nine dbt tables. Inputs are declared through the `td_core` source;
its schema is controlled by `td_core_schema` and defaults to
`td_src_macros`.

## Standalone build

From the repository root, install dependencies, load the post-run baseline
tables into the isolated source schema, and build the models:

```bash
python -m pip install -r requirements.txt
cd dbt/teradata/macros
export TD_DUCKDB_PATH="${TD_DUCKDB_PATH:-$PWD/target/td.duckdb}"
python load_inputs.py
dbt build --profiles-dir .
```

The loader only creates `td_src_macros.DIM_ACCOUNT`,
`td_src_macros.DIM_CUSTOMER`, and `td_src_macros.FACT_TRANSACTION`; it never
loads source data into `main`. The nine model tables are built in `main`.

To reconcile from the repository root:

```bash
python tools/reconcile.py --duckdb "$TD_DUCKDB_PATH" --schema main --report reports/td_macros.md
```

The repository-wide baseline contains other objects, so absent sibling objects
are expected to make the reconciliation command exit nonzero even when all nine
objects from this project are green.

For a combined build whose source tables already exist in `main`, do not run
the loader and override the source schema:

```bash
dbt build --profiles-dir . --vars '{td_core_schema: main}'
```

`CUSTOMER_TXN_HISTORY` uses `LIMIT 1000` as a fixture-only equivalent of the
Teradata `SAMPLE 1000`. It is not a general replacement for random sampling on
inputs with more than 1000 qualifying rows.
