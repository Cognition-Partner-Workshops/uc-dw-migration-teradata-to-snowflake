# Teradata reporting

Use the same required token passed to `tools/sf_landing.py`. The profile derives
`<token>_DB` and `<token>_WH`; sources use the target database. No token defaults
are supplied. Authentication uses the `SNOWFLAKE_NFR_ACCOUNT`,
`SNOWFLAKE_NFR_USER`, and `SNOWFLAKE_NFR_PRIVATE_KEY` environment variables.
`SNOWFLAKE_NFR_ROLE` is optional; when absent, Snowflake uses the user's default
role. Unset `SNOWFLAKE_HOST` before running dbt.

```bash
dbt build --project-dir dbt/teradata/reporting \
  --profiles-dir dbt/teradata/reporting --vars '{token: FSX_20261105}'
```

Sources default to `TD_TARGET`; override `core_schema` only for an isolated core
schema. The reporting clock defaults to `as_of_date: '2026-01-31'` in the project
and can be overridden alongside `token` with CLI vars.
