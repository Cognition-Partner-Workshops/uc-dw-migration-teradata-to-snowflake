# Teradata view migration

The project builds the three legacy views and two BTEQ report result sets in
DuckDB. Inputs are the frozen post-procedure tables from the derived Teradata
baseline.

```bash
python -m pip install -r requirements.txt -r dbt/teradata/views/requirements.txt
export TD_DUCKDB_PATH=$PWD/target/td.duckdb
python dbt/teradata/views/load_inputs.py
dbt build --project-dir dbt/teradata/views --profiles-dir dbt/teradata/views
python tools/reconcile.py --duckdb $TD_DUCKDB_PATH --schema main --report reports/td_views.md
```

Override the pinned clock with `--vars '{current_date: YYYY-MM-DD}'`. Override
the input schema with `--vars '{td_core_schema: another_schema}'`.

Reconciliation runs on DuckDB (dbt-core 1.9.8, dbt-duckdb 1.9.6, duckdb 1.4.1);
no Snowflake credentials exist for this run.
